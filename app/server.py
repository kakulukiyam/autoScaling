#!/usr/bin/env python3
"""Backend ligero para el laboratorio visual de AWS Auto Scaling y Balanceo de Carga."""

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import multiprocessing
import os
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request


AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
ASG_NAME = os.environ.get("ASG_NAME", "autoscaling-lab-asg-prod")
TARGET_GROUP_ARN = os.environ.get("TARGET_GROUP_ARN", "")
SCALE_UP_ALARM_NAME = os.environ.get("SCALE_UP_ALARM_NAME", "autoscaling-lab-scale-up-prod")
SCALE_DOWN_ALARM_NAME = os.environ.get("SCALE_DOWN_ALARM_NAME", "autoscaling-lab-scale-down-prod")

_METADATA_CACHE = None
_CPU_LOCK = threading.Lock()
_CPU_PERCENT = 0.0

_STRESS_LOCK = threading.Lock()
_STRESS_WORKERS = []
_STRESS_STOP_EVENT = None
_STRESS_END_TIME = 0.0
_CLUSTER_THREAD = None
_CLUSTER_STOP_EVENT = None

_AWS_CACHE_LOCK = threading.Lock()
_AWS_CACHE_DATA = None
_AWS_CACHE_TS = 0.0


def _read_proc_stat():
    with open("/proc/stat", "r", encoding="utf-8") as fh:
        line = fh.readline()
    parts = [int(x) for x in line.split()[1:8]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    total = sum(parts)
    return idle, total


def _cpu_monitor_loop():
    global _CPU_PERCENT
    try:
        prev_idle, prev_total = _read_proc_stat()
    except Exception:
        return
    while True:
        time.sleep(1.0)
        try:
            idle, total = _read_proc_stat()
            d_idle = idle - prev_idle
            d_total = total - prev_total
            prev_idle, prev_total = idle, total
            if d_total > 0:
                usage = round(100.0 * (1.0 - d_idle / d_total), 1)
                with _CPU_LOCK:
                    _CPU_PERCENT = max(0.0, min(100.0, usage))
        except Exception:
            pass


def get_cpu_percent():
    with _CPU_LOCK:
        return _CPU_PERCENT


def get_instance_metadata():
    global _METADATA_CACHE
    if _METADATA_CACHE is not None:
        return _METADATA_CACHE

    info = {
        "instance_id": socket.gethostname(),
        "availability_zone": "unknown",
        "private_ip": "127.0.0.1",
        "instance_type": "t3.micro",
        "hostname": socket.gethostname(),
    }

    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
        )
        with urllib.request.urlopen(token_req, timeout=2) as resp:
            token = resp.read().decode("utf-8")

        def _fetch(path):
            req = urllib.request.Request(
                f"http://169.254.169.254/latest/meta-data/{path}",
                headers={"X-aws-ec2-metadata-token": token},
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                return r.read().decode("utf-8").strip()

        info["instance_id"] = _fetch("instance-id")
        info["availability_zone"] = _fetch("placement/availability-zone")
        info["private_ip"] = _fetch("local-ipv4")
        info["instance_type"] = _fetch("instance-type")
        _METADATA_CACHE = info
    except Exception:
        pass

    return info


def _cpu_burner(stop_flag, end_ts):
    try:
        os.nice(10)
    except Exception:
        pass
    x = 1.0001
    while not stop_flag.is_set() and time.time() < end_ts:
        for _ in range(50000):
            x = math.sqrt(x * x + 1.234567) % 1000.0 + 1.0


def _stop_local_stress():
    global _STRESS_WORKERS, _STRESS_STOP_EVENT, _STRESS_END_TIME
    with _STRESS_LOCK:
        if _STRESS_STOP_EVENT is not None:
            _STRESS_STOP_EVENT.set()
        for proc in _STRESS_WORKERS:
            if proc.is_alive():
                proc.terminate()
        for proc in _STRESS_WORKERS:
            proc.join(timeout=1.0)
        _STRESS_WORKERS = []
        _STRESS_STOP_EVENT = None
        _STRESS_END_TIME = 0.0


def _start_local_stress(duration_sec):
    global _STRESS_WORKERS, _STRESS_STOP_EVENT, _STRESS_END_TIME
    _stop_local_stress()
    duration_sec = max(10, min(900, int(duration_sec)))
    end_ts = time.time() + duration_sec
    stop_event = multiprocessing.Event()
    num_workers = max(2, os.cpu_count() or 2)
    workers = []
    for _ in range(num_workers):
        proc = multiprocessing.Process(target=_cpu_burner, args=(stop_event, end_ts), daemon=True)
        proc.start()
        workers.append(proc)
    with _STRESS_LOCK:
        _STRESS_WORKERS = workers
        _STRESS_STOP_EVENT = stop_event
        _STRESS_END_TIME = end_ts
    return num_workers, duration_sec


def _is_stress_active():
    with _STRESS_LOCK:
        alive = any(p.is_alive() for p in _STRESS_WORKERS)
        remaining = max(0, int(_STRESS_END_TIME - time.time())) if alive else 0
        return alive and remaining > 0, remaining


def _run_aws_cli(args):
    cmd = ["aws", "--region", AWS_REGION, "--output", "json"] + args
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"aws cli error ({res.returncode})")
    return json.loads(res.stdout) if res.stdout.strip() else {}


def _get_peer_private_ips():
    asg_resp = _run_aws_cli([
        "autoscaling", "describe-auto-scaling-groups",
        "--auto-scaling-group-names", ASG_NAME,
    ])
    groups = asg_resp.get("AutoScalingGroups", [])
    if not groups:
        return []
    ids = [i["InstanceId"] for i in groups[0].get("Instances", [])]
    if not ids:
        return []
    ec2_resp = _run_aws_cli(["ec2", "describe-instances", "--instance-ids"] + ids)
    ips = []
    for res in ec2_resp.get("Reservations", []):
        for inst in res.get("Instances", []):
            if inst.get("State", {}).get("Name") == "running" and inst.get("PrivateIpAddress"):
                ips.append(inst["PrivateIpAddress"])
    return ips


def _call_peer(ip, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://{ip}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.read().decode("utf-8")


def _cluster_coordinator_loop(stop_event, end_ts):
    my_ip = get_instance_metadata().get("private_ip")
    while not stop_event.is_set() and time.time() < end_ts:
        remaining = int(end_ts - time.time())
        if remaining <= 5:
            break
        try:
            for ip in _get_peer_private_ips():
                if ip == my_ip:
                    continue
                try:
                    info_raw = urllib.request.urlopen(f"http://{ip}/api/info", timeout=2).read().decode("utf-8")
                    info = json.loads(info_raw)
                    if not info.get("stress_active"):
                        _call_peer(ip, "/api/stress?local=1", {"duration": remaining, "cluster": False})
                except Exception:
                    pass
        except Exception:
            pass
        stop_event.wait(10.0)


def _stop_cluster_stress():
    global _CLUSTER_THREAD, _CLUSTER_STOP_EVENT
    if _CLUSTER_STOP_EVENT is not None:
        _CLUSTER_STOP_EVENT.set()
    _CLUSTER_THREAD = None
    _CLUSTER_STOP_EVENT = None
    _stop_local_stress()
    my_ip = get_instance_metadata().get("private_ip")
    try:
        for ip in _get_peer_private_ips():
            if ip == my_ip:
                continue
            try:
                _call_peer(ip, "/api/stress/stop?local=1", {"cluster": False})
            except Exception:
                pass
    except Exception:
        pass


def _start_cluster_stress(duration_sec):
    global _CLUSTER_THREAD, _CLUSTER_STOP_EVENT
    if _CLUSTER_STOP_EVENT is not None:
        _CLUSTER_STOP_EVENT.set()
    workers, dur = _start_local_stress(duration_sec)
    stop_event = threading.Event()
    _CLUSTER_STOP_EVENT = stop_event
    thread = threading.Thread(
        target=_cluster_coordinator_loop,
        args=(stop_event, time.time() + dur),
        daemon=True,
    )
    thread.start()
    _CLUSTER_THREAD = thread
    return workers, dur


def _aws_refresh_loop():
    while True:
        try:
            _refresh_aws_status_once()
        except Exception:
            pass
        time.sleep(5.0)


def fetch_aws_status():
    with _AWS_CACHE_LOCK:
        if _AWS_CACHE_DATA is not None:
            return _AWS_CACHE_DATA
    return _refresh_aws_status_once()


def _refresh_aws_status_once():
    global _AWS_CACHE_DATA, _AWS_CACHE_TS

    result = {
        "asg": None,
        "instances": [],
        "alarms": [],
        "cpu_history": [],
        "activities": [],
        "error": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        asg_resp = _run_aws_cli([
            "autoscaling", "describe-auto-scaling-groups",
            "--auto-scaling-group-names", ASG_NAME,
        ])
        groups = asg_resp.get("AutoScalingGroups", [])
        if groups:
            g = groups[0]
            asg_instances = g.get("Instances", [])
            result["asg"] = {
                "name": g.get("AutoScalingGroupName"),
                "min_size": g.get("MinSize"),
                "max_size": g.get("MaxSize"),
                "desired_capacity": g.get("DesiredCapacity"),
                "total_instances": len(asg_instances),
                "in_service_count": sum(1 for i in asg_instances if i.get("LifecycleState") == "InService"),
                "pending_count": sum(1 for i in asg_instances if "Pending" in i.get("LifecycleState", "")),
                "terminating_count": sum(1 for i in asg_instances if "Terminating" in i.get("LifecycleState", "")),
            }

            tg_health = {}
            if TARGET_GROUP_ARN:
                try:
                    tg_resp = _run_aws_cli([
                        "elbv2", "describe-target-health",
                        "--target-group-arn", TARGET_GROUP_ARN,
                    ])
                    for d in tg_resp.get("TargetHealthDescriptions", []):
                        tid = d.get("Target", {}).get("Id")
                        tg_health[tid] = d.get("TargetHealth", {}).get("State", "unknown")
                except Exception:
                    pass

            ec2_details = {}
            ids = [i["InstanceId"] for i in asg_instances]
            if ids:
                ec2_resp = _run_aws_cli(["ec2", "describe-instances", "--instance-ids"] + ids)
                for res in ec2_resp.get("Reservations", []):
                    for inst in res.get("Instances", []):
                        ec2_details[inst["InstanceId"]] = {
                            "private_ip": inst.get("PrivateIpAddress", "-"),
                            "instance_type": inst.get("InstanceType", "t3.micro"),
                            "state": inst.get("State", {}).get("Name", "unknown"),
                            "launch_time": inst.get("LaunchTime", ""),
                        }

            for i in asg_instances:
                iid = i["InstanceId"]
                det = ec2_details.get(iid, {})
                result["instances"].append({
                    "instance_id": iid,
                    "availability_zone": i.get("AvailabilityZone", "-"),
                    "lifecycle_state": i.get("LifecycleState", "-"),
                    "health_status": i.get("HealthStatus", "-"),
                    "target_health": tg_health.get(iid, "not-registered"),
                    "private_ip": det.get("private_ip", "-"),
                    "instance_type": det.get("instance_type", "t3.micro"),
                    "ec2_state": det.get("state", "-"),
                })

        alarms_resp = _run_aws_cli([
            "cloudwatch", "describe-alarms",
            "--alarm-names", SCALE_UP_ALARM_NAME, SCALE_DOWN_ALARM_NAME,
        ])
        for a in alarms_resp.get("MetricAlarms", []):
            result["alarms"].append({
                "name": a.get("AlarmName"),
                "state": a.get("StateValue"),
                "reason": a.get("StateReason"),
                "threshold": a.get("Threshold"),
                "comparison": a.get("ComparisonOperator"),
                "period": a.get("Period"),
                "evaluation_periods": a.get("EvaluationPeriods"),
                "updated_at": a.get("StateUpdatedTimestamp"),
            })

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(minutes=20)
        metrics_resp = _run_aws_cli([
            "cloudwatch", "get-metric-statistics",
            "--namespace", "AWS/EC2",
            "--metric-name", "CPUUtilization",
            "--dimensions", f"Name=AutoScalingGroupName,Value={ASG_NAME}",
            "--start-time", start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "--end-time", end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "--period", "60",
            "--statistics", "Average",
        ])
        dps = sorted(metrics_resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
        result["cpu_history"] = [
            {"timestamp": d["Timestamp"], "average": round(d["Average"], 2)}
            for d in dps
        ]

        act_resp = _run_aws_cli([
            "autoscaling", "describe-scaling-activities",
            "--auto-scaling-group-name", ASG_NAME,
            "--max-items", "8",
        ])
        for act in act_resp.get("Activities", []):
            result["activities"].append({
                "id": act.get("ActivityId"),
                "description": act.get("Description"),
                "cause": act.get("Cause"),
                "status": act.get("StatusCode"),
                "start_time": act.get("StartTime"),
            })
    except Exception as exc:
        result["error"] = str(exc)

    with _AWS_CACHE_LOCK:
        _AWS_CACHE_DATA = result
        _AWS_CACHE_TS = time.time()

    return result


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/info":
            meta = get_instance_metadata()
            stress_active, remaining = _is_stress_active()
            self._send_json(200, {
                **meta,
                "cpu_percent": get_cpu_percent(),
                "stress_active": stress_active,
                "stress_remaining_sec": remaining,
                "cluster_coordinator_active": _CLUSTER_STOP_EVENT is not None and not _CLUSTER_STOP_EVENT.is_set(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        if parsed.path == "/api/aws-status":
            self._send_json(200, fetch_aws_status())
            return

        if parsed.path == "/health":
            self._send_json(200, {"status": "healthy"})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        body = self._read_json_body()
        local_only = qs.get("local", ["0"])[0] == "1" or body.get("cluster") is False

        if parsed.path == "/api/stress":
            duration = body.get("duration", qs.get("duration", ["300"])[0])
            if local_only:
                workers, dur = _start_local_stress(duration)
                mode = "local"
            else:
                workers, dur = _start_cluster_stress(duration)
                mode = "cluster"
            meta = get_instance_metadata()
            self._send_json(200, {
                "status": "started",
                "mode": mode,
                "workers": workers,
                "duration_sec": dur,
                "handled_by": meta["instance_id"],
            })
            return

        if parsed.path == "/api/stress/stop":
            if local_only:
                _stop_local_stress()
                mode = "local"
            else:
                _stop_cluster_stress()
                mode = "cluster"
            meta = get_instance_metadata()
            self._send_json(200, {
                "status": "stopped",
                "mode": mode,
                "handled_by": meta["instance_id"],
            })
            return

        self._send_json(404, {"error": "Not found"})


def main():
    threading.Thread(target=_cpu_monitor_loop, daemon=True).start()
    threading.Thread(target=_aws_refresh_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 8080), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

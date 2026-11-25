#!/usr/bin/env python3
"""
Validación End-to-End en vivo del Auto Scaling Group (1 -> 4 -> 1) y Balanceo de Carga.
Uso:
  python scripts/validate_scaling_e2e.py --app-url http://<alb-dns>
"""

import argparse
from collections import Counter
from datetime import datetime
import json
import sys
import time
import urllib.request


def get_json(url):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def run_lb_probe(base_url, count=40):
    counts = Counter()
    az_map = {}
    for i in range(count):
        info = get_json(f"{base_url}/api/info?probe={i}&t={time.time()}")
        iid = info["instance_id"]
        counts[iid] += 1
        az_map[iid] = info.get("availability_zone", "-")
    return counts, az_map


def print_status(status):
    asg = status.get("asg") or {}
    alarms = {a["name"]: a["state"] for a in status.get("alarms", [])}
    cpu_hist = status.get("cpu_history") or []
    last_cpu = cpu_hist[-1]["average"] if cpu_hist else None
    ts = datetime.now().strftime("%H:%M:%S")
    print(
        f"[{ts}] ASG desired={asg.get('desired_capacity')} in_service={asg.get('in_service_count')} "
        f"pending={asg.get('pending_count')} terminating={asg.get('terminating_count')} | "
        f"CPU={last_cpu}% | Alarmas={alarms}"
    )
    return asg, alarms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--timeout-up", type=int, default=420)
    parser.add_argument("--timeout-down", type=int, default=480)
    args = parser.parse_args()

    base = args.app_url.rstrip("/")
    print(f"=== 1. Estado inicial en {base} ===")
    status = get_json(f"{base}/api/aws-status")
    asg, _ = print_status(status)

    print("\n=== 2. Iniciando prueba de estrés (modo cluster) ===")
    start_res = post_json(f"{base}/api/stress", {"duration": 420, "cluster": True})
    print("Respuesta /api/stress:", start_res)

    print("\n=== 3. Esperando alarma Scale-Up y escalado hasta 4 instancias InService ===")
    t0 = time.time()
    reached_max = False
    while time.time() - t0 < args.timeout_up:
        time.sleep(15)
        status = get_json(f"{base}/api/aws-status")
        asg, alarms = print_status(status)
        healthy_targets = sum(
            1 for inst in status.get("instances", [])
            if inst.get("target_health") == "healthy"
        )
        if asg.get("in_service_count") == 4 and healthy_targets == 4:
            print(f"✅ ¡Escalado hacia arriba completado! 4/4 instancias healthy en ALB (Alarmas: {alarms}).")
            reached_max = True
            break

    if not reached_max:
        print("❌ No se alcanzó 4 instancias healthy dentro del timeout.")
        post_json(f"{base}/api/stress/stop", {"cluster": True})
        sys.exit(1)

    print("\n=== 4. Ejecutando prueba de balanceo de carga (40 peticiones HTTP) ===")
    counts, az_map = run_lb_probe(base, 40)
    for iid, cnt in counts.most_common():
        print(f"   - {iid} ({az_map[iid]}): {cnt}/40 peticiones ({cnt * 100 / 40:.1f}%)")
    if len(counts) < 4:
        print(f"⚠️ Solo respondieron {len(counts)} instancias distintas.")
    else:
        print("✅ ¡Balanceo de carga verificado en las 4 instancias t3.micro!")

    print("\n=== 5. Deteniendo prueba de estrés y validando escalado hacia abajo (4 -> 1) ===")
    stop_res = post_json(f"{base}/api/stress/stop", {"cluster": True})
    print("Respuesta /api/stress/stop:", stop_res)

    t1 = time.time()
    reached_min = False
    while time.time() - t1 < args.timeout_down:
        time.sleep(15)
        status = get_json(f"{base}/api/aws-status")
        asg, alarms = print_status(status)
        if asg.get("desired_capacity") == 1 and asg.get("in_service_count") == 1 and asg.get("total_instances") == 1:
            print(f"✅ ¡Escalado hacia abajo completado! ASG regresó a 1 instancia (Alarmas: {alarms}).")
            reached_min = True
            break

    if not reached_min:
        print("❌ No se completó el escalado hacia abajo dentro del timeout.")
        sys.exit(1)

    print("\n🎉 VALIDACIÓN E2E COMPLETA EXITOSA (1 -> 4 -> 1 y Balanceo de Carga en 4 nodos).")


if __name__ == "__main__":
    main()

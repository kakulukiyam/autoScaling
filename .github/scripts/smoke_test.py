#!/usr/bin/env python3
"""Smoke tests post-despliegue para el proyecto AWS Auto Scaling + Nginx."""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def check_endpoint(name, url, validator, retries=30, delay=10):
    print(f"\n🔍 [PROBANDO] {name}: {url}")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GitHubActions-SmokeTest/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.getcode()
                body = resp.read().decode("utf-8")
                if code == 200:
                    ok, msg = validator(body)
                    if ok:
                        print(f"   ✅ [EXITOSO] {msg} (intento {attempt})")
                        return True
                    print(f"   ⚠️ Intento {attempt}/{retries}: {msg}")
                else:
                    print(f"   ⚠️ Intento {attempt}/{retries}: HTTP {code}")
        except urllib.error.HTTPError as exc:
            print(f"   ⚠️ Intento {attempt}/{retries}: HTTP {exc.code}")
        except Exception as exc:
            print(f"   ⚠️ Intento {attempt}/{retries}: {exc}")
        if attempt < retries:
            time.sleep(delay)
    print(f"   ❌ [FALLÓ] {name}")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--asg-name", required=True)
    args = parser.parse_args()

    base = args.app_url.rstrip("/")
    print("=" * 70)
    print(f"🚀 SMOKE TESTS POST-DESPLIEGUE: {base}")
    print("=" * 70)

    results = []

    results.append(check_endpoint(
        "1. Panel Web Nginx (/)",
        f"{base}/",
        lambda body: (
            "auto scaling" in body.lower() and "prueba de estrés" in body.lower(),
            "Panel HTML de Auto Scaling cargado correctamente",
        ),
        retries=30,
        delay=10,
    ))

    results.append(check_endpoint(
        "2. Health Check ALB (/health)",
        f"{base}/health",
        lambda body: (
            json.loads(body).get("status") == "healthy",
            "Endpoint /health responde healthy",
        ),
        retries=12,
        delay=5,
    ))

    results.append(check_endpoint(
        "3. Metadata del Nodo (/api/info)",
        f"{base}/api/info",
        lambda body: (
            json.loads(body).get("instance_type") == "t3.micro" and bool(json.loads(body).get("instance_id")),
            f"Instancia {json.loads(body).get('instance_id')} (t3.micro) respondiendo",
        ),
        retries=12,
        delay=5,
    ))

    def validate_aws(body):
        data = json.loads(body)
        asg = data.get("asg") or {}
        alarms = data.get("alarms") or []
        ok = (
            asg.get("name") == args.asg_name
            and asg.get("min_size") == 1
            and asg.get("max_size") == 4
            and asg.get("in_service_count", 0) >= 1
            and len(alarms) == 2
        )
        return ok, (
            f"ASG {asg.get('name')} Min={asg.get('min_size')} Max={asg.get('max_size')} "
            f"InService={asg.get('in_service_count')} Alarmas={len(alarms)}"
        )

    results.append(check_endpoint(
        "4. Estado AWS ASG y Alarmas (/api/aws-status)",
        f"{base}/api/aws-status",
        validate_aws,
        retries=12,
        delay=5,
    ))

    if all(results):
        print("\n🎉 ¡TODOS LOS SMOKE TESTS PASARON!")
        sys.exit(0)
    print("\n💥 AL MENOS UN SMOKE TEST FALLÓ.")
    sys.exit(1)


if __name__ == "__main__":
    main()

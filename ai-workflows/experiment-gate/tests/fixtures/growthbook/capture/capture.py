#!/usr/bin/env python3
"""Dev-only: capture GrowthBook experiment-results exports from a throwaway self-hosted instance.

Starts GrowthBook + MongoDB + a Postgres "warehouse" with docker-compose, loads the synthetic events in
``seed.sql``, defines three experiments through GrowthBook's REST API, runs the analysis snapshots and
saves the raw ``GET /api/v1/experiments/{id}/results`` response bodies byte for byte. Then it tears the
stack down. Standard library only; needs ``docker-compose`` and a running Docker engine.

    python3 capture.py --out ..            # writes ../ranker-v*.results.json, ../fact-metrics.json, ../instance.json

Everything the instance holds is synthetic and is deleted with ``docker-compose down -v``. The only calls
that are not part of GrowthBook's documented REST API are the sign-up calls the web UI itself makes
(``/auth/register``, ``/organization``, ``/keys``) so that an API key exists without opening a browser.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "http://localhost:3100"
EMAIL, PASSWORD = "capture@example.com", "capture-only-pw-123"

# tracking key (matches experiment_id in seed.sql) -> stats engine
EXPERIMENTS = {"ranker-v2": "bayesian", "ranker-v3": "frequentist", "ranker-v4": "frequentist"}


def compose(*args: str, stdin=None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker-compose", *args], cwd=HERE, stdin=stdin, check=check)


def http(method: str, path: str, body=None, headers=None, raw: bool = False):
    request = urllib.request.Request(
        API + path, method=method, data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path} -> {exc.code}: {exc.read().decode()[:600]}")
    return data if raw else json.loads(data)


def wait_for(predicate, what: str, seconds: int = 240):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if predicate():
                return
        except (urllib.error.URLError, ConnectionError, subprocess.CalledProcessError):
            pass
        time.sleep(3)
    sys.exit(f"timed out waiting for {what}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="directory that receives the exports")
    parser.add_argument("--keep", action="store_true", help="leave the containers running")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    compose("down", "-v", "--remove-orphans", check=False)
    try:
        compose("up", "-d", "mongo", "warehouse")
        wait_for(lambda: compose("exec", "-T", "warehouse", "pg_isready", "-U", "warehouse", "-d", "events",
                                 "-h", "127.0.0.1").returncode == 0, "Postgres")
        time.sleep(5)  # the entrypoint restarts Postgres once after initdb
        wait_for(lambda: compose("exec", "-T", "warehouse", "pg_isready", "-U", "warehouse", "-d", "events",
                                 "-h", "127.0.0.1").returncode == 0, "Postgres")
        with open(HERE / "seed.sql", "rb") as seed:
            compose("exec", "-T", "warehouse", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "warehouse",
                    "-d", "events", stdin=seed)
        compose("up", "-d", "growthbook")
        wait_for(lambda: http("GET", "/healthcheck")["healthy"], "GrowthBook")

        # Sign-up as the web UI does it, then an admin secret key for the REST API.
        http("POST", "/auth/register", {"name": "Capture", "email": EMAIL, "password": PASSWORD})
        token = http("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})["token"]
        org = http("POST", "/organization", {"company": "Synthetic capture org"},
                   {"Authorization": f"Bearer {token}"})["orgId"]
        key = http("POST", "/keys", {"description": "capture", "type": "admin"},
                   {"Authorization": f"Bearer {token}", "X-Organization": org})["key"]["key"]
        auth = {"Authorization": f"Bearer {key}"}

        def api(method, path, body=None, raw=False):
            return http(method, "/api/v1" + path, body, auth, raw)

        # Fact tables and metrics (documented REST API).
        tables = {}
        for name, sql in [
            ("Orders", 'SELECT user_id, "timestamp" AS timestamp, order_id, amount FROM orders'),
            ("Refunds", 'SELECT user_id, "timestamp" AS timestamp FROM refunds'),
            ("Page loads", 'SELECT user_id, "timestamp" AS timestamp, load_ms FROM page_loads'),
        ]:
            tables[name] = api("POST", "/fact-tables", {
                "name": name, "datasource": "warehouse", "userIdTypes": ["user_id"], "sql": sql})["factTable"]["id"]

        def metric(**body) -> str:
            return api("POST", "/fact-metrics", body)["factMetric"]["id"]

        purchase = metric(name="Purchase rate", metricType="proportion",
                          numerator={"factTableId": tables["Orders"], "column": ""})
        revenue = metric(name="Revenue per user", metricType="mean",
                         numerator={"factTableId": tables["Orders"], "column": "amount", "aggregation": "sum"})
        order_value = metric(name="Average order value", metricType="ratio",
                             numerator={"factTableId": tables["Orders"], "column": "amount", "aggregation": "sum"},
                             denominator={"factTableId": tables["Orders"], "column": "$$count"})
        refund = metric(name="Refund rate", metricType="proportion", inverse=True,
                        numerator={"factTableId": tables["Refunds"], "column": ""})
        load = metric(name="Page load ms", metricType="mean", inverse=True,
                      numerator={"factTableId": tables["Page loads"], "column": "load_ms", "aggregation": "sum"})

        ids = {}
        for tracking_key, engine in EXPERIMENTS.items():
            experiment = api("POST", "/experiments", {
                "datasourceId": "warehouse", "assignmentQueryId": "user_id", "trackingKey": tracking_key,
                "name": f"Offer ranker {tracking_key[-2:]}", "type": "standard", "status": "running",
                "hypothesis": "Synthetic: the candidate ranker raises purchase rate without hurting refunds, "
                              "latency or order value.",
                "metrics": [purchase], "secondaryMetrics": [revenue],
                "guardrailMetrics": [refund, load, order_value], "statsEngine": engine, "hashAttribute": "id",
                "variations": [{"key": "0", "name": "Control"}, {"key": "1", "name": "Candidate"}],
                "phases": [{"name": "Main", "dateStarted": "2026-09-01T00:00:00.000Z",
                            "dateEnded": "2026-09-20T00:00:00.000Z", "coverage": 1,
                            "reasonForStopping": "synthetic capture"}],
            })["experiment"]
            ids[tracking_key] = experiment["id"]

        snapshots = {key_: api("POST", f"/experiments/{id_}/snapshot", {})["snapshot"]["id"]
                     for key_, id_ in ids.items()}
        for key_, snapshot in snapshots.items():
            def done(snapshot=snapshot, key_=key_):
                status = api("GET", f"/snapshots/{snapshot}")["snapshot"]["status"]
                if status == "error":
                    sys.exit(f"snapshot for {key_} failed")
                return status == "success"
            wait_for(done, f"snapshot of {key_}")

        for tracking_key, id_ in ids.items():
            (out / f"{tracking_key}.results.json").write_bytes(api("GET", f"/experiments/{id_}/results", raw=True))
        (out / "fact-metrics.json").write_bytes(api("GET", "/fact-metrics", raw=True))
        (out / "instance.json").write_bytes(http("GET", "/", raw=True))
        print("metric ids:", json.dumps({"Purchase rate": purchase, "Revenue per user": revenue,
                                         "Average order value": order_value, "Refund rate": refund,
                                         "Page load ms": load}, indent=1))
    finally:
        if not args.keep:
            compose("down", "-v", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()

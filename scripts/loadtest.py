"""QA-001 load test: signed-webhook flood + API latency percentiles (asyncio).

Usage:
  python scripts/loadtest.py [--events 400] [--requests 150]
Creates/uses sqlite:///./data/loadtest.db and seeds merchant mer1 if empty.
Prints MEASURED throughput and p50/p95/p99 only.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import statistics
import time

import httpx


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, max(0, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body,
                                hashlib.sha256).hexdigest()


def build_events(n: int) -> list[dict]:
    """~n webhook payloads from the seeded generator (created+terminal pairs)."""
    from paytwin_sim.generator import generate, to_webhook_payloads

    res = generate("mgro", hours=max(2, n // 25), seed=99)
    out = to_webhook_payloads(res.events)
    return out[: max(2, n)]


async def webhook_flood(base: str, secret: str, events: list[dict],
                        concurrency: int = 20) -> dict:
    codes: dict[int, int] = {}
    latencies: list[float] = []
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)

    async def fire(client: httpx.AsyncClient, payload: dict):
        body = json.dumps(payload).encode()
        headers = {"X-PayTwin-Signature": sign(secret, body),
                   "Content-Type": "application/json"}
        async with sem:
            t0 = time.perf_counter()
            r = await client.post(
                f"{base}/webhooks/simulator?merchant=mer1",
                content=body, headers=headers)
            dt = time.perf_counter() - t0
        async with lock:
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
            latencies.append(dt * 1000)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport,
                                 base_url=base) as client:
        t0 = time.perf_counter()
        await asyncio.gather(*[fire(client, p) for p in events])
        wall = time.perf_counter() - t0
    return {"events": len(events), "wall_s": round(wall, 2),
            "events_per_s": round(len(events) / wall, 1),
            "codes": codes,
            "p50_ms": round(percentile(latencies, 50), 1),
            "p95_ms": round(percentile(latencies, 95), 1),
            "p99_ms": round(percentile(latencies, 99), 1)}


async def api_latency(base: str, key: str, requests: int,
                      path: str, concurrency: int = 10) -> dict:
    latencies: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {key}"}

    async def hit(client: httpx.AsyncClient):
        nonlocal errors
        async with sem:
            t0 = time.perf_counter()
            r = await client.get(path, headers=headers)
            dt = time.perf_counter() - t0
            if r.status_code != 200:
                errors += 1
            latencies.append(dt * 1000)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport,
                                 base_url=base) as client:
        t0 = time.perf_counter()
        await asyncio.gather(*[hit(client) for _ in range(requests)])
        wall = time.perf_counter() - t0
    return {"path": path, "requests": requests, "errors": errors,
            "rps": round(requests / wall, 1),
            "p50_ms": round(percentile(latencies, 50), 1),
            "p95_ms": round(percentile(latencies, 95), 1),
            "p99_ms": round(percentile(latencies, 99), 1)}


def _app():
    from paytwin_api.main import app

    return app


def ensure_key(db) -> str:
    from paytwin_api.auth import new_api_key

    raw, row = new_api_key("org1", "risk_admin", user_id="loadtest")
    from paytwin_api.models import ApiKey

    if db.query(ApiKey).filter_by(key_hash=row.key_hash).one_or_none() is None:
        db.add(row)
        db.commit()
        return raw
    # deterministic re-derivation for an existing row is not possible (hashed);
    # mint another key — fine for a load test
    raw2, row2 = new_api_key("org1", "risk_admin", user_id=f"load{time.time()}")
    db.add(row2)
    db.commit()
    return raw2


def _seed_if_empty(db) -> None:
    from datetime import datetime, timedelta, timezone

    from paytwin_api.models import Merchant, Organization, Payment

    now = datetime.now(timezone.utc)
    if db.query(Organization).filter_by(id="org1").one_or_none() is None:
        db.add(Organization(id="org1", name="Nova Commerce"))
    if db.query(Merchant).filter_by(id="mer1").one_or_none() is None:
        db.add(Merchant(id="mer1", organization_id="org1",
                        name="Nova Grocery", short_code="NG",
                        autonomy_mode=4,
                        config={"policy_rules": {}, "world_id": "mgro"}))
    if db.query(Payment).count() < 100:
        for i in range(300):
            db.add(Payment(organization_id="org1", merchant_id="mer1",
                           group_id=f"g{i}", provider="simulator",
                           payment_ref=f"p{i}", amount_paise=84_000,
                           status="success" if i % 7 else "failed",
                           method="upi_intent", issuer="HDFC",
                           psp="cashfree",
                           occurred_at=now - timedelta(minutes=i % 120)))
    db.commit()


async def main_async(args) -> None:
    os.environ.setdefault("PAYTWIN_DATABASE_URL",
                          "sqlite:///./data/loadtest.db")
    from paytwin_api.config import get_settings
    from paytwin_api.db import Base, make_engine, make_session_factory

    import paytwin_api.models  # noqa: F401

    engine = make_engine(os.environ["PAYTWIN_DATABASE_URL"])
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()
    _seed_if_empty(db)
    key = ensure_key(db)
    secret = get_settings().webhook_secret_simulator

    print(f"== webhook flood ({args.events} events) ==")
    flood = await webhook_flood(args.url, secret, build_events(args.events))
    for k, v in flood.items():
        print(f"  {k}: {v}")

    print(f"== API latency ({args.requests} req each) ==")
    for path in ("/api/health", "/api/overview"):
        r = await api_latency(args.url, key, args.requests, path=path)
        print(f"  {r['path']}: p50={r['p50_ms']}ms p95={r['p95_ms']}ms "
              f"p99={r['p99_ms']}ms rps={r['rps']} errors={r['errors']}")
    print("(ASGI in-process; add network + server overhead for prod sizing)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://testserver",
                    help="informational base URL — traffic runs in-process over ASGI")
    ap.add_argument("--events", type=int, default=400)
    ap.add_argument("--requests", type=int, default=150)
    args = ap.parse_args()
    asyncio.run(main_async(args))

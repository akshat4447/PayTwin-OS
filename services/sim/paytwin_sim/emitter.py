"""Webhook emitter: signs payloads with the simulator secret and posts to the API.

Also supports in-process injection (tests/demo without HTTP).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

import httpx

from paytwin_sim.generator import SimEvent, to_webhook_payloads


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class EmitReport:
    sent: int = 0
    ok: int = 0
    duplicate: int = 0
    rejected: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def emit(base_url: str, merchant_id: str, events: list[SimEvent], secret: str,
         timeout: float = 10.0) -> EmitReport:
    rep = EmitReport()
    url = f"{base_url.rstrip('/')}/webhooks/simulator"
    with httpx.Client(timeout=timeout) as client:
        for payload in to_webhook_payloads(events):
            rep.sent += 1
            body = json.dumps(payload).encode()
            try:
                r = client.post(url, params={"merchant": merchant_id}, content=body,
                                headers={"X-PayTwin-Signature": sign(body, secret),
                                         "Content-Type": "application/json"})
                if r.status_code == 200 and r.json().get("duplicate"):
                    rep.duplicate += 1
                elif r.status_code == 200:
                    rep.ok += 1
                else:
                    rep.rejected += 1
                    rep.errors.append(f"{r.status_code}: {r.text[:120]}")
            except httpx.HTTPError as e:
                rep.rejected += 1
                rep.errors.append(str(e)[:120])
                if len(rep.errors) > 20:
                    break
    return rep

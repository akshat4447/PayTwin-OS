"""EXEC-001: idempotent, policy-gated, audited action execution.

Flow: request → idempotency check → policy evaluate →
  BLOCK    → execution REJECTED_BY_POLICY + audited (no provider call)
  APPROVAL → execution VALIDATED, waits for approve_and_execute
  ALLOW    → connector dispatch (capability-checked) → SUCCEEDED/FAILED + outcome
Duplicate request with same idempotency key ⇒ the SAME execution returned; the provider
is called exactly once (tested).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.connectors import get_connector
from paytwin_api.connectors.base import WebhookRejected
from paytwin_api.connectors.execution import execute_action
from paytwin_api.models import ActionCandidate, ActionExecution, Merchant, PolicyDecision
from paytwin_api.services import audit as audit_svc
from paytwin_api.services.policy import PolicyContext, PolicyResult, evaluate, merge_rules


def _next_human_id(db: Session) -> str:
    n = db.query(func.count(ActionExecution.id)).scalar() or 0
    return f"ACT-{5000 + n + 1}"


def idempotency_key(merchant_id: str, kind: str, params: dict, incident_id: str | None) -> str:
    payload = json.dumps({"m": merchant_id, "k": kind, "p": params, "i": incident_id},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:40]


def request_execution(db: Session, principal, merchant: Merchant, candidate: ActionCandidate,
                      actor: str = "system", approved_by: str | None = None
                      ) -> tuple[ActionExecution, PolicyResult | None]:
    key = idempotency_key(merchant.id, candidate.kind, candidate.params, candidate.incident_id)
    existing = (db.query(ActionExecution)
                .filter(ActionExecution.idempotency_key == key).one_or_none())
    if existing is not None:
        return existing, None  # idempotent replay — no second business action

    rules = merge_rules((merchant.config or {}).get("policy_rules"))
    ctx = PolicyContext(
        merchant_id=merchant.id,
        autonomy_mode=merchant.autonomy_mode,
        action_kind=candidate.kind,
        amount_paise=int(candidate.params.get("amount_cap_paise",
                                             candidate.value_paise or 0)),
        attempts_used=int(candidate.params.get("attempts_used", 1)),
        contacts_24h=int(candidate.params.get("contacts_24h", 0)),
        minutes_since_last_action=float(candidate.params.get("minutes_since_last_action", 9999)),
        provider_healthy=bool(candidate.params.get("provider_healthy", True)),
        consent_on_file=bool(candidate.params.get("consent_on_file", True)),
        within_mandate_window=bool(candidate.params.get("within_mandate_window", True)),
        agent_authority_verified=bool(candidate.params.get("agent_authority_verified", True)),
    )
    result: PolicyResult = evaluate(rules, ctx)

    ex = ActionExecution(
        organization_id=merchant.organization_id, merchant_id=merchant.id,
        incident_id=candidate.incident_id, candidate_id=candidate.id,
        human_id=_next_human_id(db), kind=candidate.kind, params=candidate.params,
        idempotency_key=key, state="CREATED",
        connector=(merchant.config or {}).get("connector", "simulator"),
    )
    db.add(ex)
    db.flush()

    dec = PolicyDecision(organization_id=merchant.organization_id, merchant_id=merchant.id,
                         action_execution_id=ex.id, policy_version=result.rules_version,
                         decision=result.decision, failed_rules=result.failed_rules,
                         context=result.checks)
    db.add(dec)

    if result.decision == "block":
        ex.state = "REJECTED_BY_POLICY"
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="policy-engine",
            action_type="action.blocked", object_type="action_execution", object_id=ex.human_id,
            summary=(f"{candidate.kind} blocked: "
                     f"{result.failed_rules[0] if result.failed_rules else 'policy'}"),
            details={"failed_rules": result.failed_rules, "candidate": candidate.id,
                     "kind": candidate.kind},
            incident_id=candidate.incident_id, policy_version=result.rules_version)
        db.flush()
        return ex, result

    if result.decision == "require_approval" and not approved_by:
        ex.state = "VALIDATED"
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="policy-engine",
            action_type="action.approval_required", object_type="action_execution",
            object_id=ex.human_id,
            summary=f"{candidate.kind} needs approval (mode {merchant.autonomy_mode})",
            details={"checks": result.checks}, incident_id=candidate.incident_id,
            policy_version=result.rules_version)
        db.flush()
        return ex, result

    ex.approved_by = approved_by or actor
    _dispatch(db, ex, merchant, actor)
    return ex, result


# __PART2__


def approve_and_execute(db: Session, principal, execution_id: str, actor: str) -> ActionExecution:
    ex = db.query(ActionExecution).filter(ActionExecution.id == execution_id).one_or_none()
    if ex is None or ex.state not in ("VALIDATED", "APPROVED"):
        raise ValueError(f"execution {execution_id} not awaiting approval")
    merchant = db.query(Merchant).filter(Merchant.id == ex.merchant_id).one()
    ex.approved_by = actor
    _dispatch(db, ex, merchant, actor)
    return ex


def _dispatch(db: Session, ex: ActionExecution, merchant: Merchant, actor: str) -> None:
    ex.state = "EXECUTING"
    db.flush()
    connector = get_connector(ex.connector)
    try:
        outcome = execute_action(connector, ex.kind, ex.params, ex.idempotency_key,
                                 get_settings().secret_key)
        ex.state = "SUCCEEDED"
        ex.outcome = outcome
        ex.connector_ref = outcome.get("ref")
        ex.executed_at = datetime.now(timezone.utc)
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="executor",
            action_type="action.executed", object_type="action_execution",
            object_id=ex.human_id, summary=f"{ex.kind} executed via {ex.connector}",
            details={"outcome": outcome}, incident_id=ex.incident_id)
    except WebhookRejected as e:
        ex.state = "FAILED_FINAL"
        ex.outcome = {"error": str(e)}
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="executor",
            action_type="action.failed", object_type="action_execution",
            object_id=ex.human_id, summary=f"{ex.kind} failed: {e}",
            details={"error": str(e)}, incident_id=ex.incident_id)
    db.flush()


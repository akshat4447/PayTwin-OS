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
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.connectors import get_connector
from paytwin_api.connectors.base import WebhookRejected
from paytwin_api.connectors.execution import RetryableActionError, execute_action
from paytwin_api.models import (ActionCandidate, ActionExecution, Integration,
                                Merchant, PolicyDecision)
from paytwin_api.services import audit as audit_svc
from paytwin_api.services.policy import (PolicyContext, PolicyResult, active_rules,
                                         evaluate)


_CONTACT_ACTIONS = {"payment_link", "notify_customer", "calendar_shift"}
_MANDATE_ACTIONS = {"calendar_shift"}


def _evidence(candidate: ActionCandidate) -> dict:
    """Evidence is server-produced; absence remains unknown rather than safe."""
    value = (candidate.params or {}).get("evidence")
    return value if isinstance(value, dict) else {}


def _bool_evidence(evidence: dict, key: str) -> bool:
    return evidence.get(key) is True


def _policy_evaluation_time(evidence: dict) -> datetime | None:
    """Allow a fixed clock only for an explicitly marked local Test Mode run.

    Production policy checks always use the current clock.  A local recovery
    fixture has no real recipient, so making its virtual test clock explicit
    keeps the batch reproducible without weakening the production guard.
    """
    if get_settings().is_prod or evidence.get("local_test_mode") is not True:
        return None
    value = evidence.get("policy_evaluated_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return _aware(parsed)
    except ValueError:
        return None


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

    # Versioned Policy rows are the SOLE enforcement source; merchant.config
    # ["policy_rules"] is only a legacy fallback inside active_rules().
    rules, policy_label = active_rules(db, merchant.organization_id, merchant)
    evidence = _evidence(candidate)
    ctx = PolicyContext(
        merchant_id=merchant.id,
        autonomy_mode=merchant.autonomy_mode,
        action_kind=candidate.kind,
        # Policy sees the monetary exposure of the slice actually being executed
        # (canary rollout), falling back to legacy fields for hand-built candidates.
        amount_paise=int(candidate.params.get(
            "slice_value_paise",
            candidate.params.get("amount_cap_paise", candidate.value_paise or 0))),
        attempts_used=int(candidate.params.get("attempts_used", 1)),
        contacts_24h=int(evidence.get("contacts_24h", 0)),
        minutes_since_last_action=float(evidence.get("minutes_since_last_action", 0)),
        provider_healthy=_bool_evidence(evidence, "provider_healthy"),
        consent_on_file=_bool_evidence(evidence, "consent_on_file"),
        within_mandate_window=_bool_evidence(evidence, "within_mandate_window"),
        agent_authority_verified=_bool_evidence(evidence, "agent_authority_verified"),
        now=_policy_evaluation_time(evidence) or datetime.now(timezone.utc),
    )
    result: PolicyResult = evaluate(rules, ctx, version_label=policy_label)

    ex = ActionExecution(
        organization_id=merchant.organization_id, merchant_id=merchant.id,
        incident_id=candidate.incident_id, candidate_id=candidate.id,
        human_id=_next_human_id(db), kind=candidate.kind,
        params={**candidate.params, "evidence_snapshot": evidence},
        idempotency_key=key, state="CREATED",
        connector=(merchant.config or {}).get("connector", "simulator"),
    )
    try:
        with db.begin_nested():  # savepoint: a concurrent duplicate only rolls this back
            db.add(ex)
            db.flush()
    except IntegrityError:
        existing = (db.query(ActionExecution)
                    .filter(ActionExecution.idempotency_key == key).one_or_none())
        if existing is not None:
            return existing, None  # lost the race: same execution, no second action
        raise

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


def _resolve_connector_secret(db: Session, ex: ActionExecution, merchant: Merchant) -> str:
    """Per-merchant connector secret via the Integration registry (env indirection).

    secret_ref names an ENVIRONMENT VARIABLE — raw secrets are never stored in the
    DB. The simulator (deterministic sandbox) uses the dev webhook secret.
    """
    if ex.connector == "simulator":
        return get_settings().webhook_secret_simulator
    integ = (db.query(Integration)
             .filter(Integration.merchant_id == merchant.id,
                     Integration.provider == ex.connector).one_or_none())
    ref = (integ.secret_ref if integ else None) or f"PAYTWIN_{ex.connector.upper()}_SECRET"
    import os

    sec = os.environ.get(ref, "")
    if not sec:
        raise WebhookRejected(f"no secret configured for {ex.connector} (env {ref})")
    return sec


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _append_stop(ex: ActionExecution, reason: str, *, automatic: bool) -> None:
    outcome = dict(ex.outcome or {})
    stops = list(outcome.get("stopping_events") or [])
    stops.append({"reason": reason, "automatic": automatic,
                  "at": datetime.now(timezone.utc).isoformat()})
    outcome["stopping_events"] = stops
    outcome["stop_reason"] = reason
    ex.outcome = outcome


def _dispatch_local_payment_links(db: Session, ex: ActionExecution,
                                  merchant: Merchant, actor: str) -> None:
    """Execute only the local Test Mode action Razorpay can prove without keys.

    Routing and direct-retry controls remain recommendations in this credentials-
    free environment. Payment Links are different: their complete lifecycle can
    be issued, settled and audited locally with Razorpay-shaped callbacks.
    """
    if ex.kind != "payment_link":
        raise WebhookRejected(
            "local Razorpay Test Mode can execute payment_link recovery only; "
            "routing and direct retry remain policy recommendations")
    failure_mode = str(ex.params.get("failure_mode") or "")
    if failure_mode in {"timeout", "rate_limit", "provider_5xx"}:
        label = {"timeout": "provider timeout", "rate_limit": "provider 429",
                 "provider_5xx": "provider 5xx"}[failure_mode]
        raise RetryableActionError(label)
    from paytwin_api.services.razorpay_local import create_payment_link

    groups = list(dict.fromkeys(ex.params.get("treatment_group_ids") or []))
    if not groups:
        groups = [f"{ex.human_id}-group-{i + 1}" for i in range(
            max(1, min(int(ex.params.get("count", 1)), 100)))]
    amount = int(ex.params.get("avg_amount_paise") or 0)
    if amount < 100:
        raise WebhookRejected("payment_link recovery needs an eligible amount of at least 100 paise")
    max_campaign_value = int((ex.params.get("stopping_rules") or {}).get(
        "max_campaign_value_paise", amount * len(groups)))
    if amount * len(groups) > max_campaign_value:
        raise WebhookRejected("payment-link campaign exceeds its policy-bounded value cap")
    refs: list[str] = []
    for index, group_id in enumerate(groups, start=1):
        created = create_payment_link(
            db, organization_id=merchant.organization_id, merchant_id=merchant.id,
            amount_paise=amount, reference_id=f"{ex.human_id}-{index}",
            payment_group_id=str(group_id), action_execution_id=ex.id,
            channel=str(ex.params.get("channel") or "whatsapp"),
            reminder_enabled=False,
            expires_after_min=int((ex.params.get("stopping_rules") or {})
                                  .get("max_duration_min", 30)),
        )
        refs.append(created.link.link_ref)
    ex.state = "MONITORING"
    ex.executed_at = datetime.now(timezone.utc)
    ex.connector_ref = f"local-payment-link-batch:{ex.human_id}"
    ex.outcome = {
        "provenance": "LOCAL_RAZORPAY_TEST",
        "attempted": len(groups), "recovered": 0, "recovered_paise": 0,
        "treatment_groups": groups, "payment_link_refs": refs,
        "gross_action_cost_paise": int(ex.params.get("outreach_cost_paise", 35)) * len(groups),
        "state": "monitoring_provider_outcomes", "stopping_events": [],
    }
    if failure_mode == "partial_success":
        ex.outcome["partial_success"] = True
        ex.outcome["failure_class"] = "partial_success"
    audit_svc.append_audit(
        db, merchant.organization_id, actor=actor, actor_role="executor",
        action_type="action.canary_started", object_type="action_execution",
        object_id=ex.human_id,
        summary=f"bounded Payment Link recovery started for {len(groups)} treatment groups",
        details={"payment_link_refs": refs, "connector": "razorpay_local",
                 "provenance": "LOCAL_RAZORPAY_TEST"}, incident_id=ex.incident_id)


def _dispatch(db: Session, ex: ActionExecution, merchant: Merchant, actor: str) -> None:
    # Real-PSP execution stays demo/sandbox-only until a provider integration is
    # certified end-to-end (secret handling, reconciliation, rollback evidence).
    if ex.connector == "razorpay" and not get_settings().is_prod \
            and not get_settings().allow_real_execution:
        try:
            _dispatch_local_payment_links(db, ex, merchant, actor)
        except RetryableActionError as e:
            retry_after = max(0, int(ex.params.get("retry_after_sec", 30)))
            ex.state = "FAILED_RETRYABLE"
            ex.outcome = {"error": str(e), "failure_class": str(ex.params.get("failure_mode")),
                          "retry_count": int((ex.outcome or {}).get("retry_count", 0)) + 1,
                          "next_retry_at": (datetime.now(timezone.utc)
                                            + timedelta(seconds=retry_after)).isoformat(),
                          "stopping_events": [], "provenance": "LOCAL_RAZORPAY_TEST"}
            audit_svc.append_audit(
                db, merchant.organization_id, actor=actor, actor_role="executor",
                action_type="action.retry_scheduled", object_type="action_execution",
                object_id=ex.human_id, summary=f"{ex.kind} retry scheduled after {e}",
                details={"retry_after_sec": retry_after, "failure": str(e),
                         "connector": "razorpay_local"}, incident_id=ex.incident_id)
        except WebhookRejected as e:
            ex.state = "FAILED_FINAL"
            ex.outcome = {"error": str(e), "provenance": "LOCAL_RAZORPAY_TEST"}
            audit_svc.append_audit(
                db, merchant.organization_id, actor=actor, actor_role="executor",
                action_type="action.failed", object_type="action_execution",
                object_id=ex.human_id, summary=f"{ex.kind} refused: {e}",
                details={"connector": "razorpay_local", "error": str(e)},
                incident_id=ex.incident_id)
        db.flush()
        return
    if ex.connector != "simulator" and not get_settings().allow_real_execution:
        ex.state = "FAILED_FINAL"
        ex.outcome = {"error": ("real-PSP execution is disabled (sandbox-only build); "
                                "set PAYTWIN_ALLOW_REAL_EXECUTION=1 in a sandbox to enable")}
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="executor",
            action_type="action.failed", object_type="action_execution",
            object_id=ex.human_id, summary=f"{ex.kind} refused: real PSP execution disabled",
            details={"connector": ex.connector, "reason": "sandbox_only"},
            incident_id=ex.incident_id)
        db.flush()
        return
    ex.state = "EXECUTING"
    db.flush()
    connector = get_connector(ex.connector)
    try:
        outcome = execute_action(connector, ex.kind, ex.params, ex.idempotency_key,
                                 _resolve_connector_secret(db, ex, merchant))
        ex.state = "MONITORING" if outcome.get("partial_success") else "SUCCEEDED"
        ex.outcome = outcome
        ex.connector_ref = outcome.get("ref")
        ex.executed_at = datetime.now(timezone.utc)
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="executor",
            action_type=("action.monitoring" if ex.state == "MONITORING" else "action.executed"),
            object_type="action_execution",
            object_id=ex.human_id, summary=f"{ex.kind} executed via {ex.connector}",
            details={"outcome": outcome}, incident_id=ex.incident_id)
    except RetryableActionError as e:
        retry_after = max(0, int(ex.params.get("retry_after_sec", 30)))
        ex.state = "FAILED_RETRYABLE"
        ex.outcome = {"error": str(e), "failure_class": str(ex.params.get("failure_mode")),
                      "retry_count": int((ex.outcome or {}).get("retry_count", 0)) + 1,
                      "next_retry_at": (datetime.now(timezone.utc)
                                        + timedelta(seconds=retry_after)).isoformat(),
                      "stopping_events": []}
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="executor",
            action_type="action.retry_scheduled", object_type="action_execution",
            object_id=ex.human_id, summary=f"{ex.kind} retry scheduled after {e}",
            details={"retry_after_sec": retry_after, "failure": str(e)},
            incident_id=ex.incident_id)
    except WebhookRejected as e:
        ex.state = "FAILED_FINAL"
        ex.outcome = {"error": str(e)}
        audit_svc.append_audit(
            db, merchant.organization_id, actor=actor, actor_role="executor",
            action_type="action.failed", object_type="action_execution",
            object_id=ex.human_id, summary=f"{ex.kind} failed: {e}",
            details={"error": str(e)}, incident_id=ex.incident_id)
    db.flush()


def monitor_execution(db: Session, ex: ActionExecution, actor: str = "runtime-control") -> str:
    """Apply active stopping rules and settle a local recovery campaign.

    This method is worker-safe and idempotent. It never creates money movement;
    it only stops/cancels outstanding local links or promotes already observed
    provider outcomes into the action ledger.
    """
    if ex.state not in {"MONITORING", "EXECUTING", "SCHEDULED", "FAILED_RETRYABLE"}:
        return ex.state
    rules = (ex.params or {}).get("stopping_rules") or {}
    max_duration = int(rules.get("max_duration_min", 30))
    elapsed = datetime.now(timezone.utc) - _aware(ex.created_at)
    if elapsed > timedelta(minutes=max_duration):
        return halt_execution(db, ex, reason="max_duration_exceeded", actor=actor,
                              automatic=True).state
    if ex.state == "FAILED_RETRYABLE":
        retry_at = (ex.outcome or {}).get("next_retry_at")
        if retry_at and datetime.fromisoformat(retry_at) <= datetime.now(timezone.utc):
            retry_limit = int(rules.get("max_provider_retries", 2))
            if int((ex.outcome or {}).get("retry_count", 0)) >= retry_limit:
                ex.state = "FAILED_FINAL"
                _append_stop(ex, "provider_retry_budget_exhausted", automatic=True)
                audit_svc.append_audit(
                    db, ex.organization_id, actor=actor, actor_role="runtime-control",
                    action_type="action.stopped", object_type="action_execution",
                    object_id=ex.human_id, summary="provider retry budget exhausted",
                    details={"execution_id": ex.id}, incident_id=ex.incident_id)
                db.flush()
                return ex.state
            ex.params = {**ex.params, "failure_mode": ""}
            merchant = db.query(Merchant).filter(Merchant.id == ex.merchant_id).one()
            _dispatch(db, ex, merchant, actor)
        return ex.state
    if (ex.outcome or {}).get("partial_success") and \
            bool(rules.get("rollback_on_partial_success", True)):
        return halt_execution(db, ex, reason="partial_provider_success", actor=actor,
                              automatic=True, rollback=True).state
    if ex.connector == "razorpay":
        from paytwin_api.models import PaymentLink

        links = (db.query(PaymentLink)
                 .filter(PaymentLink.action_execution_id == ex.id).all())
        if links and not any(link.status in {"issued", "partially_paid"} for link in links):
            paid = [link for link in links if link.status == "paid"]
            outcome = dict(ex.outcome or {})
            outcome.update({"recovered": len(paid),
                            "recovered_paise": sum(link.amount_paid_paise for link in paid),
                            "terminal_links": len(links), "state": "completed"})
            ex.outcome = outcome
            ex.state = "SUCCEEDED"
            audit_svc.append_audit(
                db, ex.organization_id, actor=actor, actor_role="runtime-control",
                action_type="action.completed", object_type="action_execution",
                object_id=ex.human_id,
                summary=f"Payment Link batch settled: {len(paid)}/{len(links)} recovered",
                details={"recovered_paise": outcome["recovered_paise"],
                         "terminal_links": len(links)}, incident_id=ex.incident_id)
    db.flush()
    return ex.state


def halt_execution(db: Session, ex: ActionExecution, *, reason: str, actor: str,
                   automatic: bool = False, rollback: bool = False) -> ActionExecution:
    """Stop an active execution and cancel every still-open local recovery link."""
    if ex.state in {"SUCCEEDED", "FAILED_FINAL", "REJECTED_BY_POLICY", "ROLLED_BACK", "HALTED"}:
        return ex
    cancelled = 0
    if ex.connector == "razorpay":
        from paytwin_api.services.razorpay_local import cancel_open_payment_links

        cancelled = cancel_open_payment_links(db, action_execution_id=ex.id, reason=reason)
    ex.state = "ROLLED_BACK" if rollback else "HALTED"
    _append_stop(ex, reason, automatic=automatic)
    audit_svc.append_audit(
        db, ex.organization_id, actor=actor,
        actor_role="runtime-control" if automatic else "human-operator",
        action_type="action.rolled_back" if rollback else "action.halted",
        object_type="action_execution", object_id=ex.human_id,
        summary=f"{ex.kind} {'rolled back' if rollback else 'halted'}: {reason}",
        details={"reason": reason, "cancelled_payment_links": cancelled,
                 "automatic": automatic}, incident_id=ex.incident_id)
    db.flush()
    return ex


def monitor_open_executions(db: Session, organization_id: str | None = None) -> dict:
    """Worker entry point for automatic stop, retry and rollback evaluation."""
    q = db.query(ActionExecution).filter(ActionExecution.state.in_(
        ("MONITORING", "EXECUTING", "SCHEDULED", "FAILED_RETRYABLE")))
    if organization_id:
        q = q.filter(ActionExecution.organization_id == organization_id)
    rows = q.order_by(ActionExecution.created_at.asc()).limit(500).all()
    states = [monitor_execution(db, row) for row in rows]
    return {"examined": len(rows), "states": states}

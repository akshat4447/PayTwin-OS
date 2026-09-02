"""AGENT-001 commander: grounded conversational agent over tenant-scoped tools.

Safety contract:
- Read-only tools; the ONLY money-adjacent path is drafting a typed request and
  running it through the POLICY ENGINE for evaluation. The commander never calls
  the executor - no customer/payment action is ever executed from chat.
- Deterministic composer (template + citations); works with PAYTWIN_LLM_PROVIDER=none.
- Every claim carries an evidence id [E#]; every id resolves to a real object.
- Tool traces are persisted to the hash-chained audit log (actor_role="agent").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.models import (
    ActionCandidate,
    ActionExecution,
    AuditRecord,
    Experiment,
    Incident,
    Payment,
    PolicyDecision,
    RootCauseCandidate,
    Simulation,
)
from paytwin_api.services import audit as audit_svc
from paytwin_api.services.experiments import results as experiment_results
from paytwin_api.services.policy import PolicyContext, active_rules, evaluate, merge_rules

_REFUSALS = [
    (r"ignore (all |any |your )?(previous|prior|above) instructions", "instruction override"),
    (r"(disable|bypass|turn off|skip).{0,20}(policy|policies|guardrail)", "policy tamper"),
    (r"(delete|wipe|erase|tamper).{0,15}(audit|logs?)", "audit tamper"),
    (r"drop\s+table|delete\s+from\s+\w+|update\s+\w+\s+set", "sql tamper"),
    (r"(reveal|give me|show me|print).{0,20}(api[- ]?key|secret|credential)", "secret exfil"),
    (r"refund (everyone|all customers|every)", "mass money movement"),
    (r"(pretend|you are now|act as).{0,30}(admin|root|unrestricted|god)", "role spoof"),
    (r"execute.{0,25}(without|no) (approval|policy|check)", "governance bypass"),
]
_ACTIONS = [
    (r"retry (all|every|the)", "retry_burst"),
    (r"reroute", "reroute_psp"),
    (r"payment links?", "payment_links"),
    (r"notify (all |the )?(customers?|users?)", "notify_customer"),
    (r"(execute|run|trigger).{0,30}(recovery|candidate|action|playbook)", "retry_burst"),
]


@dataclass
class EvidencePack:
    items: list[dict] = field(default_factory=list)

    def add(self, kind: str, ref: str, summary: str) -> str:
        self.items.append({"id": f"E{len(self.items) + 1}", "kind": kind,
                           "ref": ref, "summary": summary})
        return self.items[-1]["id"]


@dataclass
class CommanderReply:
    intent: str
    reply: str
    citations: list[str]
    evidence: list[dict]
    tool_trace: list[str]
    composed_by: str


def classify_intent(text: str) -> dict:
    low = text.lower()
    for pat, reason in _REFUSALS:
        if re.search(pat, low):
            return {"kind": "refuse", "reason": reason}
    for pat, kind in _ACTIONS:
        if re.search(pat, low):
            m = re.search(r"INC-\d+", text.upper())
            return {"kind": "action", "action_kind": kind,
                    "target": m.group(0) if m else None}
    if re.search(r"\b(how much|money recovered|recovered|recovery value|net incremental)\b", low):
        return {"kind": "recovery_proof"}
    if re.search(r"\binc-\d+", low):
        return {"kind": "incident_status"}
    if re.search(r"\b(why|explain|rca|root cause|decision)\b", low):
        return {"kind": "explain"}
    if re.search(r"\b(twin|simulat)", low):
        return {"kind": "twin"}
    if re.search(r"\b(experiment|a/b|lift)\b", low):
        return {"kind": "experiment"}
    if re.search(r"\b(audit|trail|who did)", low):
        return {"kind": "audit"}
    return {"kind": "metrics"}


def tool_query_metrics(db: Session, org_id: str, pack: EvidencePack) -> str:
    rows = db.query(Payment).filter(Payment.organization_id == org_id).all()
    total = len(rows)
    fails = sum(1 for r in rows if r.status in ("failed", "timeout"))
    sr = 1 - fails / total if total else 1.0
    eid = pack.add("metric", f"metrics.{org_id}",
                   f"{total} payments on record, SR {sr:.1%} ({fails} failed)")
    return (f"On record: {total} payments, success rate {sr:.1%} ({fails} failed). "
            f"[{eid}]")


def tool_get_incident(db: Session, org_id: str, ref: str | None,
                      pack: EvidencePack) -> str:
    q = db.query(Incident).filter(Incident.organization_id == org_id)
    inc = q.filter(Incident.human_id == ref.upper()).one_or_none() if ref else None
    if ref and inc is None:
        eid = pack.add("incident", ref.upper(), "incident is not in this organization")
        return f"No incident {ref.upper()} is available in this organization. [{eid}]"
    if inc is None:
        inc = (db.query(Incident)
               .filter(Incident.organization_id == org_id,
                       Incident.state.notin_(("RESOLVED", "POSTMORTEM")))
               .order_by(Incident.detected_at.desc()).first())
    if inc is None:
        eid = pack.add("incident", "none", "no incidents found")
        return f"No incidents on record for this organization. [{eid}]"
    label = " x ".join(f"{k}={v}" for k, v in inc.cohort().items() if v)
    e1 = pack.add("incident", inc.human_id,
                  f"{inc.human_id} {label} [{inc.state}] SR "
                  f"{inc.current_sr_bp / 100:.1f}% vs {inc.baseline_sr_bp / 100:.1f}%"
                  f", RaR Rs{inc.rar_paise / 100:,.0f}, affected {inc.affected_payments}")
    parts = [f"{inc.human_id}: {inc.title} [{inc.state}] [{e1}]"]
    rca = (db.query(RootCauseCandidate)
           .filter(RootCauseCandidate.incident_id == inc.id)
           .order_by(RootCauseCandidate.rank).first())
    if rca is not None:
        edge = " x ".join(f"{k}={v}" for k, v in {
            "issuer": rca.edge_issuer, "method": rca.edge_method,
            "psp": rca.edge_psp}.items() if v)
        e2 = pack.add("rca", f"rca.{inc.human_id}",
                      f"top cause {edge}, score {rca.score:.2f}, counterfactual share "
                      f"{rca.counterfactual_share:.0%}")
        parts.append(f"Top root cause: {edge} (confidence {rca.score:.2f}) [{e2}]")
    cand = (db.query(ActionCandidate).filter(ActionCandidate.incident_id == inc.id)
            .order_by(ActionCandidate.rank).first())
    if cand is not None:
        e3 = pack.add("candidate", cand.id, f"{cand.label}, EV Rs{cand.ev_paise / 100}")
        parts.append(f"Best candidate: {cand.label} "
                     f"(EV Rs{cand.ev_paise / 100:,.0f}) [{e3}]")
    return " ".join(parts)


def tool_get_twin(db: Session, org_id: str, pack: EvidencePack) -> str:
    sims = (db.query(Simulation).filter(Simulation.organization_id == org_id)
            .order_by(Simulation.created_at.desc()).limit(3).all())
    if not sims:
        eid = pack.add("simulation", "none", "no twin simulations stored")
        return f"No twin simulations stored yet. [{eid}]"
    parts = []
    for s in sims:
        r = s.result or {}
        eid = pack.add("simulation", s.id,
                       f"{s.scenario} p50 Rs{r.get('p50_paise', 0) / 100:,.0f}, "
                       f"seed {s.seed}, {s.trials} trials")
        parts.append(f"{s.scenario}: p50 Rs{r.get('p50_paise', 0) / 100:,.0f} "
                     f"(seed {s.seed}, reproducible) [{eid}]")
    return "Twin simulations: " + "; ".join(parts) + "."


def tool_get_experiment(db: Session, org_id: str, pack: EvidencePack) -> str:
    exp = (db.query(Experiment).filter(Experiment.organization_id == org_id)
           .order_by(Experiment.started_at.desc()).first())
    if exp is None:
        eid = pack.add("experiment", "none", "no experiments yet")
        return f"No experiments yet. [{eid}]"
    r = experiment_results(db, exp)
    eid = pack.add("experiment", exp.id,
                   f"'{exp.name}' treatment n={r['n']['treatment']}, lift "
                   f"{r.get('lift_abs', 0):+.1%}")
    return (f"Experiment '{exp.name}': treatment recovery "
            f"{r['recovery_rate']['treatment']:.1%} vs control "
            f"{r['recovery_rate']['control']:.1%}, lift {r.get('lift_abs', 0):+.1%} "
            f"(95% CI {r.get('ci95', [0, 0])}). [{eid}]")


def _rupees(paise: int | float) -> str:
    return f"₹{int(round(paise)) / 100:,.0f}"


def tool_get_recovery_proof(db: Session, org_id: str, pack: EvidencePack,
                            incident_ref: str | None = None) -> str:
    """Return the causal money proof, never a payment-count proxy.

    The treatment arm is compared with a counterfactual control expectation
    scaled to treatment eligibility.  This keeps a Commander answer aligned
    with the downloadable recovery-batch report.
    """
    query = db.query(Experiment).filter(Experiment.organization_id == org_id)
    if incident_ref:
        incident = (db.query(Incident)
                    .filter(Incident.organization_id == org_id,
                            Incident.human_id == incident_ref.upper()).one_or_none())
        if incident is not None:
            query = query.filter(Experiment.incident_id == incident.id)
    exp = query.order_by(Experiment.started_at.desc()).first()
    if exp is None:
        eid = pack.add("experiment", incident_ref or "none", "no measured recovery batch")
        return ("No measured recovery batch is available for this incident yet; "
                "PayTwin will not claim recovered money from a forecast. "
                f"[{eid}]")
    r = experiment_results(db, exp)
    n = r["n"]
    ci = r.get("net_incremental_ci95_paise", [0, 0])
    audit_refs = ", ".join(r.get("audit_refs") or []) or "none"
    stops = "; ".join(r.get("stopping_events") or []) or "none recorded"
    eid = pack.add(
        "recovery_batch", exp.id,
        f"{exp.name}: net incremental {_rupees(r['net_incremental_paise'])}; "
        f"treatment n={n['treatment']}, control n={n['control']}; "
        f"95% interval {_rupees(ci[0])}–{_rupees(ci[1])}; audit {audit_refs}",
    )
    return (
        f"Measured recovery for '{exp.name}': gross treatment recovery "
        f"{_rupees(r['gross_recovered_paise'])}, matched-control expectation "
        f"{_rupees(r['control_expected_paise'])}, intervention cost "
        f"{_rupees(r['intervention_cost_paise'])}, and net incremental GMV "
        f"{_rupees(r['net_incremental_paise'])}. The 95% interval is "
        f"{_rupees(ci[0])}–{_rupees(ci[1])} across treatment n={n['treatment']} "
        f"and control n={n['control']}. Stopping events: {stops}. "
        f"Audit references: {audit_refs}. [{eid}]"
    )


def tool_explain_decision(db: Session, org_id: str, human_or_id: str | None,
                          pack: EvidencePack) -> str:
    q = db.query(ActionExecution).filter(ActionExecution.organization_id == org_id)
    ex = (q.filter(ActionExecution.human_id == human_or_id.upper()).one_or_none()
          if human_or_id else q.order_by(ActionExecution.created_at.desc()).first())
    if ex is None:
        eid = pack.add("decision", "none", "no action executions recorded")
        return f"No action executions recorded. [{eid}]"
    dec = (db.query(PolicyDecision)
           .filter(PolicyDecision.action_execution_id == ex.id)
           .order_by(PolicyDecision.created_at.desc()).first())
    failed = dec.failed_rules if dec is not None else []
    eid = pack.add("decision", ex.human_id or ex.id,
                   f"{ex.kind} state {ex.state}, policy said "
                   f"{dec.decision if dec else '?'}, failed rules: {failed}")
    why = f" Failed rules: {'; '.join(failed)}." if failed else ""
    return (f"{ex.human_id or ex.id} ({ex.kind}) is {ex.state}; the policy engine "
            f"said '{dec.decision if dec else 'unknown'}'.{why} [{eid}]")


def tool_get_audit(db: Session, org_id: str, pack: EvidencePack, limit: int = 8) -> str:
    rows = (db.query(AuditRecord).filter(AuditRecord.organization_id == org_id)
            .order_by(AuditRecord.seq.desc()).limit(limit).all())
    if not rows:
        eid = pack.add("audit", "empty", "audit log empty")
        return f"Audit log is empty. [{eid}]"
    parts = []
    for r in rows:
        eid = pack.add("audit", str(r.seq), f"{r.action_type}: {r.summary[:80]}")
        parts.append(f"#{r.seq} {r.action_type} by {r.actor} [{eid}]")
    return "Recent audit entries: " + "; ".join(parts) + "."


def _merchant(db: Session, org_id: str, merchant_id: str | None = None):
    from paytwin_api.models import Merchant

    query = db.query(Merchant).filter(Merchant.organization_id == org_id)
    if merchant_id:
        return query.filter(Merchant.id == merchant_id).one_or_none()
    return query.order_by(Merchant.created_at.asc()).first()


def candidate_amount(cand) -> int:
    return int(cand.params.get("slice_value_paise",
                               cand.params.get("amount_cap_paise",
                                               cand.value_paise or 0)))


def _draft_and_evaluate(db: Session, org_id: str, intent: dict,
                        pack: EvidencePack) -> tuple[str, dict]:
    """Draft a typed action request and run POLICY EVALUATION only.

    The commander never dispatches: whatever the verdict is, nothing executes.
    """
    q = (db.query(Incident)
         .filter(Incident.organization_id == org_id,
                 Incident.state.notin_(("RESOLVED",))))
    if intent.get("target"):
        q = q.filter(Incident.human_id == intent["target"])
    inc = q.order_by(Incident.detected_at.desc()).first()
    cq = (db.query(ActionCandidate).filter_by(incident_id=inc.id)
          .order_by(ActionCandidate.rank)) if inc is not None else None
    cand = None
    if cq is not None:
        # the classified action kind selects which candidate to draft from;
        # fall back to best-EV when no candidate matches that kind
        cand = (cq.filter(ActionCandidate.kind == intent["action_kind"]).first()
                if intent.get("action_kind") else None) or cq.first()
    if cand is None or inc is None:
        eid = pack.add("candidate", "none", "no candidate for a typed request")
        return ("I could not find an incident with a ranked candidate to build a "
                f"request from. [{eid}]\n"
                "No customer or payment action was executed.", {"decision": "none"})
    merchant = _merchant(db, org_id, inc.merchant_id)
    if merchant is None:
        eid = pack.add("merchant", inc.merchant_id, "incident merchant is unavailable")
        return (f"The incident merchant is unavailable; no request was drafted. [{eid}]",
                {"decision": "none"})
    rules, _policy_label = active_rules(db, org_id, merchant)
    ctx = PolicyContext(
        merchant_id=merchant.id, autonomy_mode=merchant.autonomy_mode,
        action_kind=cand.kind, amount_paise=candidate_amount(cand),
        attempts_used=int(cand.params.get("attempts_used", 1)),
        contacts_24h=int(cand.params.get("contacts_24h", 0)),
        minutes_since_last_action=float(
            cand.params.get("minutes_since_last_action", 9999)),
    )
    result = evaluate(rules, ctx)
    failed = result.failed_rules
    e_dec = pack.add("policy", f"draft.{cand.id}",
                     f"draft {cand.kind}: {result.decision}, failed rules: {failed}")
    lines = [f"Drafted a typed '{cand.kind}' request against {inc.human_id} "
             f"and evaluated it against the live policy set."]
    if result.decision == "allow":
        lines.append("Verdict: ALLOWED by policy - it would proceed to the "
                     "executor's idempotent flow only if submitted from the "
                     "war room.")
    elif result.decision == "require_approval":
        lines.append("Verdict: REQUIRE_APPROVAL - a human must approve before "
                     "anything runs.")
    else:
        lines.append("Verdict: BLOCKED."
                     + (f" Failed rules: {'; '.join(failed)}." if failed else ""))
        lines.append("I will not attempt workarounds; the policy engine is final.")
    lines.append("No customer or payment action was executed.")
    lines.append(f"[{e_dec}]")
    return "\n".join(lines), {"decision": result.decision,
                              "failed_rules": failed, "kind": cand.kind}


def _requested_incident(text: str, incident_id: str | None) -> str | None:
    explicit = re.search(r"\bINC-\d+", text.upper())
    if explicit:
        return explicit.group(0)
    requested = (incident_id or "").strip().upper()
    return requested if re.fullmatch(r"INC-\d+", requested) else None


def handle_message(db: Session, principal, text: str, *,
                   incident_id: str | None = None, scope: str | None = None) -> dict:
    """Entry point: classify, run read-only tools (or policy evaluation), compose."""
    org_id = principal.organization_id
    pack = EvidencePack()
    trace: list[str] = []
    intent = classify_intent(text)
    selected_incident = _requested_incident(text, incident_id)

    if intent["kind"] == "refuse":
        out = {"intent": "refuse",
               "reply": ("I can't help with that (" + intent["reason"] + "). "
                         "PayTwin agents are read-only over tenant data; money-"
                         "moving actions only ever go through the deterministic "
                         "policy engine and executor."),
               "citations": [], "evidence": [], "tool_trace": ["refused"],
               "composed_by": _composed_by()}
    else:
        kind = intent["kind"]
        if kind == "metrics":
            trace.append("query_metrics")
            reply = tool_query_metrics(db, org_id, pack)
        elif kind == "incident_status":
            trace.append("get_incident")
            reply = tool_get_incident(db, org_id, selected_incident, pack)
        elif kind == "explain":
            trace.append("get_incident")
            reply = tool_get_incident(db, org_id, selected_incident, pack)
            m = re.search(r"\bACT-\d+", text.upper())
            if m or re.search(r"\b(decision|why)\b", text.lower()):
                trace.append("explain_decision")
                reply += "\n" + tool_explain_decision(
                    db, org_id, m.group(0) if m else None, pack)
        elif kind == "twin":
            trace.append("get_twin")
            reply = tool_get_twin(db, org_id, pack)
        elif kind == "experiment":
            trace.append("get_experiment")
            reply = tool_get_experiment(db, org_id, pack)
        elif kind == "recovery_proof":
            trace.append("get_recovery_proof")
            reply = tool_get_recovery_proof(db, org_id, pack, selected_incident)
        elif kind == "audit":
            trace.append("get_audit")
            reply = tool_get_audit(db, org_id, pack)
        else:
            trace += ["get_incident", "evaluate_policy"]
            if selected_incident:
                intent["target"] = selected_incident
            reply, _policy_meta = _draft_and_evaluate(db, org_id, intent, pack)
        out = {"intent": ("action_policy" if kind == "action"
                          else {"metrics": "metrics",
                                "incident_status": "incident_status",
                                "explain": "explain", "twin": "twin",
                                "experiment": "experiment",
                                "recovery_proof": "recovery_proof",
                                "audit": "audit"}[kind]),
               "reply": reply, "citations": [e["id"] for e in pack.items],
               "evidence": pack.items, "tool_trace": trace,
               "composed_by": _composed_by()}
    audit_svc.append_audit(
        db, org_id, actor="commander", actor_role="agent",
        action_type="commander.query", object_type="conversation",
        object_id=re.sub(r"\s+", " ", text)[:40],
        summary=f"intent={out['intent']} tools={','.join(out['tool_trace'])}",
        details={"tool_trace": out["tool_trace"], "citations": out["citations"],
                 "evidence": out["evidence"], "selected_incident": selected_incident,
                 "scope": scope})
    return out


def _composed_by() -> str:
    provider = get_settings().llm_provider
    return "deterministic" if provider == "none" else f"deterministic+{provider}"

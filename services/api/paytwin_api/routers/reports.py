"""Reports: recovery-batch markdown download (measured numbers only)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, get_db
from paytwin_api.models import ActionExecution
from paytwin_api.services.experiments import results as experiment_results
from paytwin_api.models import Experiment

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/recovery-batch")
def recovery_batch(p: Principal = Depends(current_principal),
                   db: Session = Depends(get_db), hours: int = 24,
                   scope: str | None = None):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (db.query(ActionExecution)
         .filter(ActionExecution.organization_id == p.organization_id,
                 ActionExecution.created_at >= since))
    if scope and scope != "org":
        q = q.filter(ActionExecution.merchant_id == scope)
    execs = q.order_by(ActionExecution.created_at).all()
    lines = [f"# Recovery batch report — last {hours}h",
             f"_organization: {p.organization_id} · generated "
             f"{datetime.now(timezone.utc).isoformat()}_", ""]
    succeeded = [e for e in execs if e.state == "SUCCEEDED"]
    recovered_paise = sum((e.outcome or {}).get("recovered_paise", 0)
                          for e in succeeded)
    attempted = sum((e.outcome or {}).get("attempted", 0) for e in succeeded)
    recovered_n = sum((e.outcome or {}).get("recovered", 0) for e in succeeded)
    stopping_events = [event for execution in execs
                       for event in list((execution.outcome or {}).get("stopping_events") or [])]
    lines += ["## Executions", "",
              f"- total requests: {len(execs)}",
              f"- succeeded: {len(succeeded)}",
              f"- blocked by policy: "
              f"{sum(1 for e in execs if e.state == 'REJECTED_BY_POLICY')}",
              f"- awaiting approval: "
              f"{sum(1 for e in execs if e.state == 'VALIDATED')}",
              "", "## Measured recovery", "",
              f"- payments attempted: {attempted}",
              f"- payments recovered: {recovered_n}",
              f"- gross action outcome: Rs {recovered_paise / 100:,.0f}",
              f"- stopping events: {len(stopping_events)}", ""]
    exps = (db.query(Experiment)
            .filter(Experiment.organization_id == p.organization_id,
                    Experiment.started_at >= since - timedelta(days=7)).all())
    lines += ["## Incremental recovery (treatment vs matched control)", ""]
    totals = {"gross": 0, "cost": 0, "net": 0, "control": 0, "treatment": 0}
    for e in exps:
        r = experiment_results(db, e)
        sig = "significant" if r.get("significant") else "not significant"
        n = r["n"]
        ci = r["net_incremental_ci95_paise"]
        totals["gross"] += r["incremental_gross_paise"]
        totals["cost"] += r["intervention_cost_paise"]
        totals["net"] += r["net_incremental_paise"]
        totals["control"] += n["control"]
        totals["treatment"] += n["treatment"]
        lines += [f"### {e.name}",
                  f"- sample: {n['treatment']} treatment / {n['control']} control",
                  f"- recovery rate: treatment {r['recovery_rate']['treatment']:.1%}"
                  f" vs control {r['recovery_rate']['control']:.1%}; lift "
                  f"{r.get('lift_abs', 0):+.1%} ({sig})",
                  f"- gross recovered in treatment: Rs {r['gross_recovered_paise'] / 100:,.0f}",
                  f"- control-expected recovery: Rs {r['control_expected_paise'] / 100:,.0f}",
                  f"- incremental recovered GMV: Rs {r['incremental_gross_paise'] / 100:,.0f}",
                  f"- intervention cost: Rs {r['intervention_cost_paise'] / 100:,.0f}",
                  f"- **net incremental GMV: Rs {r['net_incremental_paise'] / 100:,.0f}** "
                  f"(95% interval Rs {ci[0] / 100:,.0f} – Rs {ci[1] / 100:,.0f})",
                  f"- audit references: {', '.join(r['audit_refs']) or 'none'}",
                  f"- stopping events: {len(r['stopping_events'])}", ""]
    if not exps:
        lines.append("- none in window")
    else:
        lines += ["## Batch total", "",
                  f"- sample: {totals['treatment']} treatment / {totals['control']} control",
                  f"- incremental recovered GMV: Rs {totals['gross'] / 100:,.0f}",
                  f"- intervention cost: Rs {totals['cost'] / 100:,.0f}",
                  f"- **net incremental GMV: Rs {totals['net'] / 100:,.0f}**", "",
                  "## Provenance", "",
                  "- Local Test Mode: outcomes originate from signed Razorpay-shaped "
                  "webhook lifecycles in this workspace; no provider account or real "
                  "money movement is claimed."]
    return Response(content="\n".join(lines) + "\n", media_type="text/markdown",
                    headers={"Content-Disposition":
                             'attachment; filename="recovery-batch.md"'})

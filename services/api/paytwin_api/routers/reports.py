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
              f"- recovered value: Rs {recovered_paise / 100:,.0f}", ""]
    exps = (db.query(Experiment)
            .filter(Experiment.organization_id == p.organization_id,
                    Experiment.started_at >= since - timedelta(days=7)).all())
    lines += ["## Experiments (control vs treatment)", ""]
    for e in exps:
        r = experiment_results(db, e)
        sig = "significant" if r.get("significant") else "not significant"
        lines.append(f"- **{e.name}**: treatment {r['recovery_rate']['treatment']:.1%}"
                     f" vs control {r['recovery_rate']['control']:.1%}, lift "
                     f"{r.get('lift_abs', 0):+.1%} ({sig})")
    if not exps:
        lines.append("- none in window")
    return Response(content="\n".join(lines) + "\n", media_type="text/markdown",
                    headers={"Content-Disposition":
                             'attachment; filename="recovery-batch.md"'})
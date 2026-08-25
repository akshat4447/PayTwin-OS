"""Incident engine (PHASE 12): correlate detector alerts → incidents → RCA → candidates.

One underlying outage ⇒ ONE incident. Lifecycle: DETECTED → TRIAGING → DIAGNOSED →
ACTION_PROPOSED → (execution path) → MONITORING → RESOLVED.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import product

from sqlalchemy.orm import Session

from paytwin_ml.detectors import detect
from paytwin_ml.features import baseline_sr, cohort_series
from paytwin_ml.rca import rank_root_causes
from paytwin_ml.rar import revenue_at_risk
from paytwin_api.models import (
    ActionCandidate,
    Incident,
    IncidentEvidence,
    Merchant,
    Payment,
    RootCauseCandidate,
)
from paytwin_api.services import audit as audit_svc
from paytwin_api.services.optimizer import ActionOption, rank_options

ISSUERS = ("HDFC", "ICICI", "SBI", "AXIS", "KOTAK")
METHODS = ("upi_intent", "upi_collect", "card", "netbanking", "mandate")
PSPS = ("cashfree", "razorpay", "payu")

# Severity-gate tuning (calibrated on seed-42 outage vs clean sweeps, see tests):
SEVERITY_GUARD_MIN = 10   # minutes before firing excluded from the baseline region
SEVERITY_ALPHA = 0.01     # per-cohort binomial-tail threshold (~40 cohorts watched)
SEVERITY_MIN_EXCESS = 3   # business floor: extra failures beyond expectation
SEVERITY_MIN_DROP = 0.03  # business floor: window SR at least this far below baseline
SEVERITY_MIN_N = 10       # verdict needs traffic


def _watch_cohorts() -> list[dict]:
    out = [{"issuer": i, "method": m} for i, m in product(ISSUERS, METHODS)]
    out += [{"psp": p} for p in PSPS]
    out += [{"method": m} for m in METHODS]
    out += [{"issuer": i} for i in ISSUERS]
    return out


def _aware_utc(dt: datetime) -> datetime:
    """DB timestamps may come back naive (SQLite); they are UTC by convention."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _payments_dicts(db: Session, merchant_id: str, hours: float = 3.0) -> tuple[list[dict], int]:
    """Payment dicts + sweep-window start (epoch sec) for detection.

    Time handling: rows are read WITHOUT a wall-clock predicate and normalized to
    aware-UTC here — SQLite returns naive values and .timestamp() would otherwise
    interpret them as LOCAL time (breaks any non-UTC host). The window is anchored
    on the DATA (latest event), not on now-hours: live traffic anchors at ~now while
    backfilled/simulated history aligns exactly wherever it sits in time.
    Scale note: replace full scan with rollup read-model when volume warrants it.
    """
    rows = (db.query(Payment)
            .filter(Payment.merchant_id == merchant_id)
            .order_by(Payment.occurred_at.asc())
            .all())
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    if not rows:
        return [], now_epoch
    epochs = [_aware_utc(r.occurred_at).timestamp() for r in rows]
    # Anchor on the newest event: identical alignment for live traffic (~now) and
    # replayed/simulated history (which may sit entirely in past or future).
    t0 = int(max(epochs)) - int(hours * 3600)
    pays = [{"epoch": int(e), "failed": r.status in ("failed", "timeout"),
             "method": r.method, "issuer": r.issuer, "psp": r.psp, "gateway": r.gateway,
             "amount": r.amount_paise, "ref": r.payment_ref, "group_id": r.group_id}
            for r, e in zip(rows, epochs) if e >= t0]
    return pays, t0


def _next_human_id(db: Session, organization_id: str) -> str:
    n = db.query(Incident).filter_by(organization_id=organization_id).count()
    return f"INC-{2480 + n + 1}"


# __PART2__


def _binom_sf(k: int, n: int, p: float) -> float:
    """Exact binomial survival function P(X >= k), X~Bin(n, p). Stdlib only."""
    from math import comb

    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    q = 1.0 - p
    total = sum(comb(n, i) * (p ** i) * (q ** (n - i)) for i in range(k, n + 1))
    return min(1.0, max(0.0, total))


def _related(d1: dict, d2: dict) -> bool:
    """Hierarchical relation: compatible when every key BOTH specify agrees.

    An unspecified key is a wildcard, so {issuer:HDFC} IS related to
    {issuer:HDFC, method:upi_intent} but not to {issuer:SBI, ...}.
    """
    for k in set(d1) | set(d2):
        v1, v2 = d1.get(k), d2.get(k)
        if v1 is not None and v2 is not None and v1 != v2:
            return False
    return True


def run_detection_cycle(db: Session, organization_id: str) -> list[Incident]:
    """One sweep: detect per cohort, correlate to a single incident per merchant.

    Anti-noise rules (multiple testing across ~40 cohorts):
    1. Family corroboration — a candidate needs ≥1 OTHER firing whose dims are
       hierarchically consistent (wildcards allowed) AND whose [first, first+20min]
       detection window overlaps the candidate's (real outages light up related
       cohorts together; scattered noise firings do not).
    2. Severity on a bounded 20-min window vs a guard-banded pre-onset baseline of
       the cohort itself (capped at 99.5%): exact binomial tail p < 0.01 AND
       excess ≥3 failures AND window SR ≥3pts below baseline AND ≥10 attempts.
    3. Revenue-weighted selection: family with max excess wins; most-specific dims
       inside the family become the incident cohort.
    """
    opened: list[Incident] = []
    merchants = db.query(Merchant).filter_by(organization_id=organization_id).all()
    for m in merchants:
        pays, t0 = _payments_dicts(db, m.id)
        if len(pays) < 60:
            continue
        firings: list[tuple[dict, object]] = []
        for dims in _watch_cohorts():
            s = cohort_series(pays, dims, t0, t0 + 180 * 60)
            if s.attempts.sum() < 40:
                continue
            d = detect(s, baseline_minutes=45, bucket_min=5, k_consecutive=2)
            if d.fired:
                firings.append((dims, d))
        if not firings:
            continue

        data_end = max((p["epoch"] for p in pays), default=t0)

        def severity(dims: dict, det):
            """Business impact + statistical surprise on a 20-min window.

            Baseline = the cohort's own SR over [t0, firing−guard) (guard band keeps
            onset ramp out of the baseline), capped at 99.5% so sparse "perfect"
            histories cannot manufacture infinite surprise; falls back to the
            detector baseline when the region is too thin. Admission combines an
            exact binomial tail (multiple-testing aware across ~40 watched cohorts)
            with business floors (excess failures, SR drop).
            """
            f = det.first_minute or 0
            win_start = t0 + f * 60
            win = (win_start, min(data_end, win_start + 20 * 60))
            base_cut = t0 + max(0, f - SEVERITY_GUARD_MIN) * 60
            pre = [p for p in pays if t0 <= p["epoch"] < base_cut]
            bsr = det.baseline_sr if len(pre) < 30 else baseline_sr(
                cohort_series(pre, dims, t0, base_cut), min_attempts=1)
            bsr = min(bsr, 0.995)
            coh = [p for p in pays if win[0] <= p["epoch"] < win[1]
                   and all(p.get(k) == v for k, v in dims.items() if v)]
            if len(coh) < SEVERITY_MIN_N:
                return None, f"tiny n={len(coh)}"
            fails = sum(1 for p in coh if p["failed"])
            excess = fails - int(round(len(coh) * (1 - bsr)))
            wsr = 1 - fails / len(coh)
            p_tail = _binom_sf(fails, len(coh), 1 - bsr)
            return (excess, wsr, (win, bsr), p_tail), "ok"

        # candidates with corroboration + severity, ranked by excess (revenue-weighted)
        candidates = []
        for dims, det in firings:
            f1 = (det.first_minute or 0) * 60
            w1 = (f1, f1 + 20 * 60)
            fam = [(d2, dt2) for d2, dt2 in firings
                   if (d2, dt2) != (dims, det) and _related(dims, d2)
                   and min(w1[1], (dt2.first_minute or 0) * 60 + 20 * 60)
                   > max(w1[0], (dt2.first_minute or 0) * 60)]  # window overlap
            if not fam:
                continue
            sev, _why = severity(dims, det)
            if sev is None:
                continue
            excess, wsr, meta, p_tail = sev
            if (excess >= SEVERITY_MIN_EXCESS and wsr < meta[1] - SEVERITY_MIN_DROP
                    and p_tail < SEVERITY_ALPHA):
                candidates.append((excess, len(dims), dims, det, meta))
        if not candidates:
            continue
        # Two-stage selection: max excess anchors the winning family, then the
        # MOST-SPECIFIC corroborated member becomes the incident cohort (an
        # aggregate inherits the outage's excess plus sibling noise, so raw excess
        # alone would mis-target e.g. all-of-HDFC instead of HDFC×upi_intent).
        candidates.sort(key=lambda c: (-c[0], -c[1]))
        top = candidates[0]
        tf = (top[3].first_minute or 0) * 60

        def _overlaps(c) -> bool:
            cf = (c[3].first_minute or 0) * 60
            return min(tf + 20 * 60, cf + 20 * 60) > max(tf, cf)

        family = [c for c in candidates if c is not top and _related(c[2], top[2])
                  and _overlaps(c)]
        chosen = max([top] + family, key=lambda c: (len(c[2]), c[0]))
        excess, _, dims, det, (win, bsr) = chosen
        inc = _open_incident(db, m, dims, det, pays, t0,
                             firing_count=len(firings), window=win, bsr=bsr)
        if inc:
            opened.append(inc)
    return opened


def _open_incident(db: Session, m: Merchant, dims: dict, det, pays: list[dict],
                   t0: int, firing_count: int, window: tuple[int, int],
                   bsr: float) -> Incident | None:
    recent_cut = datetime.now(timezone.utc) - timedelta(minutes=30)
    existing = (db.query(Incident)
                .filter(Incident.merchant_id == m.id,
                        Incident.state.notin_(("RESOLVED", "POSTMORTEM")),
                        Incident.detected_at >= recent_cut)
                .one_or_none())
    if existing:
        return None  # one outage ⇒ one incident

    rar = revenue_at_risk(pays, window, dims, bsr)
    wsr = rar.window_sr
    sev = "P1" if (rar.expected_paise > 2_000_00 and wsr < bsr - 0.05) else "P2"
    label = " × ".join(f"{k}={v}" for k, v in dims.items())

    inc = Incident(
        organization_id=m.organization_id, merchant_id=m.id,
        human_id=_next_human_id(db, m.organization_id),
        sev=sev, title=f"{label} degradation", state="TRIAGING",
        cohort_issuer=dims.get("issuer"), cohort_method=dims.get("method"),
        cohort_psp=dims.get("psp"), cohort_gateway=dims.get("gateway"),
        baseline_sr_bp=int(bsr * 10000), current_sr_bp=int(wsr * 10000),
        rar_paise=rar.expected_paise, rar_lo_paise=rar.lo_paise, rar_hi_paise=rar.hi_paise,
        affected_payments=rar.affected, confidence=det.score,
    )
    db.add(inc)
    db.flush()

    def ev(kind, ref, summary, weight=1.0):
        db.add(IncidentEvidence(incident_id=inc.id, kind=kind, ref=ref, summary=summary,
                                weight=weight))

    ev("detector", f"det.{inc.human_id}",
       f"Ensemble fired at +{det.first_minute or 0}m: votes={det.votes}, "
       f"SR {det.window_sr:.1%} vs baseline {det.baseline_sr:.1%} "
       f"({firing_count} correlated cohort alerts)", 2.0)
    ev("metric", f"metric.{label}", f"Cohort SR {wsr:.1%} vs {bsr:.1%} baseline")
    ev("metric", f"metric.rar.{inc.human_id}",
       f"Revenue at risk ₹{rar.expected_paise / 100:,.0f} "
       f"[₹{rar.lo_paise / 100:,.0f} – ₹{rar.hi_paise / 100:,.0f}]", 1.5)

    cands = rank_root_causes(pays, window, baseline_sr=bsr, top_k=3)
    for c in cands:
        db.add(RootCauseCandidate(incident_id=inc.id, edge_issuer=c.edge.get("issuer"),
                                  edge_method=c.edge.get("method"), edge_psp=c.edge.get("psp"),
                                  score=c.score, rank=c.rank,
                                  counterfactual_share=c.counterfactual_share))
    if cands:
        top = cands[0]
        inc.state = "DIAGNOSED"
        inc.confidence = max(inc.confidence, top.score)
        ev("rca", f"rca.{inc.human_id}",
           "Top cause: " + " × ".join(f"{k}={v}" for k, v in top.edge.items())
           + f" (confidence {top.score:.2f}, counterfactual removes "
             f"{top.counterfactual_share:.0%} of excess failures)", 2.0)

    failed = [p for p in pays if window[0] <= p["epoch"] < window[1]
              and p["failed"] and all(p.get(k) == v for k, v in dims.items() if v)]
    _propose_candidates(db, inc, m, failed)
    db.flush()
    audit_svc.append_audit(db, m.organization_id, actor="detector", actor_role="system",
                           action_type="incident.opened", object_type="incident",
                           object_id=inc.human_id, summary=inc.title,
                           details={"sev": sev, "rar_paise": rar.expected_paise,
                                    "cohort": dims}, incident_id=inc.id)
    return inc


# __PART3__


def _propose_candidates(db: Session, inc: Incident, m: Merchant, failed: list[dict]) -> None:
    from paytwin_ml.twin import run_twin

    industry = (m.config or {}).get("industry", "grocery")
    fp = [{"amount": p["amount"], "age_min": 5.0} for p in failed[:200]]
    total_value = sum(p["amount"] for p in fp)
    avg_amt = int(total_value / max(1, len(failed))) if failed else 0
    # Autopilot executes a bounded CANARY SLICE of the failed cohort, not all of it:
    # the slice's count/value are what the policy engine must judge (its AMOUNT_CAP
    # bounds real per-action exposure, not the whole cohort's GMV).
    alloc_pct = 25
    slice_count = max(1, round(len(fp) * alloc_pct / 100)) if fp else 0
    slice_value = int(total_value * alloc_pct / 100)
    options: list[ActionOption] = []
    for scen in ("retry_burst", "reroute_psp", "payment_links", "notify_customer"):
        twin = run_twin(m.id, industry, fp, scen, seed=42, trials=400,
                        alloc_pct=alloc_pct, duration_min=30)
        p_delta = min(0.45, twin.p50_paise / max(1, total_value) + 0.02)
        options.append(ActionOption(
            kind=scen, label=scen.replace("_", " ").title(),
            detail=(f"twin p50 +₹{twin.p50_paise / 100:,.0f} "
                    f"[₹{twin.lo_paise / 100:,.0f}–₹{twin.hi_paise / 100:,.0f}] "
                    f"cost ₹{twin.cost_paise / 100:,.0f}"),
            params={"count": slice_count, "p_success": 0.4,
                    "avg_amount_paise": avg_amt, "attempts_used": 1,
                    "scenario": scen, "alloc_pct": alloc_pct,
                    "slice_value_paise": slice_value},
            p_succ_delta=max(0.0, p_delta), value_paise=total_value,
            cost_paise=twin.cost_paise, risk_paise=int(twin.cost_paise * 0.2)))
    ranked = rank_options(options)
    for i, o in enumerate(ranked):
        if o.kind == "do_nothing" and i > 0:
            continue
        db.add(ActionCandidate(
            incident_id=inc.id, kind=o.kind, label=o.label, detail=o.detail,
            params=o.params, p_succ_delta=o.p_succ_delta, value_paise=o.value_paise,
            cost_paise=o.cost_paise, risk_paise=o.risk_paise, ev_paise=o.ev_paise,
            rank=i))
    inc.state = "ACTION_PROPOSED"
    db.add(IncidentEvidence(incident_id=inc.id, kind="simulation", ref=f"twin.{inc.human_id}",
                            summary=f"Twin Monte-Carlo (400 trials, seed 42) ranked "
                                    f"{len(options)} interventions; best EV {ranked[0].label}",
                            weight=1.5))


def resolve(db: Session, inc: Incident, actor: str = "system") -> None:
    inc.state = "RESOLVED"
    inc.resolved_at = datetime.now(timezone.utc)
    audit_svc.append_audit(db, inc.organization_id, actor=actor, actor_role="system",
                           action_type="incident.resolved", object_type="incident",
                           object_id=inc.human_id, summary=f"{inc.human_id} resolved",
                           incident_id=inc.id)



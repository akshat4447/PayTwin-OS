"""GOV-001: deterministic policy engine — the LAST WORD on money-moving actions.

The LLM never authorizes anything. Rules are typed, versioned, stored per merchant.
Hard violations ⇒ BLOCK (regardless of autonomy mode). Autonomy ladder gates auto-exec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from paytwin_contracts import ActionKind, AutonomyMode, PolicyDecision, PolicyRuleId

# TRAI quiet hours are defined in IST; evaluate them in IST regardless of host TZ.
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_RULES: dict = {
    PolicyRuleId.MAX_ATTEMPTS.value: 3,
    PolicyRuleId.AMOUNT_CAP.value: 5_000_00,          # ₹5,000 per action
    PolicyRuleId.CONTACT_BUDGET.value: 2,             # customer contacts / 24h
    PolicyRuleId.PROVIDER_HEALTHY.value: True,
    PolicyRuleId.CONSENT_ON_FILE.value: True,
    PolicyRuleId.DND_WINDOW.value: {"start_hour": 21, "end_hour": 9},   # TRAI quiet hours
    PolicyRuleId.WITHIN_MANDATE_WINDOW.value: True,
    PolicyRuleId.COOLDOWN.value: 30,                  # minutes between actions/group
    PolicyRuleId.AGENT_AUTHORITY.value: True,
}

CONTACT_ACTIONS = {ActionKind.PAYMENT_LINK.value, ActionKind.NOTIFY_CUSTOMER.value,
                   ActionKind.CALENDAR_SHIFT.value}
MONEY_ACTIONS = {ActionKind.RETRY_BURST.value, ActionKind.REROUTE_PSP.value,
                 ActionKind.PAYMENT_LINK.value, ActionKind.CALENDAR_SHIFT.value}


@dataclass
class PolicyContext:
    merchant_id: str
    autonomy_mode: int
    action_kind: str
    amount_paise: int = 0
    attempts_used: int = 1
    contacts_24h: int = 0
    minutes_since_last_action: float = 9999.0
    provider_healthy: bool = True
    consent_on_file: bool = True
    within_mandate_window: bool = True
    agent_authority_verified: bool = True
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PolicyResult:
    decision: str                 # PolicyDecision
    failed_rules: list[str]
    checks: dict
    rules_version: str


def merge_rules(merchant_rules: dict | None) -> dict:
    rules = dict(DEFAULT_RULES)
    rules.update(merchant_rules or {})
    return rules


def active_rules(db, org_id: str, merchant) -> tuple[dict, str]:
    """Resolve the EFFECTIVE rule set for a merchant — the single enforcement source.

    Live, latest-version Policy rows are merged in human_id order; unknown/legacy
    keys from merchant.config["policy_rules"] are applied only where no versioned
    policy already speaks. Returns (merged rules incl. defaults, version label)
    where the label names every policy version that contributed (audit trail).
    """
    from paytwin_api.models import Policy

    rows = (db.query(Policy)
            .filter(Policy.organization_id == org_id,
                    Policy.merchant_id == merchant.id,
                    Policy.status == "live")
            .order_by(Policy.human_id, Policy.version.desc()).all())
    latest: dict[str, Policy] = {}
    for r in rows:
        latest.setdefault(r.human_id, r)  # first seen per human_id = highest version
    merged: dict = {}
    labels: list[str] = []
    for hid in sorted(latest):
        row = latest[hid]
        merged.update(row.rules or {})
        labels.append(f"{hid}:v{row.version}")
    for key, value in ((merchant.config or {}).get("policy_rules") or {}).items():
        merged.setdefault(key, value)  # legacy fallback only
    version = "+".join(labels) if labels else "defaults"
    return merge_rules(merged), version


_INT_BOUNDS = {
    "max_attempts": (1, 10),
    "amount_cap": (100, 10_000_000),   # paise: ₹1 .. ₹1,00,000 per action
    "contact_budget_ok": (0, 10),
    "cooldown_ok": (0, 1440),          # minutes
}
_BOOL_RULES = {"provider_healthy", "consent_on_file",
               "within_mandate_window", "agent_authority_verified"}


def validate_rules(rules: dict) -> str | None:
    """Strict typed/range validation for saved policies. Returns error text or None."""
    for key, value in (rules or {}).items():
        if key in _INT_BOUNDS:
            lo, hi = _INT_BOUNDS[key]
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                return (f"{key} must be an integer in [{lo}, {hi}] "
                        f"(got {value!r})")
        elif key in _BOOL_RULES:
            if not isinstance(value, bool):
                return f"{key} must be a boolean (got {value!r})"
        elif key == "dnd_window_ok":
            if not isinstance(value, dict):
                return f"dnd_window_ok must be an object (got {value!r})"
            s, e = value.get("start_hour"), value.get("end_hour")
            for part, h in (("start_hour", s), ("end_hour", e)):
                if isinstance(h, bool) or not isinstance(h, int) or not 0 <= h <= 23:
                    return f"dnd_window_ok.{part} must be an integer 0-23 (got {h!r})"
            if s == e:
                return "dnd_window_ok.start_hour must differ from end_hour"
        else:
            return f"unrecognized rule id: {key}"
    return None


def evaluate(rules: dict, ctx: PolicyContext,
             version_label: str | None = None) -> PolicyResult:
    failed: list[str] = []
    checks: dict = {}

    def hard(rule: str, ok: bool, reason: str):
        checks[rule] = "ok" if ok else "violated"
        if not ok:
            failed.append(f"{rule}: {reason}")

    # ---- hard guardrails (BLOCK on any violation) ----
    max_att = rules.get(PolicyRuleId.MAX_ATTEMPTS.value, 3)
    hard(PolicyRuleId.MAX_ATTEMPTS.value, ctx.attempts_used < max_att,
         f"attempt {ctx.attempts_used}/{max_att} — retry limit reached")

    cap = rules.get(PolicyRuleId.AMOUNT_CAP.value, DEFAULT_RULES[PolicyRuleId.AMOUNT_CAP.value])
    hard(PolicyRuleId.AMOUNT_CAP.value, ctx.amount_paise <= cap,
         f"request ₹{ctx.amount_paise / 100:,.0f}; exceeds the "
         f"₹{cap / 100:,.0f} cap by ₹{(ctx.amount_paise - cap) / 100:,.0f}")

    if rules.get(PolicyRuleId.PROVIDER_HEALTHY.value, True):
        hard(PolicyRuleId.PROVIDER_HEALTHY.value, ctx.provider_healthy,
             "connector circuit-breaker open")
    # Consent and contact-budget checks are relevant to customer outreach,
    # not to a purely internal routing action. Their evidence remains
    # fail-closed whenever the action can contact a customer.
    if ctx.action_kind in CONTACT_ACTIONS and rules.get(PolicyRuleId.CONSENT_ON_FILE.value, True):
        hard(PolicyRuleId.CONSENT_ON_FILE.value, ctx.consent_on_file,
             "no DPDP consent on file")
    if ctx.action_kind == ActionKind.CALENDAR_SHIFT.value \
            and rules.get(PolicyRuleId.WITHIN_MANDATE_WINDOW.value, True):
        hard(PolicyRuleId.WITHIN_MANDATE_WINDOW.value, ctx.within_mandate_window,
             "outside RBI e-mandate window")
    if rules.get(PolicyRuleId.AGENT_AUTHORITY.value, True) and ctx.action_kind in MONEY_ACTIONS:
        hard(PolicyRuleId.AGENT_AUTHORITY.value, ctx.agent_authority_verified,
             "AP2/UAP agent authority not verified")

    if ctx.action_kind in CONTACT_ACTIONS:
        budget = rules.get(PolicyRuleId.CONTACT_BUDGET.value, 2)
        hard(PolicyRuleId.CONTACT_BUDGET.value, ctx.contacts_24h < budget,
             f"{ctx.contacts_24h}/{budget} contacts in 24h — anti-harassment cap")
        dnd = rules.get(PolicyRuleId.DND_WINDOW.value) or {}
        naive = ctx.now.tzinfo is None
        h = (ctx.now.replace(tzinfo=IST) if naive else ctx.now.astimezone(IST)).hour
        s, e = dnd.get("start_hour", 21), dnd.get("end_hour", 9)
        in_dnd = (h >= s or h < e) if s > e else (s <= h < e)
        hard(PolicyRuleId.DND_WINDOW.value, not in_dnd,
             f"TRAI quiet hours {s:02d}:00–{e:02d}:00 IST")

    cooldown = rules.get(PolicyRuleId.COOLDOWN.value, 30)
    hard(PolicyRuleId.COOLDOWN.value,
         ctx.minutes_since_last_action >= cooldown,
         f"last action {ctx.minutes_since_last_action:.0f}m ago < {cooldown}m cooldown")

    if failed:
        base = version_label or "rules"
        return PolicyResult(PolicyDecision.BLOCK, failed, checks,
                            f"{base}@{len(rules)}-hard")

    # ---- autonomy ladder (only healthy candidates reach here) ----
    mode = int(ctx.autonomy_mode)
    if ctx.action_kind not in MONEY_ACTIONS:
        decision = PolicyDecision.ALLOW          # read-only/notify-style ops
    elif mode >= AutonomyMode.AUTONOMOUS:
        decision = PolicyDecision.ALLOW
    elif mode == AutonomyMode.BOUNDED_AUTOPILOT:
        decision = (PolicyDecision.ALLOW if ctx.amount_paise <= cap / 2
                    else PolicyDecision.REQUIRE_APPROVAL)
    elif mode == AutonomyMode.APPROVE_FIRST:
        decision = PolicyDecision.REQUIRE_APPROVAL
    else:  # OBSERVE / RECOMMEND
        decision = PolicyDecision.REQUIRE_APPROVAL

    base = version_label or "rules"
    return PolicyResult(decision, [], checks, f"{base}@{len(rules)}-mode{mode}")

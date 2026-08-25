"""GOV-001: deterministic policy engine — the LAST WORD on money-moving actions.

The LLM never authorizes anything. Rules are typed, versioned, stored per merchant.
Hard violations ⇒ BLOCK (regardless of autonomy mode). Autonomy ladder gates auto-exec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from paytwin_contracts import ActionKind, AutonomyMode, PolicyDecision, PolicyRuleId

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
    now: datetime = field(default_factory=datetime.utcnow)


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


def evaluate(rules: dict, ctx: PolicyContext) -> PolicyResult:
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
         f"₹{(ctx.amount_paise - cap) / 100:,.0f} over the ₹{cap / 100:,.0f} cap")

    if rules.get(PolicyRuleId.PROVIDER_HEALTHY.value, True):
        hard(PolicyRuleId.PROVIDER_HEALTHY.value, ctx.provider_healthy,
             "connector circuit-breaker open")
    if rules.get(PolicyRuleId.CONSENT_ON_FILE.value, True):
        hard(PolicyRuleId.CONSENT_ON_FILE.value, ctx.consent_on_file,
             "no DPDP consent on file")
    if rules.get(PolicyRuleId.WITHIN_MANDATE_WINDOW.value, True):
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
        h = ctx.now.hour
        s, e = dnd.get("start_hour", 21), dnd.get("end_hour", 9)
        in_dnd = (h >= s or h < e) if s > e else (s <= h < e)
        hard(PolicyRuleId.DND_WINDOW.value, not in_dnd,
             f"TRAI quiet hours {s:02d}:00–{e:02d}:00 IST")

    cooldown = rules.get(PolicyRuleId.COOLDOWN.value, 30)
    hard(PolicyRuleId.COOLDOWN.value,
         ctx.minutes_since_last_action >= cooldown,
         f"last action {ctx.minutes_since_last_action:.0f}m ago < {cooldown}m cooldown")

    if failed:
        return PolicyResult(PolicyDecision.BLOCK, failed, checks,
                            f"rules@{len(rules)}-hard")

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

    return PolicyResult(decision, [], checks, f"rules@{len(rules)}-mode{mode}")

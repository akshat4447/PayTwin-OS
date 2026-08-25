"""DECIDE-001: expected-value optimizer over action candidates.

EV = p_succ_delta × value_at_stake − execution_cost − friction/messaging_cost − risk_cost
argmax(EV) subject to EV ≥ 0, else NO_ACTION. Deterministic and unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActionOption:
    kind: str                 # ActionKind value; "do_nothing" for the null action
    label: str
    detail: str = ""
    params: dict = field(default_factory=dict)
    p_succ_delta: float = 0.0   # incremental success probability (from twin/uplift)
    value_paise: int = 0        # value at stake the delta applies to
    cost_paise: int = 0         # execution + messaging cost
    risk_paise: int = 0         # friction/risk cost
    twin_ref: str | None = None

    @property
    def ev_paise(self) -> int:
        return int(round(self.p_succ_delta * self.value_paise - self.cost_paise - self.risk_paise))


NO_ACTION = ActionOption(kind="do_nothing", label="Do nothing",
                         detail="No intervention beats the expected value of acting")


def rank_options(options: list[ActionOption]) -> list[ActionOption]:
    """All options (incl. NO_ACTION) sorted by EV desc."""
    return sorted([*options, NO_ACTION], key=lambda o: -o.ev_paise)


def select_best(options: list[ActionOption]) -> ActionOption:
    """argmax EV with the NO_ACTION floor: never act at negative expected value."""
    ranked = rank_options(options)
    best = ranked[0]
    return best if best.ev_paise > 0 else NO_ACTION

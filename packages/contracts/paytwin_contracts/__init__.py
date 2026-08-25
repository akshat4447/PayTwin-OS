"""PayTwin canonical contracts. Providers normalize at the edge; core sees only these."""
from paytwin_contracts.enums import (  # noqa: F401
    ActionKind, AutonomyMode, Connector, ExecutionState, ExperimentArm, FailureClass,
    IncidentSev, IncidentState, ModelStage, PaymentStatus, PolicyDecision, EventType,
    PolicyRuleId,
)
from paytwin_contracts.money import compact_inr, format_inr, paise, rupees  # noqa: F401
from paytwin_contracts.events import CANONICAL_SCHEMA_VERSION, CanonicalEvent, cohort_key  # noqa: F401

__version__ = "0.1.0"

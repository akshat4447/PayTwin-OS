from __future__ import annotations

from enum import IntEnum, StrEnum


class EventType(StrEnum):
    PAYMENT_CREATED = "payment.created"
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_SUCCESS = "payment.success"
    PAYMENT_TIMEOUT = "payment.timeout"
    REFUND_CREATED = "refund.created"
    REFUND_FAILED = "refund.failed"
    REFUND_UPDATED = "refund.updated"
    ORDER_PAID = "order.paid"
    CONNECTOR_HEALTH = "connector.health"


class PaymentStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REFUNDED = "refunded"


class FailureClass(StrEnum):
    ISSUER_DECLINE = "issuer_decline"
    TIMEOUT = "timeout"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    PSP_ERROR = "psp_error"
    CHECKOUT_ERROR = "checkout_error"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    NONE = "none"


class IncidentState(StrEnum):
    DETECTED = "DETECTED"
    TRIAGING = "TRIAGING"
    DIAGNOSED = "DIAGNOSED"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    MITIGATING = "MITIGATING"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    POSTMORTEM = "POSTMORTEM"


class IncidentSev(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ActionKind(StrEnum):
    DO_NOTHING = "do_nothing"
    RETRY_BURST = "retry_burst"
    REROUTE_PSP = "reroute_psp"
    PAYMENT_LINK = "payment_link"
    NOTIFY_CUSTOMER = "notify_customer"
    CALENDAR_SHIFT = "calendar_shift"
    ESCALATE = "escalate"


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class ExecutionState(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    REJECTED_BY_POLICY = "REJECTED_BY_POLICY"


class AutonomyMode(IntEnum):
    OBSERVE = 0
    RECOMMEND = 1
    APPROVE_FIRST = 2
    BOUNDED_AUTOPILOT = 3
    AUTONOMOUS = 4


class ExperimentArm(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"


class ModelStage(StrEnum):
    TRAINED = "TRAINED"
    VALIDATED = "VALIDATED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    CHAMPION = "CHAMPION"
    RETIRED = "RETIRED"


class Connector(StrEnum):
    SIMULATOR = "simulator"
    MOCK_PROVIDER = "mockprovider"
    RAZORPAY = "razorpay"


class PolicyRuleId(StrEnum):
    MAX_ATTEMPTS = "max_attempts"
    AMOUNT_CAP = "amount_cap"
    DND_WINDOW = "dnd_window_ok"
    WITHIN_MANDATE_WINDOW = "within_mandate_window"
    CONSENT_ON_FILE = "consent_on_file"
    CONTACT_BUDGET = "contact_budget_ok"
    AGENT_AUTHORITY = "agent_authority_verified"
    PROVIDER_HEALTHY = "provider_healthy"
    COOLDOWN = "cooldown_ok"
    AUTONOMY_GATE = "autonomy_mode_ok"

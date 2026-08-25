"""Contract tests: money helpers + canonical event schema (FOUNDATION-002)."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from paytwin_contracts import (
    CANONICAL_SCHEMA_VERSION,
    ActionKind,
    AutonomyMode,
    CanonicalEvent,
    EventType,
    PolicyRuleId,
    cohort_key,
    compact_inr,
    format_inr,
    paise,
    rupees,
)


def _evt(**over) -> CanonicalEvent:
    base = dict(
        type=EventType.PAYMENT_FAILED.value,
        organization_id="org1",
        merchant_id="mer1",
        provider="simulator",
        external_event_id="evt_123",
        occurred_at=datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
        payment_ref="pay_abc",
        amount_paise=129900,
        cohort={"issuer": "HDFC", "method": "upi_intent", "psp": "cashfree"},
    )
    base.update(over)
    return CanonicalEvent(**base)


class TestMoney:
    def test_paise_roundtrip(self):
        assert paise(1299) == 129900
        assert rupees(129900) == 1299.0
        assert paise(0.01) == 1  # rounding-safe

    def test_money_is_int(self):
        assert isinstance(paise(10.105), int)

    def test_compact_inr_units(self):
        assert compact_inr(100) == "₹1"            # ₹1
        assert compact_inr(100_000) == "₹1K"       # ₹1,000
        assert compact_inr(1_00_000_00) == "₹1L"   # ₹1,00,000
        assert compact_inr(3_20_00_00_000) == "₹3.2Cr"  # ₹3.2 crore
        assert compact_inr(-50_00) == "-₹50"

    def test_format_inr_grouping(self):
        assert format_inr(129900) == "₹1,299"
        assert format_inr(123456700) == "₹12,34,567"


class TestCanonicalEvent:
    def test_valid_parse_and_defaults(self):
        e = _evt()
        assert e.schema_version == CANONICAL_SCHEMA_VERSION == 1
        assert e.currency == "INR"
        assert e.late is False
        assert e.ingested_at.tzinfo is not None

    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError):
            _evt(type="payment.vaporized")

    def test_non_inr_rejected(self):
        with pytest.raises(ValidationError):
            _evt(currency="USD")

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            _evt(pan="1234567812345678")  # sensitive junk must never pass

    def test_naive_datetime_coerced_to_utc(self):
        e = _evt(occurred_at=datetime(2026, 8, 25, 10, 0))
        assert e.occurred_at.tzinfo is not None

    def test_cohort_key_stable_and_normalized(self):
        a = cohort_key({"issuer": "HDFC", "method": "upi_intent", "psp": "cashfree"})
        b = cohort_key({"psp": "cashfree", "issuer": "HDFC", "method": "upi_intent"})
        assert a == b == "HDFC|upi_intent|cashfree|*"
        assert cohort_key(None) == "*|*|*|*"

    def test_negative_amount_rejected(self):
        with pytest.raises(ValidationError):
            _evt(amount_paise=-1)


def test_enums_frozen():
    with pytest.raises(AttributeError):
        ActionKind.RETRY_BURST.value = "x"
    assert AutonomyMode.BOUNDED_AUTOPILOT == 3
    assert {r.value for r in PolicyRuleId} >= {"max_attempts", "dnd_window_ok", "amount_cap"}

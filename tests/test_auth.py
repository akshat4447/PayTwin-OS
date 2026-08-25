"""TENANCY-001: API key issuance, principal resolution, RBAC, revocation."""
from __future__ import annotations

import pytest

from paytwin_api.auth import AuthError, new_api_key, resolve_principal
from paytwin_api.models import Organization


def _seed_org(db):
    db.add(Organization(id="org1", name="Nova Commerce"))
    db.add(Organization(id="org2", name="Other Co"))
    db.commit()


def test_key_roundtrip(db):
    _seed_org(db)
    raw, row = new_api_key("org1", "ops_oncall")
    db.add(row)
    db.commit()
    p = resolve_principal(db, f"Bearer {raw}")
    assert p.organization_id == "org1"
    assert p.role == "ops_oncall"
    assert p.can_write and not p.is_admin


def test_hashed_at_rest(db):
    _seed_org(db)
    raw, row = new_api_key("org1", "org_admin")
    db.add(row)
    db.commit()
    stored = row.key_hash
    assert raw.encode() not in stored.encode()
    assert len(stored) == 64  # sha256 hex


def test_invalid_and_malformed(db):
    _seed_org(db)
    with pytest.raises(AuthError):
        resolve_principal(db, None)
    with pytest.raises(AuthError):
        resolve_principal(db, "Basic abc")
    with pytest.raises(AuthError):
        resolve_principal(db, "Bearer ptw_doesnotexist")


def test_revoked_key_rejected(db):
    _seed_org(db)
    raw, row = new_api_key("org1", "finance_viewer")
    db.add(row)
    db.commit()
    from datetime import datetime, timezone

    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    with pytest.raises(AuthError):
        resolve_principal(db, f"Bearer {raw}")


def test_roles_hierarchy(db):
    _seed_org(db)
    raw_v, row_v = new_api_key("org1", "finance_viewer")
    raw_r, row_r = new_api_key("org1", "risk_admin")
    db.add_all([row_v, row_r])
    db.commit()
    viewer = resolve_principal(db, f"Bearer {raw_v}")
    risk = resolve_principal(db, f"Bearer {raw_r}")
    assert not viewer.can_write and not viewer.is_admin
    assert risk.can_write and risk.is_admin

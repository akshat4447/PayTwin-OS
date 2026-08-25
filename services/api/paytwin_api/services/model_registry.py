"""ML-002 model registry: persist TrainingResult as model_versions rows.

Lifecycle starts at TRAINED; VALIDATED -> CHAMPION transitions happen later via the
API (risk_admin only). paytwin_ml stays import-free of paytwin_api — this shim is
the only place the two meet.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from paytwin_api.models import ModelVersion


def register_training(db: Session, result,
                      params: dict | None = None) -> ModelVersion:
    """Get-or-create the model_versions row for a TrainingResult (idempotent).

    Note: models are shared artifacts — model_versions intentionally carries no
    tenant column; predictions/incidents referencing them are tenant-scoped.
    """
    row = (db.query(ModelVersion)
           .filter(ModelVersion.name == result.name,
                   ModelVersion.version == result.version)
           .one_or_none())
    if row is not None:
        return row
    row = ModelVersion(
        name=result.name, version=result.version, stage="TRAINED",
        kind=result.champion_kind,
        metrics={"champion": result.champion, **result.champion_metrics},
        params={"seed": params.get("seed") if params else None,
                "feature_version": result.feature_version,
                "splits": result.metrics.get("split", {})},
        artifact_path=result.artifact_paths[result.champion],
        feature_version=result.feature_version,
        dataset_fingerprint=result.dataset_fingerprint,
    )
    db.add(row)
    db.flush()
    return row


def champion(db: Session, name: str = "success_prob") -> ModelVersion | None:
    return (db.query(ModelVersion)
            .filter(ModelVersion.name == name)
            .order_by(ModelVersion.stage == "CHAMPION", ModelVersion.trained_at.desc())
            .first())
"""ML-002 model registry: persist and select reproducible runtime models.

Lifecycle starts at TRAINED. A model becomes VALIDATED only when its recorded
offline acceptance gates pass; CHAMPION remains an explicit admin promotion. The
runtime can consume VALIDATED/CHAMPION models, never a merely-trained artifact.
paytwin_ml stays import-free of paytwin_api — this shim is the only place the two
meet.
"""
from __future__ import annotations

from sqlalchemy import case
from sqlalchemy.orm import Session

from paytwin_api.models import ModelVersion


RUNTIME_STAGES = ("VALIDATED", "CHAMPION")


def register_training(db: Session, result, params: dict | None = None,
                      stage: str = "TRAINED") -> ModelVersion:
    """Get-or-create the model_versions row for a TrainingResult (idempotent).

    Note: models are shared artifacts — model_versions intentionally carries no
    tenant column; predictions/incidents referencing them are tenant-scoped.
    """
    if stage not in ("TRAINED", *RUNTIME_STAGES):
        raise ValueError(f"unsupported model stage: {stage}")
    row = (db.query(ModelVersion)
           .filter(ModelVersion.name == result.name,
                   ModelVersion.version == result.version)
           .one_or_none())
    if row is not None:
        # A deterministic demo may be re-run after its holdout gates are added.
        # Allow only the narrow, auditable TRAINED -> VALIDATED transition here;
        # CHAMPION promotion always remains the role-gated API operation.
        if stage == "VALIDATED" and row.stage == "TRAINED":
            row.stage = "VALIDATED"
            row.params = {**(row.params or {}), **(params or {})}
        return row
    row = ModelVersion(
        name=result.name, version=result.version, stage=stage,
        kind=result.champion_kind,
        metrics={"champion": result.champion, **result.champion_metrics},
        params={"seed": params.get("seed") if params else None,
                "feature_version": result.feature_version,
                "splits": result.metrics.get("split", {}),
                **(params or {})},
        artifact_path=result.artifact_paths[result.champion],
        feature_version=result.feature_version,
        dataset_fingerprint=result.dataset_fingerprint,
    )
    db.add(row)
    db.flush()
    return row


def runtime_model(db: Session, name: str = "success_prob") -> ModelVersion | None:
    """Return the best decision-ready model, preferring CHAMPION over VALIDATED."""
    return (db.query(ModelVersion)
            .filter(ModelVersion.name == name,
                    ModelVersion.stage.in_(RUNTIME_STAGES))
            .order_by(case((ModelVersion.stage == "CHAMPION", 0),
                           (ModelVersion.stage == "VALIDATED", 1), else_=2),
                      ModelVersion.promoted_at.desc(), ModelVersion.trained_at.desc())
            .first())


def champion(db: Session, name: str = "success_prob") -> ModelVersion | None:
    """Backward-compatible name for callers that need a decision-ready model."""
    return runtime_model(db, name)

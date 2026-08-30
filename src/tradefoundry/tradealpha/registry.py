from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.tradealpha.common import idempotent_row, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    ModelPromotionRequest,
    ModelPromotionView,
    ModelVersionCreate,
    ModelVersionView,
)
from tradefoundry.tradealpha.models import ModelPromotionRow, ModelVersionRow


class ModelRegistryService:
    def __init__(self, session: Session):
        self.session = session

    def register(self, request: ModelVersionCreate) -> ModelVersionView:
        request_hash = request_fingerprint({}, request)
        existing = idempotent_row(
            self.session, ModelVersionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return ModelVersionView.model_validate(existing)
        version = self.session.scalar(
            select(func.coalesce(func.max(ModelVersionRow.version_no), 0)).where(
                ModelVersionRow.model_key == request.model_key
            )
        )
        row = ModelVersionRow(
            id=str(uuid4()),
            model_key=request.model_key,
            version_no=int(version) + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            model_type=request.model_type,
            artifact_uri=request.artifact_uri,
            feature_schema_hash=request.feature_schema_hash,
            training_data_cutoff=request.training_data_cutoff,
            validation_start=request.validation_start,
            validation_end=request.validation_end,
            metrics_json=request.metrics,
            out_of_time_metrics_json=request.out_of_time_metrics,
            safety_checks_json=request.safety_checks,
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return ModelVersionView.model_validate(row)

    def promote(self, request: ModelPromotionRequest) -> ModelPromotionView:
        request_hash = request_fingerprint({}, request)
        existing = idempotent_row(
            self.session, ModelPromotionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return ModelPromotionView.model_validate(existing)
        target = self.session.get(ModelVersionRow, request.target_model_version_id)
        if target is None:
            raise LookupError(f"model version {request.target_model_version_id} not found")
        last_accepted = self.session.scalar(
            select(ModelPromotionRow)
            .where(
                ModelPromotionRow.model_key == target.model_key,
                ModelPromotionRow.decision == "accepted",
            )
            .order_by(ModelPromotionRow.created_at.desc(), ModelPromotionRow.id.desc())
        )
        previous_id = last_accepted.target_model_version_id if last_accepted else None
        criteria = request.criteria
        metrics = target.out_of_time_metrics_json
        reasons = []
        if request.action == "rollback":
            prior_acceptance = self.session.scalar(
                select(ModelPromotionRow).where(
                    ModelPromotionRow.target_model_version_id == target.id,
                    ModelPromotionRow.decision == "accepted",
                )
            )
            if prior_acceptance is None:
                reasons.append("rollback target was never an accepted champion")
        if int(metrics.get("sample_count", 0)) < criteria.minimum_samples:
            reasons.append("out-of-time sample count below promotion minimum")
        if float(metrics.get("brier_score", 1.0)) > criteria.max_brier:
            reasons.append("out-of-time Brier score exceeds promotion maximum")
        if float(metrics.get("ece", 1.0)) > criteria.max_ece:
            reasons.append("out-of-time ECE exceeds promotion maximum")
        if criteria.require_safety_pass and not (
            target.safety_checks_json and all(target.safety_checks_json.values())
        ):
            reasons.append("one or more required safety checks failed")
        row = ModelPromotionRow(
            id=str(uuid4()),
            model_key=target.model_key,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            action=request.action,
            previous_model_version_id=previous_id,
            target_model_version_id=target.id,
            criteria_json=criteria.model_dump(mode="json"),
            decision="rejected" if reasons else "accepted",
            reasons_json=reasons,
            actor=request.actor,
        )
        self.session.add(row)
        self.session.commit()
        return ModelPromotionView.model_validate(row)

    def champion(self, model_key: str) -> ModelVersionView:
        promotion = self.session.scalar(
            select(ModelPromotionRow)
            .where(
                ModelPromotionRow.model_key == model_key,
                ModelPromotionRow.decision == "accepted",
            )
            .order_by(ModelPromotionRow.created_at.desc(), ModelPromotionRow.id.desc())
        )
        if promotion is None:
            raise LookupError(f"model {model_key} has no accepted champion")
        return ModelVersionView.model_validate(
            self.session.get(ModelVersionRow, promotion.target_model_version_id)
        )

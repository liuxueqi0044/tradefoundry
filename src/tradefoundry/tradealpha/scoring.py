from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tradefoundry.tradealpha.common import aware, idempotent_row, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    ScoreRequest,
    ScoreSnapshotView,
    ScoringPolicyCreate,
    ScoringPolicyView,
)
from tradefoundry.tradealpha.models import (
    FeatureSnapshotRow,
    ModelPromotionRow,
    ModelVersionRow,
    ScoreSnapshotRow,
    ScoringPolicyRow,
)


class ScoringPolicyService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: ScoringPolicyCreate) -> ScoringPolicyView:
        request_hash = request_fingerprint({}, request)
        existing = idempotent_row(
            self.session, ScoringPolicyRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return ScoringPolicyView.model_validate(existing)
        version = self.session.scalar(
            select(func.coalesce(func.max(ScoringPolicyRow.version_no), 0)).where(
                ScoringPolicyRow.policy_key == request.policy_key
            )
        )
        self.session.execute(
            update(ScoringPolicyRow)
            .where(
                ScoringPolicyRow.policy_key == request.policy_key,
                ScoringPolicyRow.status == "active",
            )
            .values(status="deprecated")
        )
        row = ScoringPolicyRow(
            id=str(uuid4()),
            policy_key=request.policy_key,
            version_no=int(version) + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            name=request.name,
            status="active",
            weights_json=request.weights,
            hard_rules_json=[rule.model_dump(mode="json") for rule in request.hard_rules],
            missing_strategy=request.missing_strategy,
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return ScoringPolicyView.model_validate(row)

    def get(self, policy_id: str) -> ScoringPolicyView:
        row = self.session.get(ScoringPolicyRow, policy_id)
        if row is None:
            raise LookupError(f"scoring policy {policy_id} not found")
        return ScoringPolicyView.model_validate(row)


class ScoreService:
    def __init__(self, session: Session):
        self.session = session

    def score(self, route_id: str, request: ScoreRequest) -> ScoreSnapshotView:
        request_hash = request_fingerprint({"route_id": route_id}, request)
        existing = idempotent_row(
            self.session, ScoreSnapshotRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return ScoreSnapshotView.model_validate(existing)
        snapshot = self.session.get(FeatureSnapshotRow, request.feature_snapshot_id)
        if snapshot is None or snapshot.route_id != route_id:
            raise LookupError("feature snapshot does not exist for this route")
        policy = self.session.get(ScoringPolicyRow, request.policy_id)
        if policy is None:
            raise LookupError(f"scoring policy {request.policy_id} not found")
        if policy.status != "active":
            raise ValueError("only an active scoring policy can create new scores")
        if aware(snapshot.as_of) > request.as_of:
            raise ValueError("score as_of cannot precede its feature snapshot")
        scoring_mode = "rule_baseline"
        if request.model_version_id:
            model = self.session.get(ModelVersionRow, request.model_version_id)
            if model is None:
                raise LookupError(f"model version {request.model_version_id} not found")
            champion = self.session.scalar(
                select(ModelPromotionRow)
                .where(
                    ModelPromotionRow.model_key == model.model_key,
                    ModelPromotionRow.target_model_version_id == model.id,
                    ModelPromotionRow.decision == "accepted",
                )
                .order_by(ModelPromotionRow.created_at.desc())
            )
            if champion is None:
                raise ValueError("only an accepted champion may be used for scoring")
            if model.model_type != "rule_baseline":
                raise ValueError("artifact execution is disabled until a verified runner exists")
            scoring_mode = "registered_rule_baseline"
        hard_reasons = self._hard_reasons(
            policy.hard_rules_json, snapshot.features_json, snapshot.context_json
        )
        factors = []
        assumptions = ["Feature values are normalized to the interval [0, 1]."]
        gaps = []
        weighted_sum = 0.0
        denominator = sum(abs(value) for value in policy.weights_json.values())
        for feature, weight in sorted(policy.weights_json.items()):
            raw_value = snapshot.features_json.get(feature)
            assumed = False
            if raw_value is None:
                gaps.append(feature)
                assumed = True
                if policy.missing_strategy == "veto":
                    hard_reasons.append(f"missing required feature: {feature}")
                    value = 0.0
                elif policy.missing_strategy == "neutral":
                    value = 0.5
                    assumptions.append(f"Missing {feature} was imputed as neutral 0.5.")
                else:
                    value = 0.0
                    assumptions.append(f"Missing {feature} was imputed as zero.")
            else:
                value = max(0.0, min(float(raw_value), 1.0))
            contribution = weight * value
            weighted_sum += contribution
            factors.append(
                {
                    "feature": feature,
                    "value": value,
                    "weight": weight,
                    "contribution": contribution,
                    "assumed": assumed,
                }
            )
        total = max(0.0, min(100.0, 50 + 50 * weighted_sum / denominator))
        sensitivities = sorted(
            (
                {
                    "feature": item["feature"],
                    "score_change_if_value_moves_0_1": abs(item["weight"]) * 5 / denominator,
                }
                for item in factors
            ),
            key=lambda item: (-item["score_change_if_value_moves_0_1"], item["feature"]),
        )
        row = ScoreSnapshotRow(
            id=str(uuid4()),
            route_id=route_id,
            feature_snapshot_id=snapshot.id,
            policy_id=policy.id,
            model_version_id=request.model_version_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            scoring_mode=scoring_mode,
            factors_json=factors,
            total_score=total,
            hard_decision="veto" if hard_reasons else "pass",
            hard_reasons_json=hard_reasons,
            assumptions_json=assumptions,
            gaps_json=gaps,
            sensitivities_json=sensitivities,
        )
        self.session.add(row)
        self.session.commit()
        return ScoreSnapshotView.model_validate(row)

    @staticmethod
    def _hard_reasons(rules: list[dict], features: dict, context: dict) -> list[str]:
        operators = {
            "eq": lambda left, right: left == right,
            "ne": lambda left, right: left != right,
            "lt": lambda left, right: left < right,
            "lte": lambda left, right: left <= right,
            "gt": lambda left, right: left > right,
            "gte": lambda left, right: left >= right,
            "in": lambda left, right: left in right,
            "not_in": lambda left, right: left not in right,
        }
        reasons = []
        for rule in rules:
            field = rule["field"]
            namespace, _, name = field.partition(".")
            values = features if namespace == "feature" else context
            left = values.get(name if name else namespace)
            try:
                matched = operators[rule["operator"]](left, rule["value"])
            except (KeyError, TypeError):
                matched = True
            if matched:
                reasons.append(rule["reason"])
        return reasons

"""Outcome construction, forecast attribution and temporally safe datasets."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.execution.common import (
    aware,
    idempotent_row,
    money,
    new_id,
    request_fingerprint,
    utcnow,
)
from tradefoundry.execution.contracts_learning import (
    LearningDatasetBuildRequest,
    LearningDatasetItemView,
    LearningDatasetView,
    OutcomeBuildRequest,
    OutcomeView,
    PredictionActualRequest,
    PredictionActualView,
)
from tradefoundry.execution.models_learning import (
    LearningDatasetItemRow,
    LearningDatasetRow,
    OutcomeRow,
    PredictionActualRow,
)


def _as_json(value: Any) -> Any:
    """Return JSON-compatible values, including Decimal and datetime values."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return aware(value).isoformat()
    if isinstance(value, dict):
        return {str(k): _as_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_json(v) for v in value]
    return value


class OutcomeBuilder:
    def __init__(self, session: Session):
        self.session = session

    def build(self, request: OutcomeBuildRequest) -> OutcomeView:
        request_hash = request_fingerprint({"service": "outcome"}, request)
        existing = idempotent_row(self.session, OutcomeRow, request.idempotency_key, request_hash)
        if existing is not None:
            return OutcomeView.model_validate(existing)
        # Route existence is checked for every label, including no_reply and stopped.
        from tradefoundry.deals.models import DealRouteRow

        route = self.session.get(DealRouteRow, request.route_id)
        if route is None:
            raise LookupError(f"deal route {request.route_id} was not found")
        order = pnl = collection = cashflow_plan = None
        milestones: list[Any] = []
        quality_cases: list[Any] = []
        if request.status == "success":
            if not (request.order_id and request.pnl_snapshot_id and request.collection_signal_id):
                raise ValueError(
                    "success requires order, reconciled PnL and published "
                    "collection signal references"
                )
            from tradefoundry.execution.models_orders import (
                FulfillmentMilestoneRow,
                OrderCommandRow,
            )
            from tradefoundry.execution.models_settlement import (
                CollectionSignalRow,
                ContributionPnlSnapshotRow,
                QualityCaseRow,
            )

            order = self.session.get(OrderCommandRow, request.order_id)
            pnl = self.session.get(ContributionPnlSnapshotRow, request.pnl_snapshot_id)
            collection = self.session.get(CollectionSignalRow, request.collection_signal_id)
            if order is None or pnl is None or collection is None:
                raise LookupError(
                    "success outcome references missing order, PnL or collection signal"
                )
            if pnl.order_id != order.id or collection.order_id != order.id:
                raise ValueError("order, PnL and collection signal references do not agree")
            if order.route_id != request.route_id:
                raise ValueError("order does not belong to outcome route")
            cutoff = aware(request.outcome_cutoff_at)
            if (
                aware(order.created_at) > cutoff
                or aware(pnl.as_of) > cutoff
                or aware(pnl.created_at) > cutoff
                or aware(collection.published_at) > cutoff
            ):
                raise ValueError("success facts cannot be later than the outcome cutoff")
            if pnl.reconciliation_status != "reconciled":
                raise ValueError("success requires reconciled contribution PnL")
            if collection.status != "published" or collection.published_at is None:
                raise ValueError("success requires a published collected signal")
            milestones = (
                list(
                    self.session.scalars(
                        select(FulfillmentMilestoneRow).where(
                            FulfillmentMilestoneRow.id.in_(request.milestone_ids)
                        )
                    )
                )
                if request.milestone_ids
                else []
            )
            if len(milestones) != len(request.milestone_ids):
                raise LookupError("one or more fulfillment milestones were not found")
            if milestones and not request.shipment_ids:
                raise ValueError("milestones require validated shipment references")
            if any(row.shipment_id not in request.shipment_ids for row in milestones):
                raise ValueError("fulfillment milestone is outside referenced shipments")
            if any(
                aware(row.created_at) > cutoff
                or row.actual_at is not None
                and aware(row.actual_at) > cutoff
                for row in milestones
            ):
                raise ValueError("fulfillment milestone is later than the outcome cutoff")
            quality_cases = (
                list(
                    self.session.scalars(
                        select(QualityCaseRow).where(
                            QualityCaseRow.id.in_(request.quality_case_ids)
                        )
                    )
                )
                if request.quality_case_ids
                else []
            )
            if len(quality_cases) != len(request.quality_case_ids):
                raise LookupError("one or more quality cases were not found")
            if any(row.order_id != order.id for row in quality_cases):
                raise ValueError("quality case is outside referenced order")
            if any(
                aware(row.opened_at) > cutoff
                or row.closed_at is not None
                and aware(row.closed_at) > cutoff
                for row in quality_cases
            ):
                raise ValueError("quality case is later than the outcome cutoff")
        elif request.order_id:
            from tradefoundry.execution.models_orders import OrderCommandRow

            order = self.session.get(OrderCommandRow, request.order_id)
            if order is None:
                raise LookupError(f"order {request.order_id} was not found")
            if order.route_id != request.route_id:
                raise ValueError("order does not belong to outcome route")
            if aware(order.created_at) > aware(request.outcome_cutoff_at):
                raise ValueError("order is later than the outcome cutoff")
        # Monetary and cycle values come from immutable ledger rows, never request claims.
        actual_price = pnl.revenue if pnl is not None else None
        realized_pnl = pnl.contribution if pnl is not None else None
        days = None
        if order is not None and collection is not None and collection.published_at:
            days = max(
                Decimal("0"),
                Decimal(
                    str(
                        (aware(collection.published_at) - aware(order.created_at)).total_seconds()
                        / 86400
                    )
                ),
            )
        peak_capital = None
        if request.cashflow_plan_id:
            from tradefoundry.controltower.models import CashflowPlanRow

            cashflow_plan = self.session.get(CashflowPlanRow, request.cashflow_plan_id)
            if cashflow_plan is None:
                raise LookupError(f"cashflow plan {request.cashflow_plan_id} was not found")
            if cashflow_plan.route_id != route.id:
                raise ValueError("cashflow plan does not belong to outcome route")
            if aware(cashflow_plan.created_at) > aware(request.outcome_cutoff_at):
                raise ValueError("cashflow plan was created after the outcome cutoff")
            peak_capital = cashflow_plan.peak_working_capital
        derived_quality = (
            {
                "case_ids": [row.id for row in quality_cases],
                "closed": all(row.status == "closed" for row in quality_cases),
                "final_loss": str(sum((row.final_loss for row in quality_cases), Decimal("0"))),
            }
            if quality_cases
            else {}
        )
        derived_delay = (
            {
                "max_late_days": max((row.late_days or 0 for row in milestones), default=0),
                "milestone_ids": [row.id for row in milestones],
            }
            if milestones
            else {}
        )
        row = OutcomeRow(
            id=new_id(),
            route_id=request.route_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            outcome_cutoff_at=request.outcome_cutoff_at,
            status=request.status,
            order_id=order.id if order is not None else None,
            pnl_snapshot_id=pnl.id if pnl is not None else None,
            collection_signal_id=collection.id if collection is not None else None,
            cashflow_plan_id=cashflow_plan.id if cashflow_plan is not None else None,
            milestone_ids_json=[row.id for row in milestones],
            quality_case_ids_json=[row.id for row in quality_cases],
            success=request.status == "success",
            no_reply=request.status == "no_reply",
            timeline_json=_as_json(request.timeline),
            interaction_json=_as_json(request.interaction),
            qualification_json=_as_json(request.qualification),
            quote_json=_as_json(request.quote),
            commit_json=_as_json(request.commit),
            delivery_json=_as_json(request.delivery),
            collection_json=_as_json(request.collection),
            currency=request.currency,
            actual_price=money(actual_price) if actual_price is not None else None,
            pnl=money(realized_pnl) if realized_pnl is not None else None,
            peak_capital=money(peak_capital) if peak_capital is not None else None,
            days=days,
            quality_json=_as_json(derived_quality),
            delay_json=_as_json(derived_delay),
            refund_json=_as_json({"final_loss": derived_quality.get("final_loss", "0")}),
            claim_json=_as_json({"case_ids": derived_quality.get("case_ids", [])}),
            failed_stage=request.failed_stage,
            reasons_json=list(request.reasons),
            human_intervention=request.human_intervention,
            exploration_marker=request.exploration_marker,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return OutcomeView.model_validate(row)

    create = build


def _snapshot_as_of(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("as_of") or payload.get("snapshot_at") or payload.get("valuation_at")
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return aware(value)


def _check_upstream_time(row: Any, cutoff: datetime, label: str) -> None:
    for field in ("as_of", "created_at", "recorded_at", "screened_at"):
        value = getattr(row, field, None)
        if value is not None and aware(value) > cutoff:
            raise ValueError(f"{label} {field} is after prediction cutoff")


class PredictionActualService:
    """Pins the prediction payload at prediction time; later mutable rows are ignored."""

    def __init__(self, session: Session):
        self.session = session

    def compare(self, request: PredictionActualRequest) -> PredictionActualView:
        request_hash = request_fingerprint({"service": "prediction_actual"}, request)
        existing = idempotent_row(
            self.session, PredictionActualRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return PredictionActualView.model_validate(existing)
        outcome = self.session.get(OutcomeRow, request.outcome_id)
        if outcome is None:
            raise LookupError(f"outcome {request.outcome_id} was not found")
        cutoff = aware(request.prediction_cutoff_at)
        if cutoff >= aware(outcome.outcome_cutoff_at):
            raise ValueError("prediction cutoff must be before outcome cutoff")

        from tradefoundry.controltower.models import LandedCostScenarioRow
        from tradefoundry.execution.models_settlement import ContributionPnlSnapshotRow
        from tradefoundry.tradealpha.models import ProbabilityEstimateRow, ScoreSnapshotRow

        score_source = self.session.get(ScoreSnapshotRow, request.score_snapshot_id)
        probability_source = self.session.get(
            ProbabilityEstimateRow, request.probability_estimate_id
        )
        cost_source = self.session.get(LandedCostScenarioRow, request.board8_cost_snapshot_id)
        pinned_pnl = self.session.get(ContributionPnlSnapshotRow, request.pnl_snapshot_id)
        if any(row is None for row in (score_source, probability_source, cost_source, pinned_pnl)):
            raise LookupError(
                "prediction comparison requires all four immutable snapshot references"
            )
        if (
            score_source.route_id != outcome.route_id
            or probability_source.route_id != outcome.route_id
        ):
            raise ValueError("prediction snapshots do not belong to outcome route")
        if cost_source.route_id and cost_source.route_id != outcome.route_id:
            raise ValueError("cost snapshot does not belong to outcome route")
        if outcome.order_id and pinned_pnl.order_id != outcome.order_id:
            raise ValueError("PnL snapshot does not belong to outcome order")
        for row, label in (
            (score_source, "score snapshot"),
            (probability_source, "probability estimate"),
            (cost_source, "cost snapshot"),
        ):
            _check_upstream_time(row, cutoff, label)
        if request.pnl_snapshot_id != outcome.pnl_snapshot_id:
            raise ValueError("actual PnL must be the snapshot pinned by the outcome")
        _check_upstream_time(pinned_pnl, aware(outcome.outcome_cutoff_at), "PnL snapshot")
        score = {
            "id": score_source.id,
            "as_of": aware(score_source.as_of).isoformat(),
            "total_score": score_source.total_score,
            "scoring_mode": score_source.scoring_mode,
            "factors": score_source.factors_json,
        }
        probability = float(probability_source.overall_mean)
        cost = {
            "id": cost_source.id,
            "as_of": aware(cost_source.created_at).isoformat(),
            "total_base": str(cost_source.total_base),
            "currency": cost_source.currency,
            "calculator_version": cost_source.calculator_version,
        }
        predicted_cost = Decimal(str(cost_source.total_base))
        actual_cost = pinned_pnl.revenue - pinned_pnl.contribution
        cost_error = (
            (actual_cost - predicted_cost)
            if actual_cost is not None and predicted_cost is not None
            else None
        )
        actual_days = outcome.days
        cycle_error = None
        if actual_days is not None and request.predicted_cycle_days is not None:
            cycle_error = actual_days - request.predicted_cycle_days
        probability_error = None
        if probability is not None:
            probability_error = probability - (1.0 if outcome.success else 0.0)
        row = PredictionActualRow(
            id=new_id(),
            outcome_id=outcome.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            prediction_cutoff_at=cutoff,
            outcome_cutoff_at=outcome.outcome_cutoff_at,
            score_snapshot_id=request.score_snapshot_id,
            probability_estimate_id=request.probability_estimate_id,
            board8_cost_snapshot_id=request.board8_cost_snapshot_id,
            pnl_snapshot_id=request.pnl_snapshot_id or outcome.pnl_snapshot_id,
            score_snapshot_json=_as_json(score),
            probability_estimate=probability,
            cost_snapshot_json=_as_json(cost),
            predicted_cost=money(predicted_cost) if predicted_cost is not None else None,
            actual_cost=money(actual_cost) if actual_cost is not None else None,
            cost_error=money(cost_error) if cost_error is not None else None,
            cycle_error=cycle_error,
            probability_error=probability_error,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return PredictionActualView.model_validate(row)

    build = compare


class LearningDatasetService:
    def __init__(self, session: Session):
        self.session = session

    def build(self, request: LearningDatasetBuildRequest) -> LearningDatasetView:
        request_hash = request_fingerprint({"service": "dataset"}, request)
        existing = idempotent_row(
            self.session, LearningDatasetRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return LearningDatasetView.model_validate(existing)
        if all(item.label == "success" for item in request.observations):
            raise ValueError("learning dataset must include failure or no_reply observations")
        from tradefoundry.tradealpha.models import FeatureSnapshotRow

        hydrated: list[tuple[Any, Any, Any]] = []
        for item in request.observations:
            feature = self.session.get(FeatureSnapshotRow, item.feature_snapshot_id)
            if feature is None:
                raise LookupError(f"feature snapshot {item.feature_snapshot_id} was not found")
            if item.route_id and feature.route_id != item.route_id:
                raise ValueError(f"feature snapshot route mismatch for {item.observation_id}")
            cutoff = aware(item.observation_cutoff)
            if (
                aware(feature.as_of) > cutoff
                or aware(feature.source_max_available_at) > cutoff
                or aware(feature.created_at) > cutoff
            ):
                raise ValueError(
                    f"feature snapshot is after observation cutoff for {item.observation_id}"
                )
            linked_outcome = None
            if item.outcome_id:
                linked_outcome = self.session.get(OutcomeRow, item.outcome_id)
                if linked_outcome is None:
                    raise LookupError(f"outcome {item.outcome_id} was not found")
                expected = (
                    "success"
                    if linked_outcome.success
                    else "no_reply"
                    if linked_outcome.no_reply
                    else "failure"
                )
                if item.label != expected:
                    raise ValueError(f"label does not match outcome {item.outcome_id}")
                if item.route_id and linked_outcome.route_id != item.route_id:
                    raise ValueError(f"outcome route mismatch for {item.observation_id}")
                if cutoff >= aware(linked_outcome.outcome_cutoff_at):
                    raise ValueError(
                        f"observation cutoff must precede outcome {item.outcome_id}"
                    )
            hydrated.append((item, feature, linked_outcome))
        labels = {key: 0 for key in ("success", "failure", "no_reply")}
        for item, _feature, _outcome in hydrated:
            labels[item.label] += 1
        dataset = LearningDatasetRow(
            id=new_id(),
            dataset_key=request.dataset_key,
            dataset_version=request.dataset_version,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            feature_schema_version=request.feature_schema_version,
            row_count=len(request.observations),
            label_counts_json=labels,
            status="immutable",
            created_at=utcnow(),
        )
        self.session.add(dataset)
        self.session.flush()
        for item, feature, _outcome in hydrated:
            self.session.add(
                LearningDatasetItemRow(
                    id=new_id(),
                    dataset_id=dataset.id,
                    observation_id=item.observation_id,
                    outcome_id=item.outcome_id,
                    route_id=item.route_id,
                    observation_cutoff=item.observation_cutoff,
                    feature_snapshot_json=_as_json(
                        {
                            "registry_hash": feature.registry_hash,
                            "features": feature.features_json,
                            "sources": feature.sources_json,
                            "context": feature.context_json,
                        }
                    ),
                    feature_snapshot_id=feature.id,
                    feature_as_of=feature.as_of,
                    source_max_available_at=feature.source_max_available_at or feature.as_of,
                    label=item.label,
                    human_intervention=item.human_intervention,
                    exploration_marker=item.exploration_marker,
                    created_at=utcnow(),
                )
            )
        self.session.commit()
        return LearningDatasetView.model_validate(dataset)

    create = build

    def items(self, dataset_id: str) -> list[LearningDatasetItemView]:
        return [
            LearningDatasetItemView.model_validate(row)
            for row in self.session.scalars(
                select(LearningDatasetItemRow)
                .where(LearningDatasetItemRow.dataset_id == dataset_id)
                .order_by(LearningDatasetItemRow.observation_cutoff, LearningDatasetItemRow.id)
            )
        ]

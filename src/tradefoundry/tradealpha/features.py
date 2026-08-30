from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.models import (
    ActionAttemptRow,
    ActionRow,
    BudgetSpendRow,
    DealCellRow,
    DealRouteRow,
    ExperimentOutcomeRow,
    ExperimentRow,
    ObservationRow,
    RouteLifecycleEventRow,
    StageTransitionRow,
)
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.opportunity.models import (
    ParticipantCandidateRow,
    ProductNeedRow,
    RouteCandidateRow,
    TradeHypothesisRow,
    WorldEventRow,
)
from tradefoundry.tradealpha.common import aware, idempotent_row, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    FeatureDefinitionCreate,
    FeatureDefinitionView,
    FeatureSnapshotRequest,
    FeatureSnapshotView,
)
from tradefoundry.tradealpha.models import FeatureDefinitionRow, FeatureSnapshotRow

BUILTIN_FEATURES = [
    ("event_reliability", "event", "reliability", "event_reliability", "ratio"),
    (
        "hypothesis_prior_midpoint",
        "hypothesis",
        "probability_band",
        "hypothesis_prior_midpoint",
        "ratio",
    ),
    ("route_stage_progress", "deal", "stage", "route_stage_progress", "ratio"),
    ("observation_count", "deal", "observations", "observation_count", "count"),
    (
        "experiment_success_rate",
        "outcome",
        "experiment_outcomes",
        "experiment_success_rate",
        "ratio",
    ),
    ("action_success_rate", "outcome", "action_status", "action_success_rate", "ratio"),
    ("sunk_cost_ratio", "deal", "budget_spends", "sunk_cost_ratio", "ratio"),
    ("evidence_completeness", "derived", "available_inputs", "evidence_completeness", "ratio"),
]

STAGE_PROGRESS = {
    "issued": 0.0,
    "hypothesized": 0.05,
    "probe_ready": 0.12,
    "probing": 0.2,
    "engaged": 0.35,
    "qualified": 0.5,
    "priceable": 0.62,
    "quoted": 0.72,
    "negotiating": 0.8,
    "committed": 0.9,
    "collected": 1.0,
    "stopped": 0.0,
}


class FeatureRegistryService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: FeatureDefinitionCreate) -> FeatureDefinitionView:
        request_hash = request_fingerprint({}, request)
        existing = idempotent_row(
            self.session, FeatureDefinitionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return FeatureDefinitionView.model_validate(existing)
        version = self.session.scalar(
            select(func.coalesce(func.max(FeatureDefinitionRow.version_no), 0)).where(
                FeatureDefinitionRow.feature_key == request.feature_key
            )
        )
        row = FeatureDefinitionRow(
            id=str(uuid4()),
            version_no=int(version) + 1,
            request_hash=request_hash,
            status="active",
            **request.model_dump(),
        )
        self.session.execute(
            update(FeatureDefinitionRow)
            .where(
                FeatureDefinitionRow.feature_key == request.feature_key,
                FeatureDefinitionRow.status == "active",
            )
            .values(status="deprecated")
        )
        self.session.add(row)
        self.session.commit()
        return FeatureDefinitionView.model_validate(row)

    def seed_defaults(self) -> list[FeatureDefinitionView]:
        results = []
        for key, kind, field, calculator, value_type in BUILTIN_FEATURES:
            results.append(
                self.create(
                    FeatureDefinitionCreate(
                        feature_key=key,
                        idempotency_key=f"builtin-feature:{key}:v1",
                        source_kind=kind,
                        source_field=field,
                        value_type=value_type,
                        calculation_ref=calculator,
                        available_time_rule="occurred_and_recorded"
                        if kind == "outcome"
                        else "created_at",
                        description=f"TradeAlpha built-in feature: {key}",
                        created_by="system",
                    )
                )
            )
        return results

    def list_active(self) -> list[FeatureDefinitionView]:
        rows = self.session.scalars(
            select(FeatureDefinitionRow)
            .where(FeatureDefinitionRow.status == "active")
            .order_by(FeatureDefinitionRow.feature_key)
        ).all()
        return [FeatureDefinitionView.model_validate(row) for row in rows]


class FeatureSnapshotService:
    def __init__(self, session: Session):
        self.session = session

    def materialize(self, route_id: str, request: FeatureSnapshotRequest) -> FeatureSnapshotView:
        request_hash = request_fingerprint({"route_id": route_id}, request)
        existing = idempotent_row(
            self.session, FeatureSnapshotRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return FeatureSnapshotView.model_validate(existing)
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        if aware(route.created_at) > request.as_of:
            raise ValueError("route did not exist at the requested as_of time")
        definitions = self.session.scalars(
            select(FeatureDefinitionRow)
            .where(FeatureDefinitionRow.status == "active")
            .order_by(FeatureDefinitionRow.feature_key)
        ).all()
        if not definitions:
            FeatureRegistryService(self.session).seed_defaults()
            definitions = self.session.scalars(
                select(FeatureDefinitionRow)
                .where(FeatureDefinitionRow.status == "active")
                .order_by(FeatureDefinitionRow.feature_key)
            ).all()
        context, records = self._context(route, request.as_of)
        values: dict[str, float | None] = {}
        sources: dict[str, list[dict]] = {}
        for definition in definitions:
            value, refs = self._calculate(definition.calculation_ref, route, context, records)
            values[definition.feature_key] = value
            sources[definition.feature_key] = refs
        available_times = [aware(route.created_at)]
        for refs in sources.values():
            available_times.extend(datetime.fromisoformat(ref["available_at"]) for ref in refs)
        source_max = max(available_times)
        if source_max > request.as_of:
            raise ValueError("feature snapshot contains information unavailable at as_of")
        registry_hash = payload_hash(
            [
                {
                    "id": row.id,
                    "feature_key": row.feature_key,
                    "version_no": row.version_no,
                    "calculation_ref": row.calculation_ref,
                }
                for row in definitions
            ]
        )
        completeness = sum(value is not None for value in values.values()) / len(values)
        row = FeatureSnapshotRow(
            id=str(uuid4()),
            route_id=route_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            registry_hash=registry_hash,
            features_json=values,
            sources_json=sources,
            context_json=context,
            completeness=completeness,
            source_max_available_at=source_max,
        )
        self.session.add(row)
        self.session.commit()
        return FeatureSnapshotView.model_validate(row)

    def _context(self, route: DealRouteRow, as_of: datetime) -> tuple[dict, dict]:
        cell = self.session.get(DealCellRow, route.cell_id)
        hypothesis = self.session.get(TradeHypothesisRow, cell.hypothesis_id) if cell else None
        candidate = (
            self.session.get(RouteCandidateRow, route.source_route_candidate_id)
            if route.source_route_candidate_id
            else None
        )
        event = None
        if candidate:
            event = self.session.get(WorldEventRow, candidate.event_id)
        elif hypothesis and hypothesis.event_ids_json:
            event = self.session.get(WorldEventRow, hypothesis.event_ids_json[0])
        buyer_ids: list[str] = []
        if hypothesis:
            participants = self.session.scalars(
                select(ParticipantCandidateRow).where(
                    ParticipantCandidateRow.id.in_(hypothesis.buyer_candidate_ids_json)
                )
            ).all()
            buyer_ids = sorted({row.entity_id for row in participants})
        product_ids: list[str] = []
        if hypothesis:
            needs = self.session.scalars(
                select(ProductNeedRow).where(
                    ProductNeedRow.id.in_(hypothesis.product_need_ids_json)
                )
            ).all()
            product_ids = sorted({row.product_concept_id for row in needs})
        transitions = self.session.scalars(
            select(StageTransitionRow)
            .where(
                StageTransitionRow.route_id == route.id,
                StageTransitionRow.outcome == "accepted",
                StageTransitionRow.created_at <= as_of,
            )
            .order_by(StageTransitionRow.created_at, StageTransitionRow.id)
        ).all()
        stage = transitions[-1].to_stage if transitions else "hypothesized"
        observations = self.session.scalars(
            select(ObservationRow).where(
                ObservationRow.route_id == route.id,
                ObservationRow.occurred_at <= as_of,
                ObservationRow.created_at <= as_of,
            )
        ).all()
        experiments = self.session.scalars(
            select(ExperimentRow).where(
                ExperimentRow.route_id == route.id, ExperimentRow.created_at <= as_of
            )
        ).all()
        experiment_ids = [row.id for row in experiments]
        experiment_outcomes = []
        if experiment_ids:
            experiment_outcomes = self.session.scalars(
                select(ExperimentOutcomeRow).where(
                    ExperimentOutcomeRow.experiment_id.in_(experiment_ids),
                    ExperimentOutcomeRow.created_at <= as_of,
                )
            ).all()
        actions = self.session.scalars(
            select(ActionRow).where(ActionRow.route_id == route.id, ActionRow.created_at <= as_of)
        ).all()
        action_ids = [row.id for row in actions]
        attempts = []
        if action_ids:
            attempts = self.session.scalars(
                select(ActionAttemptRow).where(
                    ActionAttemptRow.action_id.in_(action_ids),
                    ActionAttemptRow.completed_at.is_not(None),
                    ActionAttemptRow.completed_at <= as_of,
                )
            ).all()
        spends = []
        if action_ids:
            spends = self.session.scalars(
                select(BudgetSpendRow).where(
                    BudgetSpendRow.action_id.in_(action_ids),
                    BudgetSpendRow.created_at <= as_of,
                )
            ).all()
        lifecycle_events = self.session.scalars(
            select(RouteLifecycleEventRow)
            .where(
                RouteLifecycleEventRow.route_id == route.id,
                RouteLifecycleEventRow.created_at <= as_of,
            )
            .order_by(RouteLifecycleEventRow.created_at, RouteLifecycleEventRow.id)
        ).all()
        lifecycle_status = lifecycle_events[-1].new_status if lifecycle_events else "active"
        context = {
            "route_id": route.id,
            "cell_id": route.cell_id,
            "route_type": route.route_type,
            "lifecycle_status": lifecycle_status,
            "stage": stage,
            "currency": route.currency,
            "country_code": event.country_code if event else None,
            "buyer_ids": buyer_ids,
            "product_ids": product_ids,
            "event_id": event.id if event else None,
            "hypothesis_id": hypothesis.id if hypothesis else None,
        }
        return context, {
            "route": route,
            "hypothesis": hypothesis,
            "event": event,
            "transitions": transitions,
            "observations": observations,
            "experiments": experiments,
            "experiment_outcomes": experiment_outcomes,
            "actions": actions,
            "action_attempts": attempts,
            "spends": spends,
        }

    def _calculate(self, ref: str, route: DealRouteRow, context: dict, records: dict):
        def source(kind: str, row, available_at=None) -> dict:
            return {
                "kind": kind,
                "id": row.id,
                "available_at": aware(available_at or row.created_at).isoformat(),
            }

        event = records["event"]
        hypothesis = records["hypothesis"]
        if ref == "event_reliability":
            return (event.reliability, [source("event", event)]) if event else (None, [])
        if ref == "hypothesis_prior_midpoint":
            return (
                (
                    (hypothesis.probability_low + hypothesis.probability_high) / 2,
                    [source("hypothesis", hypothesis)],
                )
                if hypothesis
                else (None, [])
            )
        if ref == "route_stage_progress":
            refs = [source("stage_transition", row) for row in records["transitions"]]
            return STAGE_PROGRESS.get(context["stage"], 0.0), refs or [source("route", route)]
        if ref == "observation_count":
            rows = records["observations"]
            return min(len(rows) / 10, 1.0), [source("observation", row) for row in rows]
        if ref == "experiment_success_rate":
            rows = records["experiment_outcomes"]
            successes = sum(row.outcome == "success" for row in rows)
            return (successes + 1) / (len(rows) + 2), [
                source("experiment_outcome", row) for row in rows
            ]
        if ref == "action_success_rate":
            rows = records["action_attempts"]
            successes = sum(row.status == "succeeded" for row in rows)
            return (successes + 1) / (len(rows) + 2), [
                source("action_attempt", row, row.completed_at) for row in rows
            ]
        if ref == "sunk_cost_ratio":
            rows = records["spends"]
            total = sum((row.amount for row in rows), Decimal(0))
            value = float(total / route.budget_limit) if route.budget_limit else 0.0
            return min(value, 1.0), [source("budget_spend", row) for row in rows]
        if ref == "evidence_completeness":
            types = {row.observation_type for row in records["observations"]}
            return min(len(types) / 10, 1.0), [
                source("observation", row) for row in records["observations"]
            ]
        raise ValueError(f"unknown feature calculator {ref}")

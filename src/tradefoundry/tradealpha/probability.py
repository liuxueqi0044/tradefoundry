from __future__ import annotations

from uuid import uuid4

import numpy as np
from scipy.stats import beta as beta_distribution
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.deals.models import DealRouteRow, StageTransitionRow
from tradefoundry.tradealpha.common import aware, idempotent_row, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    ProbabilityEstimateRequest,
    ProbabilityEstimateView,
)
from tradefoundry.tradealpha.models import FeatureSnapshotRow, ProbabilityEstimateRow

STAGES = ["engaged", "qualified", "quoted", "committed", "collected"]
STAGE_ORDER = {
    "issued": 0,
    "hypothesized": 1,
    "probe_ready": 2,
    "probing": 3,
    "engaged": 4,
    "qualified": 5,
    "priceable": 6,
    "quoted": 7,
    "negotiating": 8,
    "committed": 9,
    "collected": 10,
    "stopped": -1,
}


class ProbabilityService:
    def __init__(self, session: Session):
        self.session = session

    def estimate(
        self, route_id: str, request: ProbabilityEstimateRequest
    ) -> ProbabilityEstimateView:
        request_hash = request_fingerprint({"route_id": route_id}, request)
        existing = idempotent_row(
            self.session, ProbabilityEstimateRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return ProbabilityEstimateView.model_validate(existing)
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        context = {"country_code": "unknown", "product_ids": [], "buyer_ids": []}
        if request.feature_snapshot_id:
            snapshot = self.session.get(FeatureSnapshotRow, request.feature_snapshot_id)
            if snapshot is None or snapshot.route_id != route_id:
                raise LookupError("feature snapshot does not exist for this route")
            if aware(snapshot.as_of) > request.as_of:
                raise ValueError("probability as_of cannot precede feature snapshot")
            context = {**snapshot.context_json, "cohort_scope": "portfolio_fallback"}
        routes = self.session.scalars(
            select(DealRouteRow).where(DealRouteRow.created_at <= request.as_of)
        ).all()
        if request.feature_snapshot_id:
            candidates = self.session.scalars(
                select(FeatureSnapshotRow).where(
                    FeatureSnapshotRow.as_of <= request.as_of,
                    FeatureSnapshotRow.registry_hash == snapshot.registry_hash,
                )
            ).all()
            latest = {}
            for item in candidates:
                previous = latest.get(item.route_id)
                if previous is None or aware(item.as_of) > aware(previous.as_of):
                    latest[item.route_id] = item

            def same_slice(item, fields):
                for field in fields:
                    left = context.get(field)
                    right = item.context_json.get(field)
                    if isinstance(left, list):
                        if left and right and not set(left).intersection(right):
                            return False
                    elif left and right and left != right:
                        return False
                return True

            hierarchy = [
                ("country_product_buyer", ["country_code", "product_ids", "buyer_ids"]),
                ("country_product", ["country_code", "product_ids"]),
                ("country", ["country_code"]),
            ]
            by_id = {item.id: item for item in routes}
            for scope, fields in hierarchy:
                matched = [
                    by_id[candidate_route_id]
                    for candidate_route_id, item in latest.items()
                    if candidate_route_id in by_id and same_slice(item, fields)
                ]
                if len(matched) >= 20:
                    routes = matched
                    context["cohort_scope"] = scope
                    break
        route_ids = [item.id for item in routes]
        transitions = (
            self.session.scalars(
                select(StageTransitionRow).where(
                    StageTransitionRow.route_id.in_(route_ids),
                    StageTransitionRow.outcome == "accepted",
                    StageTransitionRow.created_at <= request.as_of,
                )
            ).all()
            if route_ids
            else []
        )
        stage_sets: dict[str, set[str]] = {item.id: {"issued", "hypothesized"} for item in routes}
        for transition in transitions:
            stage_sets[transition.route_id].add(transition.to_stage)
        rng = np.random.default_rng(request.seed)
        alpha_tail = (1 - request.interval_mass) / 2
        stages_json = []
        samples = np.ones(10_000)
        previous = None
        total_observations = 0
        for stage in STAGES:
            prior = request.priors.get(stage)
            prior_alpha = prior.alpha if prior else 1.0
            prior_beta = prior.beta if prior else 1.0
            at_risk = (
                routes
                if previous is None
                else [item for item in routes if previous in stage_sets[item.id]]
            )
            successes = sum(stage in stage_sets[item.id] for item in at_risk)
            failures = len(at_risk) - successes
            posterior_alpha = prior_alpha + successes
            posterior_beta = prior_beta + failures
            mean = posterior_alpha / (posterior_alpha + posterior_beta)
            low = float(beta_distribution.ppf(alpha_tail, posterior_alpha, posterior_beta))
            high = float(beta_distribution.ppf(1 - alpha_tail, posterior_alpha, posterior_beta))
            samples *= rng.beta(posterior_alpha, posterior_beta, len(samples))
            total_observations += len(at_risk)
            stages_json.append(
                {
                    "stage": stage,
                    "conditional_on": previous or "route_created",
                    "successes": successes,
                    "failures": failures,
                    "prior_alpha": prior_alpha,
                    "prior_beta": prior_beta,
                    "posterior_alpha": posterior_alpha,
                    "posterior_beta": posterior_beta,
                    "mean": mean,
                    "low": low,
                    "high": high,
                }
            )
            previous = stage
        row = ProbabilityEstimateRow(
            id=str(uuid4()),
            route_id=route_id,
            feature_snapshot_id=request.feature_snapshot_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            estimator_version="beta-chain-v1",
            context_json=context,
            stages_json=stages_json,
            overall_mean=float(samples.mean()),
            overall_low=float(np.quantile(samples, alpha_tail)),
            overall_high=float(np.quantile(samples, 1 - alpha_tail)),
            sample_size=total_observations,
        )
        self.session.add(row)
        self.session.commit()
        return ProbabilityEstimateView.model_validate(row)

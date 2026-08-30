from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

import numpy as np
from sqlalchemy.orm import Session

from tradefoundry.tradealpha.common import aware, idempotent_row, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    BacktestRequest,
    BacktestRunView,
    CalibrationPoint,
    CalibrationReportView,
    CalibrationRequest,
)
from tradefoundry.tradealpha.features import STAGE_PROGRESS
from tradefoundry.tradealpha.models import (
    BacktestRunRow,
    CalibrationReportRow,
    FeatureSnapshotRow,
    ScoringPolicyRow,
)


def _rank_metrics(ranking: list[str], outcomes: dict[str, bool], top_k: int) -> dict:
    selected = ranking[: min(top_k, len(ranking))]
    hits = sum(outcomes[item] for item in selected)
    overall_rate = sum(outcomes.values()) / len(outcomes) if outcomes else 0.0
    selected_rate = hits / len(selected) if selected else 0.0
    return {
        "top_k": len(selected),
        "hits": hits,
        "hit_rate": selected_rate,
        "overall_rate": overall_rate,
        "uplift": selected_rate - overall_rate,
    }


class BacktestService:
    def __init__(self, session: Session):
        self.session = session

    def run(self, policy_id: str, request: BacktestRequest) -> BacktestRunView:
        request_hash = request_fingerprint({"policy_id": policy_id}, request)
        existing = idempotent_row(
            self.session, BacktestRunRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return BacktestRunView.model_validate(existing)
        policy = self.session.get(ScoringPolicyRow, policy_id)
        if policy is None:
            raise LookupError(f"scoring policy {policy_id} not found")
        snapshots = []
        route_ids = set()
        leakage = []
        for snapshot_id in request.feature_snapshot_ids:
            snapshot = self.session.get(FeatureSnapshotRow, snapshot_id)
            if snapshot is None:
                raise LookupError(f"feature snapshot {snapshot_id} not found")
            if snapshot.route_id in route_ids:
                raise ValueError("backtest requires one snapshot per route")
            route_ids.add(snapshot.route_id)
            if (
                aware(snapshot.as_of) > request.cutoff_at
                or aware(snapshot.source_max_available_at) > request.cutoff_at
            ):
                leakage.append(snapshot.id)
            snapshots.append(snapshot)
        labels = {label.route_id: label for label in request.labels}
        if route_ids != set(labels):
            raise ValueError("backtest labels must exactly match snapshot route IDs")
        leakage.extend(
            label.route_id
            for label in request.labels
            if label.outcome_available_at <= request.cutoff_at
        )
        if leakage:
            raise ValueError(f"temporal leakage detected in {len(set(leakage))} routes")
        denominator = sum(abs(value) for value in policy.weights_json.values())

        def alpha_score(snapshot):
            weighted = 0.0
            for feature, weight in policy.weights_json.items():
                value = snapshot.features_json.get(feature)
                if value is None:
                    value = 0.5 if policy.missing_strategy == "neutral" else 0.0
                weighted += weight * max(0.0, min(float(value), 1.0))
            return 50 + 50 * weighted / denominator

        outcomes = {key: label.outcome for key, label in labels.items()}
        scores = {
            "alpha": {snapshot.route_id: alpha_score(snapshot) for snapshot in snapshots},
            "simple": {
                snapshot.route_id: STAGE_PROGRESS.get(
                    snapshot.context_json.get("stage", "hypothesized"), 0.0
                )
                for snapshot in snapshots
            },
            "manual": {route_id: label.manual_baseline_score for route_id, label in labels.items()},
        }
        rng = np.random.default_rng(request.seed)
        scores["random"] = {route_id: float(rng.random()) for route_id in sorted(route_ids)}
        rankings = {
            name: sorted(values, key=lambda route_id: (-values[route_id], route_id))
            for name, values in scores.items()
        }
        metrics = {
            name: _rank_metrics(ranking, outcomes, request.top_k)
            for name, ranking in rankings.items()
        }
        row = BacktestRunRow(
            id=str(uuid4()),
            policy_id=policy_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            cutoff_at=request.cutoff_at,
            top_k=request.top_k,
            seed=request.seed,
            route_count=len(snapshots),
            leakage_count=0,
            metrics_json=metrics,
            rankings_json=rankings,
            baselines_json={
                "simple": "stage_progress",
                "random_seed": request.seed,
                "manual": True,
            },
        )
        self.session.add(row)
        self.session.commit()
        return BacktestRunView.model_validate(row)


def _calibration_metrics(points: list[CalibrationPoint], bins: int) -> dict:
    if not points:
        return {"sample_count": 0, "brier_score": None, "ece": None, "mean_prediction": None}
    predictions = np.asarray([item.prediction for item in points], dtype=float)
    outcomes = np.asarray([item.outcome for item in points], dtype=float)
    brier = float(np.mean((predictions - outcomes) ** 2))
    bucket_ids = np.minimum((predictions * bins).astype(int), bins - 1)
    ece = 0.0
    bucket_rows = []
    for bucket in range(bins):
        mask = bucket_ids == bucket
        if not mask.any():
            continue
        mean_prediction = float(predictions[mask].mean())
        outcome_rate = float(outcomes[mask].mean())
        weight = float(mask.mean())
        ece += weight * abs(mean_prediction - outcome_rate)
        bucket_rows.append(
            {
                "bucket": bucket,
                "count": int(mask.sum()),
                "mean_prediction": mean_prediction,
                "outcome_rate": outcome_rate,
            }
        )
    return {
        "sample_count": len(points),
        "brier_score": brier,
        "ece": ece,
        "mean_prediction": float(predictions.mean()),
        "bins": bucket_rows,
    }


class CalibrationService:
    def __init__(self, session: Session):
        self.session = session

    def evaluate(self, request: CalibrationRequest) -> CalibrationReportView:
        request_hash = request_fingerprint({}, request)
        existing = idempotent_row(
            self.session, CalibrationReportRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return CalibrationReportView.model_validate(existing)
        if not request.window_start < request.window_end <= request.evaluated_at:
            raise ValueError("calibration window must end by evaluated_at")
        points = [
            item
            for item in request.points
            if request.window_start <= item.prediction_at < request.window_end
            and item.outcome_at <= request.evaluated_at
        ]
        overall = _calibration_metrics(points, request.bins)
        grouped: dict[tuple[str, str], list[CalibrationPoint]] = defaultdict(list)
        for item in points:
            grouped[("country", item.country_code)].append(item)
            grouped[("product", item.product_id)].append(item)
        slices = [
            {"dimension": dimension, "key": key, **_calibration_metrics(items, request.bins)}
            for (dimension, key), items in sorted(grouped.items())
        ]
        drift = (
            abs(overall["mean_prediction"] - request.reference_mean_prediction)
            if points and request.reference_mean_prediction is not None
            else None
        )
        failures = []
        if len(points) < request.minimum_samples:
            status = "insufficient_data"
            recommendation = "rule_baseline_only"
        else:
            if overall["brier_score"] > request.max_brier:
                failures.append("brier_score")
            if overall["ece"] > request.max_ece:
                failures.append("ece")
            if drift is not None and drift > request.max_mean_prediction_drift:
                failures.append("mean_prediction_drift")
            status = "degraded" if failures else "healthy"
            recommendation = "fallback_rule_baseline" if failures else "continue_monitoring"
        thresholds = {
            "minimum_samples": request.minimum_samples,
            "max_brier": request.max_brier,
            "max_ece": request.max_ece,
            "max_mean_prediction_drift": request.max_mean_prediction_drift,
        }
        overall.update({"mean_prediction_drift": drift, "failed_checks": failures})
        row = CalibrationReportRow(
            id=str(uuid4()),
            model_version_id=request.model_version_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            evaluated_at=request.evaluated_at,
            window_start=request.window_start,
            window_end=request.window_end,
            sample_count=len(points),
            brier_score=overall["brier_score"],
            ece=overall["ece"],
            status=status,
            recommendation=recommendation,
            overall_json=overall,
            slices_json=slices,
            thresholds_json=thresholds,
        )
        self.session.add(row)
        self.session.commit()
        return CalibrationReportView.model_validate(row)

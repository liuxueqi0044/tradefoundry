"""Out-of-time evaluation and challenger eligibility (never model promotion)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from tradefoundry.execution.common import aware, idempotent_row, new_id, request_fingerprint, utcnow
from tradefoundry.execution.contracts_learning import EvaluationReportView, EvaluationRequest
from tradefoundry.execution.models_learning import (
    EvaluationReportRow,
    LearningDatasetItemRow,
    LearningDatasetRow,
)


def _brier(predictions: Sequence[float], labels: Sequence[bool]) -> float:
    return sum((float(p) - int(y)) ** 2 for p, y in zip(predictions, labels, strict=True)) / len(
        labels
    )


def _ece(predictions: Sequence[float], labels: Sequence[bool], bins: int) -> float:
    total = len(labels)
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        selected = [
            i
            for i, p in enumerate(predictions)
            if low <= p < high or (index == bins - 1 and p == high)
        ]
        if selected:
            mean_prediction = sum(float(predictions[i]) for i in selected) / len(selected)
            frequency = sum(bool(labels[i]) for i in selected) / len(selected)
            error += len(selected) / total * abs(mean_prediction - frequency)
    return error


def calibration_metrics(
    predictions: Sequence[float], labels: Sequence[bool], bins: int = 10
) -> dict[str, Any]:
    if not labels:
        return {"sample_count": 0, "brier_score": None, "ece": None}
    if any(not 0 <= float(p) <= 1 for p in predictions):
        raise ValueError("probability predictions must be between 0 and 1")
    return {
        "sample_count": len(labels),
        "brier_score": _brier(predictions, labels),
        "ece": _ece(predictions, labels, bins),
        "mean_prediction": sum(predictions) / len(predictions),
        "positive_rate": sum(labels) / len(labels),
    }


def _economic_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize economic inputs while preserving the caller's auditable values."""
    result = dict(data)
    if "baseline" not in result and "baseline_value" in result:
        result["baseline"] = result["baseline_value"]
    if "challenger" not in result and "challenger_value" in result:
        result["challenger"] = result["challenger_value"]
    if "challenger" in result and "baseline" in result:
        result["challenger_better"] = float(result["challenger"]) >= float(result["baseline"])
    else:
        # No economic simulation was supplied; do not invent a number. The calibration
        # gate remains evaluable, and the absence is visible in the report.
        result.setdefault("challenger_better", False)
    return result


def _safety_pass(data: dict[str, Any]) -> bool:
    checks = data.get("checks", data)
    return (
        bool(data.get("pass", True)) and all(bool(value) for value in checks.values())
        if checks
        else bool(data.get("pass", True))
    )


class EvaluationService:
    def __init__(self, session: Session):
        self.session = session

    def evaluate(self, request: EvaluationRequest) -> EvaluationReportView:
        request_hash = request_fingerprint({"service": "evaluation"}, request)
        existing = idempotent_row(
            self.session, EvaluationReportRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return EvaluationReportView.model_validate(existing)
        dataset = self.session.get(LearningDatasetRow, request.dataset_id)
        if dataset is None:
            raise LookupError(f"learning dataset {request.dataset_id} was not found")
        if dataset.status != "immutable":
            raise ValueError("evaluation requires an immutable learning dataset")
        item_count = (
            self.session.query(LearningDatasetItemRow)
            .filter(LearningDatasetItemRow.dataset_id == dataset.id)
            .count()
        )
        if item_count != len(request.labels) or dataset.row_count != item_count:
            raise ValueError("evaluation labels do not match dataset rows")
        if dataset.label_counts_json.get("success", 0) != sum(request.labels):
            raise ValueError("evaluation labels do not match dataset success labels")
        validation_items = list(
            self.session.query(LearningDatasetItemRow)
            .filter(LearningDatasetItemRow.dataset_id == dataset.id)
            .order_by(
                LearningDatasetItemRow.observation_cutoff,
                LearningDatasetItemRow.observation_id,
            )
        )
        expected_labels = [item.label == "success" for item in validation_items]
        if list(request.labels) != expected_labels:
            raise ValueError("evaluation label order does not match immutable dataset items")
        if any(
            not request.validation_start <= aware(item.observation_cutoff) <= request.validation_end
            for item in validation_items
        ):
            raise ValueError("dataset observations are outside the out-of-time validation window")
        baseline = calibration_metrics(request.baseline_predictions, request.labels, request.bins)
        challenger = calibration_metrics(
            request.challenger_predictions, request.labels, request.bins
        )
        slice_reports: list[dict[str, Any]] = []
        for item in request.slices:
            predictions = item.get("predictions", request.challenger_predictions)
            labels = item.get("labels", request.labels)
            if len(predictions) != len(labels) or not labels:
                slice_reports.append(
                    {
                        "name": item.get("name", "unknown"),
                        "status": "insufficient_data",
                        "sample_count": len(labels),
                    }
                )
                continue
            metrics = calibration_metrics(predictions, labels, request.bins)
            slice_reports.append({"name": item.get("name", "unknown"), **metrics})
        economic = _economic_metrics(request.economic)
        if not request.economic:
            economic["challenger_better"] = False
        safety = dict(request.safety)
        safety["passed"] = bool(request.safety) and _safety_pass(safety)
        insufficient_slice = any(
            item.get("status") == "insufficient_data" for item in slice_reports
        )
        brier_better = challenger["brier_score"] <= baseline["brier_score"]
        ece_better = challenger["ece"] <= baseline["ece"]
        strictly_better = (
            challenger["brier_score"] < baseline["brier_score"]
            or challenger["ece"] < baseline["ece"]
        )
        eligible = bool(
            brier_better
            and ece_better
            and strictly_better
            and economic["challenger_better"]
            and safety["passed"]
            and not insufficient_slice
        )
        row = EvaluationReportRow(
            id=new_id(),
            dataset_id=request.dataset_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            evaluated_at=request.evaluated_at,
            model_name=request.model_name,
            sample_count=len(request.labels),
            baseline_json=baseline,
            challenger_json=challenger,
            slices_json=slice_reports,
            economic_json=economic,
            safety_json=safety,
            eligible=eligible,
            status="eligible" if eligible else "not_eligible",
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return EvaluationReportView.model_validate(row)

    assess = evaluate

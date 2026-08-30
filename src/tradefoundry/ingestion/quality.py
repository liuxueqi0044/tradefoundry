from __future__ import annotations

from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.contracts import QualityResult, QualityThresholds, RunStatus
from tradefoundry.ingestion.models import (
    DataQualityAlertRow,
    FetchRunRow,
    QualityAssessmentRow,
)


class QualityService:
    def __init__(self, session: Session):
        self.session = session

    def assess(
        self, run: FetchRunRow, configured: dict | None = None, *, persist: bool = True
    ) -> QualityResult:
        if persist:
            existing = self.session.scalar(
                select(QualityAssessmentRow).where(QualityAssessmentRow.fetch_run_id == run.id)
            )
            if existing:
                return QualityResult(
                    score=existing.score,
                    status=existing.status,
                    anomalies=existing.anomalies,
                    metrics=existing.metrics,
                )
        thresholds = QualityThresholds.model_validate(configured or {})
        metrics = dict(run.metrics or {})
        records = int(metrics.get("records_seen", 0))
        duplicates = int(metrics.get("duplicate_records", 0))
        drift = float(metrics.get("max_time_drift_hours", 0))
        previous_metrics = self._previous_metrics(run)
        previous_count = int(previous_metrics.get("records_seen", 0)) if previous_metrics else None
        failures = self._consecutive_failures_before(run) + (
            1 if run.status == RunStatus.FAILED.value else 0
        )
        anomalies: list[str] = []

        if records < thresholds.minimum_records:
            anomalies.append("empty_or_below_minimum")
        if previous_count and records < previous_count * (1 - thresholds.maximum_drop_ratio):
            anomalies.append("record_count_drop")
        duplicate_ratio = duplicates / records if records else 0
        if duplicate_ratio > thresholds.maximum_duplicate_ratio:
            anomalies.append("duplicate_surge")
        field_drops = self._field_drops(
            previous_metrics or {}, metrics, thresholds.maximum_field_drop_ratio
        )
        if field_drops:
            anomalies.append("field_presence_drop")
        if drift > thresholds.maximum_time_drift_hours:
            anomalies.append("time_drift")
        if failures >= thresholds.maximum_consecutive_failures:
            anomalies.append("repeated_failures")

        weights = {
            "empty_or_below_minimum": 40,
            "record_count_drop": 25,
            "duplicate_surge": 15,
            "field_presence_drop": 20,
            "time_drift": 10,
            "repeated_failures": 30,
        }
        score = max(0, 100 - sum(weights[item] for item in anomalies))
        status = "healthy" if score >= 90 else "warning" if score >= 60 else "critical"
        result = QualityResult(
            score=score,
            status=status,
            anomalies=anomalies,
            metrics={
                **metrics,
                "previous_record_count": previous_count,
                "duplicate_ratio": duplicate_ratio,
                "consecutive_failures_before_run": failures,
                "dropped_fields": field_drops,
            },
        )
        if persist:
            assessment = QualityAssessmentRow(
                id=str(uuid4()),
                source_id=run.source_id,
                fetch_run_id=run.id,
                score=result.score,
                status=result.status,
                anomalies=result.anomalies,
                metrics=result.metrics,
            )
            self.session.add(assessment)
            for anomaly in result.anomalies:
                self.session.add(
                    DataQualityAlertRow(
                        id=str(uuid4()),
                        source_id=run.source_id,
                        fetch_run_id=run.id,
                        anomaly_code=anomaly,
                        severity="critical" if result.status == "critical" else "warning",
                        details_json=result.metrics,
                    )
                )
            self.session.commit()
        return result

    def latest(self, source_id: str) -> QualityAssessmentRow | None:
        return self.session.scalar(
            select(QualityAssessmentRow)
            .where(QualityAssessmentRow.source_id == source_id)
            .order_by(desc(QualityAssessmentRow.created_at))
            .limit(1)
        )

    def _previous_metrics(self, run: FetchRunRow) -> dict | None:
        prior = self.session.scalar(
            select(FetchRunRow)
            .where(
                FetchRunRow.source_id == run.source_id,
                FetchRunRow.status == RunStatus.SUCCEEDED.value,
                FetchRunRow.finished_at < run.finished_at,
            )
            .order_by(desc(FetchRunRow.finished_at))
            .limit(1)
        )
        return dict(prior.metrics or {}) if prior else None

    @staticmethod
    def _field_drops(previous: dict, current: dict, maximum_drop_ratio: float) -> list[str]:
        previous_records = int(previous.get("records_seen", 0))
        current_records = int(current.get("records_seen", 0))
        if not previous_records or not current_records:
            return []
        previous_fields = previous.get("field_counts", {})
        current_fields = current.get("field_counts", {})
        dropped = []
        for field, old_count in previous_fields.items():
            old_ratio = old_count / previous_records
            new_ratio = current_fields.get(field, 0) / current_records
            if old_ratio >= 0.5 and new_ratio < old_ratio * (1 - maximum_drop_ratio):
                dropped.append(field)
        return sorted(dropped)

    def _consecutive_failures_before(self, run: FetchRunRow) -> int:
        rows = self.session.scalars(
            select(FetchRunRow)
            .where(
                FetchRunRow.source_id == run.source_id,
                FetchRunRow.requested_at < run.requested_at,
            )
            .order_by(desc(FetchRunRow.requested_at))
            .limit(20)
        ).all()
        count = 0
        for row in rows:
            if row.status != RunStatus.FAILED.value:
                break
            count += 1
        return count

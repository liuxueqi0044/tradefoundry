from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.models import (
    ChangeEventRow,
    DataQualityAlertRow,
    QualityAssessmentRow,
    QuarantineRow,
    ReplayBatchRow,
    SourceRecordRow,
)


class IngestionQueryService:
    def __init__(self, session: Session):
        self.session = session

    def changes(self, source_id: str, limit: int = 100):
        return self.session.scalars(
            select(ChangeEventRow)
            .where(ChangeEventRow.source_id == source_id)
            .order_by(desc(ChangeEventRow.created_at))
            .limit(limit)
        ).all()

    def quarantine(self, source_id: str, limit: int = 100):
        return self.session.scalars(
            select(QuarantineRow)
            .where(QuarantineRow.source_id == source_id)
            .order_by(desc(QuarantineRow.created_at))
            .limit(limit)
        ).all()

    def current_records(self, source_id: str, limit: int = 100):
        return self.session.scalars(
            select(SourceRecordRow)
            .where(
                SourceRecordRow.source_id == source_id,
                SourceRecordRow.is_current.is_(True),
            )
            .order_by(SourceRecordRow.external_id)
            .limit(limit)
        ).all()

    def quality(self, source_id: str, limit: int = 50):
        return self.session.scalars(
            select(QualityAssessmentRow)
            .where(QualityAssessmentRow.source_id == source_id)
            .order_by(desc(QualityAssessmentRow.created_at))
            .limit(limit)
        ).all()

    def replays(self, source_id: str, limit: int = 50):
        return self.session.scalars(
            select(ReplayBatchRow)
            .where(ReplayBatchRow.source_id == source_id)
            .order_by(desc(ReplayBatchRow.created_at))
            .limit(limit)
        ).all()

    def alerts(self, source_id: str, limit: int = 100):
        return self.session.scalars(
            select(DataQualityAlertRow)
            .where(DataQualityAlertRow.source_id == source_id)
            .order_by(desc(DataQualityAlertRow.created_at))
            .limit(limit)
        ).all()

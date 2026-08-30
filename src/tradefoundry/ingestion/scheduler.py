from __future__ import annotations

from datetime import UTC, datetime, timedelta

from croniter import croniter
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.contracts import FetchRunCreate, FetchRunView, TimeWindow
from tradefoundry.ingestion.models import FetchRunRow, SourceRow, SourceVersionRow
from tradefoundry.ingestion.runs import FetchRunService


class SchedulerService:
    """Database-backed due calculation; a cron process can call enqueue_due safely."""

    def __init__(self, session: Session):
        self.session = session

    def enqueue_due(self, now: datetime | None = None) -> list[FetchRunView]:
        now = now or datetime.now(UTC)
        queued: list[FetchRunView] = []
        sources = self.session.scalars(
            select(SourceRow).where(SourceRow.active.is_(True)).order_by(SourceRow.key)
        ).all()
        for source in sources:
            version = self.session.scalar(
                select(SourceVersionRow).where(
                    SourceVersionRow.source_id == source.id,
                    SourceVersionRow.version_no == source.current_version,
                )
            )
            if version is None or not version.schedule_cron:
                continue
            last = self.session.scalar(
                select(FetchRunRow)
                .where(FetchRunRow.source_id == source.id)
                .order_by(desc(FetchRunRow.requested_at))
                .limit(1)
            )
            if last:
                next_due = croniter(version.schedule_cron, self._aware(last.requested_at)).get_next(
                    datetime
                )
                start = self._aware(last.window_end)
                if self._aware(next_due) > now or start >= now:
                    continue
            else:
                start = now - timedelta(hours=version.sla_hours or 24)
            queued.append(
                FetchRunService(self.session).create(
                    FetchRunCreate(source_id=source.id, window=TimeWindow(start=start, end=now))
                )
            )
        return queued

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

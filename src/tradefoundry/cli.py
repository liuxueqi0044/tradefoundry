import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from tradefoundry.config import get_settings
from tradefoundry.db import SessionLocal, create_all
from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.contracts import FetchRunCreate, SourceCreate, SourceKind, TimeWindow
from tradefoundry.ingestion.registry import SourceRegistry
from tradefoundry.ingestion.runs import FetchRunService, IngestionOrchestrator
from tradefoundry.ingestion.scheduler import SchedulerService
from tradefoundry.ingestion.worker import run_worker_once

app = typer.Typer(no_args_is_help=True)


@app.command("init-db")
def init_db() -> None:
    create_all()
    typer.echo("database initialized")


@app.command("enqueue-due")
def enqueue_due() -> None:
    with SessionLocal() as session:
        runs = SchedulerService(session).enqueue_due()
        for run in runs:
            typer.echo(run.id)


@app.command("worker-once")
def worker_once() -> None:
    with SessionLocal() as session:
        results = run_worker_once(
            session, FileSystemArtifactStore(Path(get_settings().artifact_root))
        )
        for result in results:
            typer.echo(f"{result.id} {result.status.value}")


@app.command("worker")
def worker(poll_seconds: int = typer.Option(default=30, min=1, max=3600)) -> None:
    store = FileSystemArtifactStore(Path(get_settings().artifact_root))
    while True:
        with SessionLocal() as session:
            results = run_worker_once(session, store)
            for result in results:
                typer.echo(f"{result.id} {result.status.value}")
        time.sleep(poll_seconds)


@app.command("execute")
def execute(run_id: str) -> None:
    with SessionLocal() as session:
        store = FileSystemArtifactStore(Path(get_settings().artifact_root))
        run = IngestionOrchestrator(session, store).execute(run_id)
        typer.echo(run.model_dump_json(indent=2))


@app.command("demo")
def demo() -> None:
    """Run a deterministic two-page ingestion without external network calls."""
    create_all()
    now = datetime.now(UTC)
    with SessionLocal() as session:
        registry = SourceRegistry(session)
        source = registry.create(
            SourceCreate(
                key=f"demo-{int(now.timestamp())}",
                name="Board one deterministic demo",
                kind=SourceKind.MEMORY,
                owner="local-operator",
                access_method="embedded test fixture",
                schedule_cron="0 * * * *",
                sla_hours=24,
                license_name="Internal fixture",
                license_url="https://example.invalid/license",
                terms_checked_at=now,
                commercial_use_allowed=True,
                retention_allowed=True,
                redistribution_allowed=False,
                connector_config={
                    "pages": [
                        [{"id": "notice-1", "title": "Medical gloves"}],
                        [{"id": "notice-2", "title": "Water pumps"}],
                    ]
                },
            )
        )
        source = registry.activate(source.id)
        run = FetchRunService(session).create(
            FetchRunCreate(
                source_id=source.id,
                window=TimeWindow(start=now - timedelta(days=1), end=now),
            )
        )
        result = IngestionOrchestrator(
            session, FileSystemArtifactStore(Path(get_settings().artifact_root))
        ).execute(run.id)
        typer.echo(result.model_dump_json(indent=2))

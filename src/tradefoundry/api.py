from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from tradefoundry.bilateral.api import router as bilateral_router
from tradefoundry.config import get_settings
from tradefoundry.db import get_session
from tradefoundry.deals.api import router as deals_router
from tradefoundry.evidence.api import router as evidence_router
from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.contracts import (
    FetchRunCreate,
    FetchRunView,
    ReplayReport,
    ReplayRequest,
    SourceCreate,
    SourceVersionCreate,
    SourceVersionView,
    SourceView,
)
from tradefoundry.ingestion.queries import IngestionQueryService
from tradefoundry.ingestion.registry import (
    SourceActivationError,
    SourceNotFoundError,
    SourceRegistry,
)
from tradefoundry.ingestion.replay import ReplayService
from tradefoundry.ingestion.runs import (
    FetchRunService,
    IngestionOrchestrator,
    InvalidRunTransition,
    RunNotFoundError,
)
from tradefoundry.ingestion.scheduler import SchedulerService
from tradefoundry.master.api import router as master_router
from tradefoundry.opportunity.api import router as opportunity_router
from tradefoundry.tradealpha.api import router as tradealpha_router

app = FastAPI(title="TradeFoundry", version="0.1.0")
app.include_router(evidence_router)
app.include_router(master_router)
app.include_router(opportunity_router)
app.include_router(deals_router)
app.include_router(tradealpha_router)
app.include_router(bilateral_router)


def _artifact_store() -> FileSystemArtifactStore:
    return FileSystemArtifactStore(Path(get_settings().artifact_root))


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (SourceNotFoundError, RunNotFoundError, LookupError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (SourceActivationError, InvalidRunTransition, ValueError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _rows(rows):
    return [
        {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}
        for row in rows
    ]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/sources", response_model=SourceView, status_code=201)
def create_source(request: SourceCreate, session: Session = Depends(get_session)):
    try:
        return SourceRegistry(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get("/v1/sources", response_model=list[SourceView])
def list_sources(session: Session = Depends(get_session)):
    return SourceRegistry(session).list()


@app.get("/v1/sources/{source_id}", response_model=SourceView)
def get_source(source_id: str, session: Session = Depends(get_session)):
    try:
        return SourceRegistry(session).get(source_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/sources/{source_id}/versions", response_model=SourceView, status_code=201)
def add_source_version(
    source_id: str, request: SourceVersionCreate, session: Session = Depends(get_session)
):
    try:
        return SourceRegistry(session).add_version(source_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get("/v1/sources/{source_id}/versions", response_model=list[SourceVersionView])
def list_source_versions(source_id: str, session: Session = Depends(get_session)):
    try:
        return SourceRegistry(session).versions(source_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/sources/{source_id}/activate", response_model=SourceView)
def activate_source(source_id: str, session: Session = Depends(get_session)):
    try:
        return SourceRegistry(session).activate(source_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/sources/{source_id}/deactivate", response_model=SourceView)
def deactivate_source(source_id: str, session: Session = Depends(get_session)):
    try:
        return SourceRegistry(session).deactivate(source_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/runs", response_model=FetchRunView, status_code=201)
def create_run(request: FetchRunCreate, session: Session = Depends(get_session)):
    try:
        return FetchRunService(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get("/v1/runs/{run_id}", response_model=FetchRunView)
def get_run(run_id: str, session: Session = Depends(get_session)):
    try:
        return FetchRunService(session).get(run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/runs/{run_id}/execute", response_model=FetchRunView)
def execute_run(run_id: str, session: Session = Depends(get_session)):
    try:
        return IngestionOrchestrator(session, _artifact_store()).execute(run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/runs/{run_id}/pause", response_model=FetchRunView)
def pause_run(run_id: str, session: Session = Depends(get_session)):
    try:
        return FetchRunService(session).pause(run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/runs/{run_id}/resume", response_model=FetchRunView)
def resume_run(run_id: str, session: Session = Depends(get_session)):
    try:
        return FetchRunService(session).resume(run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/runs/{run_id}/cancel", response_model=FetchRunView)
def cancel_run(run_id: str, session: Session = Depends(get_session)):
    try:
        return FetchRunService(session).cancel(run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/runs/{run_id}/rerun", response_model=FetchRunView, status_code=201)
def rerun(run_id: str, session: Session = Depends(get_session)):
    try:
        return FetchRunService(session).rerun(run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/runs/{run_id}/retry", response_model=FetchRunView, status_code=201)
def retry(run_id: str, session: Session = Depends(get_session)):
    try:
        return FetchRunService(session).retry(run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/scheduler/enqueue-due", response_model=list[FetchRunView])
def enqueue_due(session: Session = Depends(get_session)):
    try:
        return SchedulerService(session).enqueue_due()
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/v1/replays", response_model=ReplayReport, status_code=201)
def replay(request: ReplayRequest, session: Session = Depends(get_session)):
    try:
        return ReplayService(session, _artifact_store()).replay(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get("/v1/sources/{source_id}/changes")
def changes(
    source_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    return _rows(IngestionQueryService(session).changes(source_id, limit))


@app.get("/v1/sources/{source_id}/quarantine")
def quarantine(
    source_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    return _rows(IngestionQueryService(session).quarantine(source_id, limit))


@app.get("/v1/sources/{source_id}/records")
def records(
    source_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    return _rows(IngestionQueryService(session).current_records(source_id, limit))


@app.get("/v1/sources/{source_id}/quality")
def quality(
    source_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    return _rows(IngestionQueryService(session).quality(source_id, limit))


@app.get("/v1/sources/{source_id}/alerts")
def alerts(
    source_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    return _rows(IngestionQueryService(session).alerts(source_id, limit))

"""Board 9 execution-to-learning closure API.

External ERP dispatch is intentionally absent from the default runtime. The API
can queue an intent, but a separately configured operator must inject the live
ERP transport after Board 8 authorization.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from tradefoundry.controltower.governance import ExecutionTokenService
from tradefoundry.db import get_session
from tradefoundry.execution.adapters import (
    Board8MoneyNormalizationAdapter,
    DealsCollectionPublisher,
)
from tradefoundry.execution.contracts_learning import (
    DashboardSnapshotRequest,
    DashboardSnapshotView,
    EvaluationReportView,
    EvaluationRequest,
    LearningDatasetBuildRequest,
    LearningDatasetItemView,
    LearningDatasetView,
    OutcomeBuildRequest,
    OutcomeView,
    PredictionActualRequest,
    PredictionActualView,
    ReviewProposalRequest,
    ReviewProposalView,
)
from tradefoundry.execution.contracts_orders import (
    ErpOrderEvent,
    ErpResource,
    MilestoneRecord,
    OrderCommand,
    ShipmentDocument,
)
from tradefoundry.execution.contracts_settlement import (
    ActualCostCreate,
    BankReconciliation,
    InvoiceRefCreate,
    PaymentAllocationCreate,
    PaymentRefCreate,
    PnlSnapshotCreate,
    QualityCaseCreate,
    QualityClose,
    QualityEventCreate,
)
from tradefoundry.execution.dashboard import DashboardService
from tradefoundry.execution.documents import ShipmentDocumentService
from tradefoundry.execution.erp import ErpMappingService, RecordingErpGateway
from tradefoundry.execution.evaluation import EvaluationService
from tradefoundry.execution.fulfillment import FulfillmentService
from tradefoundry.execution.learning import (
    LearningDatasetService,
    OutcomeBuilder,
    PredictionActualService,
)
from tradefoundry.execution.orders import OrderReconciliationService, OrderService
from tradefoundry.execution.pnl import PnlService
from tradefoundry.execution.ports import ControlTowerTokenGuard
from tradefoundry.execution.quality import QualityCaseService
from tradefoundry.execution.reviews import ReviewProposalService
from tradefoundry.execution.settlement import (
    InvoiceSettlementService,
    PaymentSettlementService,
)

router = APIRouter(prefix="/v1/execution", tags=["execution-learning"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _row(row) -> dict:
    return {
        column.key: getattr(row, column.key)
        for column in inspect(row).mapper.column_attrs
    }


@router.post("/erp/resources", status_code=202)
def queue_erp_resource(request: ErpResource, session: Session = Depends(get_session)):
    """Queue a provider-neutral intent; this endpoint never performs a live effect."""
    try:
        return _row(ErpMappingService(session, RecordingErpGateway()).queue(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/erp/order-events", status_code=201)
def ingest_erp_order_event(request: ErpOrderEvent, session: Session = Depends(get_session)):
    try:
        return _row(OrderReconciliationService(session).ingest(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/orders", status_code=202)
def issue_order(request: OrderCommand, session: Session = Depends(get_session)):
    try:
        guard = ControlTowerTokenGuard(ExecutionTokenService(session))
        return _row(OrderService(session, guard).issue(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/milestones", status_code=201)
def record_milestone(request: MilestoneRecord, session: Session = Depends(get_session)):
    try:
        return _row(FulfillmentService(session).record(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/shipment-documents", status_code=201)
def add_shipment_document(
    request: ShipmentDocument, session: Session = Depends(get_session)
):
    try:
        return _row(ShipmentDocumentService(session).add(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/shipments/{shipment_id}/document-issues")
def validate_shipment_documents(
    shipment_id: str, session: Session = Depends(get_session)
):
    try:
        return [_row(row) for row in ShipmentDocumentService(session).validate(shipment_id)]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/shipment-documents/{document_id}")
def shipment_document(
    document_id: str,
    session: Session = Depends(get_session),
):
    try:
        # This public boundary is always redacted. A production identity adapter
        # may call the service with server-derived roles; query flags are not auth.
        return ShipmentDocumentService(session).view(document_id, roles=set())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/invoices", status_code=201)
def record_invoice(request: InvoiceRefCreate, session: Session = Depends(get_session)):
    try:
        return _row(
            InvoiceSettlementService(session, Board8MoneyNormalizationAdapter(session))
            .record_invoice(request)
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/orders/{order_id}/invoice-reconciliation")
def reconcile_invoices(
    order_id: str,
    order_amount: str,
    currency: str,
    session: Session = Depends(get_session),
):
    try:
        return InvoiceSettlementService(
            session, Board8MoneyNormalizationAdapter(session)
        ).reconcile_order(order_id, order_amount, currency)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/payments", status_code=201)
def record_payment(request: PaymentRefCreate, session: Session = Depends(get_session)):
    try:
        return _row(
            PaymentSettlementService(session, Board8MoneyNormalizationAdapter(session))
            .record_payment(request)
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/payment-allocations", status_code=201)
def allocate_payment(
    request: PaymentAllocationCreate, session: Session = Depends(get_session)
):
    try:
        return _row(
            PaymentSettlementService(session, Board8MoneyNormalizationAdapter(session))
            .allocate(request)
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/bank-reconciliations")
def reconcile_bank(request: BankReconciliation, session: Session = Depends(get_session)):
    try:
        return _row(PaymentSettlementService(session).reconcile_bank(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/orders/{order_id}/collection-signals")
def publish_collection(order_id: str, session: Session = Depends(get_session)):
    try:
        service = PaymentSettlementService(
            session,
            Board8MoneyNormalizationAdapter(session),
            DealsCollectionPublisher(session),
        )
        row = service.emit_collection_signal(order_id)
        if row is None:
            raise ValueError("fully allocated, bank-reconciled sales invoices are required")
        return _row(row)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/quality-cases", status_code=201)
def open_quality_case(request: QualityCaseCreate, session: Session = Depends(get_session)):
    try:
        return _row(QualityCaseService(session).open_case(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/quality-events", status_code=201)
def append_quality_event(
    request: QualityEventCreate, session: Session = Depends(get_session)
):
    try:
        return _row(QualityCaseService(session).append_event(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/quality-case-closures")
def close_quality_case(request: QualityClose, session: Session = Depends(get_session)):
    try:
        return _row(QualityCaseService(session).close_case(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/actual-costs", status_code=201)
def record_actual_cost(request: ActualCostCreate, session: Session = Depends(get_session)):
    try:
        return _row(
            PnlService(session, Board8MoneyNormalizationAdapter(session))
            .record_actual_cost(request)
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/pnl-snapshots", status_code=201)
def create_pnl_snapshot(request: PnlSnapshotCreate, session: Session = Depends(get_session)):
    try:
        return _row(PnlService(session, Board8MoneyNormalizationAdapter(session)).snapshot(request))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/outcomes", response_model=OutcomeView, status_code=201)
def build_outcome(request: OutcomeBuildRequest, session: Session = Depends(get_session)):
    try:
        return OutcomeBuilder(session).build(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/prediction-actuals", response_model=PredictionActualView, status_code=201)
def compare_prediction(
    request: PredictionActualRequest, session: Session = Depends(get_session)
):
    try:
        return PredictionActualService(session).compare(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/learning-datasets", response_model=LearningDatasetView, status_code=201)
def build_learning_dataset(
    request: LearningDatasetBuildRequest, session: Session = Depends(get_session)
):
    try:
        return LearningDatasetService(session).build(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/learning-datasets/{dataset_id}/items",
    response_model=list[LearningDatasetItemView],
)
def learning_dataset_items(dataset_id: str, session: Session = Depends(get_session)):
    return LearningDatasetService(session).items(dataset_id)


@router.post("/evaluations", response_model=EvaluationReportView, status_code=201)
def evaluate_challenger(request: EvaluationRequest, session: Session = Depends(get_session)):
    try:
        return EvaluationService(session).evaluate(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/review-proposals", response_model=ReviewProposalView, status_code=201)
def propose_review(
    request: ReviewProposalRequest, session: Session = Depends(get_session)
):
    try:
        return ReviewProposalService(session).propose(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/review-proposals", response_model=list[ReviewProposalView])
def pending_reviews(session: Session = Depends(get_session)):
    return ReviewProposalService(session).list_pending()


@router.post(
    "/dashboard-snapshots", response_model=DashboardSnapshotView, status_code=201
)
def snapshot_dashboard(
    request: DashboardSnapshotRequest, session: Session = Depends(get_session)
):
    try:
        return DashboardService(session).snapshot(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/dashboard-snapshots/{snapshot_key}", response_model=DashboardSnapshotView)
def latest_dashboard(
    snapshot_key: str,
    version: str = Query(default="v1"),
    session: Session = Depends(get_session),
):
    try:
        return DashboardService(session).latest(snapshot_key, version)
    except Exception as exc:
        raise _http_error(exc) from exc

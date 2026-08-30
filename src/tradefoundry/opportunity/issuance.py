from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.opportunity.contracts import IssuanceRequest, IssuanceView
from tradefoundry.opportunity.models import (
    DealCellIssuanceRow,
    HypothesisAuditRow,
    OpportunityTemplateRow,
    TradeHypothesisRow,
)


class DealCellIssuanceService:
    def __init__(self, session: Session):
        self.session = session

    def issue(self, hypothesis_id: str, request: IssuanceRequest) -> IssuanceView:
        request_hash = payload_hash(
            {"hypothesis_id": hypothesis_id, **request.model_dump(mode="json")}
        )
        existing_key = self.session.scalar(
            select(DealCellIssuanceRow).where(
                DealCellIssuanceRow.idempotency_key == request.idempotency_key
            )
        )
        if existing_key is not None:
            if existing_key.request_hash != request_hash:
                raise ValueError("issuance idempotency key was reused with a different payload")
            return IssuanceView.model_validate(existing_key)
        hypothesis = self.session.get(TradeHypothesisRow, hypothesis_id)
        if hypothesis is None:
            raise LookupError(f"trade hypothesis {hypothesis_id} not found")
        existing_ready = self.session.scalar(
            select(DealCellIssuanceRow).where(
                DealCellIssuanceRow.hypothesis_id == hypothesis_id,
                DealCellIssuanceRow.command_status == "ready",
            )
        )
        if existing_ready is not None:
            return IssuanceView.model_validate(existing_ready)
        latest_audit = self.session.scalar(
            select(HypothesisAuditRow)
            .where(HypothesisAuditRow.hypothesis_id == hypothesis_id)
            .order_by(HypothesisAuditRow.created_at.desc(), HypothesisAuditRow.id.desc())
            .limit(1)
        )
        if (
            hypothesis.audit_status != "pass"
            or latest_audit is None
            or latest_audit.decision != "pass"
        ):
            status = "denied"
            rejection = (
                "Hypothesis has not passed its latest audit; current status is "
                f"{hypothesis.audit_status}."
            )
            deal_cell_key = None
            payload = {}
        else:
            template = self.session.get(OpportunityTemplateRow, hypothesis.template_id)
            if template is None:
                raise RuntimeError(f"template {hypothesis.template_id} is missing")
            status = "ready"
            rejection = None
            deal_cell_key = f"hypothesis:{hypothesis.id}"
            payload = {
                "contract_version": "deal-cell-create-command-v1",
                "deal_cell_key": deal_cell_key,
                "hypothesis_id": hypothesis.id,
                "event_ids": hypothesis.event_ids_json,
                "route_candidate_ids": hypothesis.route_candidate_ids_json,
                "template": {
                    "id": template.id,
                    "key": template.template_key,
                    "version": template.version_no,
                },
                "compiler_version": hypothesis.compiler_version,
                "audit": {
                    "id": latest_audit.id,
                    "auditor_version": latest_audit.auditor_version,
                    "policy_version": latest_audit.policy_version,
                },
            }
        row = DealCellIssuanceRow(
            id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            hypothesis_id=hypothesis_id,
            command_status=status,
            deal_cell_key=deal_cell_key,
            payload_json=payload,
            rejection_reason=rejection,
            requested_by=request.requested_by,
            correlation_id=request.correlation_id,
        )
        self.session.add(row)
        self.session.commit()
        return IssuanceView.model_validate(row)

    def get(self, issuance_id: str) -> IssuanceView:
        row = self.session.get(DealCellIssuanceRow, issuance_id)
        if row is None:
            raise LookupError(f"Deal Cell issuance command {issuance_id} not found")
        return IssuanceView.model_validate(row)

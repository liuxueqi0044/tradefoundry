from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from tradefoundry.controltower.common import (
    aware,
    idempotent_row,
    new_id,
    request_fingerprint,
    utcnow,
)
from tradefoundry.controltower.contracts import AuditExportCreate
from tradefoundry.controltower.models import (
    ApprovalDecisionRow,
    ApprovalRequestRow,
    ApprovalStepRow,
    AuditExportRow,
    CashflowEventRow,
    CashflowPlanRow,
    CommunicationDecisionRow,
    CreditAssessmentRow,
    CreditOverrideRow,
    ExecutionTokenRow,
    ExportControlAssessmentRow,
    FreezeReleaseRow,
    FreezeRow,
    LandedCostLineRow,
    LandedCostScenarioRow,
    PolicyDecisionRow,
    RiskCaseRow,
    ScreeningMatchRow,
    ScreeningRunRow,
    SensitivityRunRow,
    TradeRequirementAssessmentRow,
)
from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash

AUDITOR_ROLES = {"compliance_auditor", "internal_auditor", "regulator"}
SENSITIVE_KEYS = {
    "query_snapshot_json",
    "context_snapshot_json",
    "identifiers",
    "normalized_value_json",
    "params_json",
    "value_json",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _row(row: Any, *, full: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in inspect(row).mapper.column_attrs:
        key = column.key
        if key in {"token_hash", "request_hash"}:
            continue
        value = getattr(row, key)
        if not full and key in SENSITIVE_KEYS and value is not None:
            result[key] = {"redacted": True, "value_hash": payload_hash(_jsonable(value))}
        else:
            result[key] = _jsonable(value)
    return result


class AuditExportService:
    def __init__(self, session: Session):
        self.session = session

    def export(self, request: AuditExportCreate) -> AuditExportRow:
        request_hash = request_fingerprint({"operation": "risk.audit.export"}, request)
        existing = idempotent_row(
            self.session, AuditExportRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        refs = set(request.resource_refs)
        entity_ids = refs | {value.removeprefix("entity:") for value in refs}
        full = request.requester_role in AUDITOR_ROLES
        policy = [
            row
            for row in self.session.scalars(select(PolicyDecisionRow))
            if row.resource_id in refs and self._in_window(row.evaluated_at, request)
        ]
        approvals = [
            row
            for row in self.session.scalars(select(ApprovalRequestRow))
            if row.resource_id in refs and self._in_window(row.created_at, request)
        ]
        approval_ids = {row.id for row in approvals}
        steps = [
            row
            for row in self.session.scalars(select(ApprovalStepRow))
            if row.approval_request_id in approval_ids
        ]
        approval_decisions = [
            row
            for row in self.session.scalars(select(ApprovalDecisionRow))
            if row.approval_request_id in approval_ids
        ]
        tokens = [
            row
            for row in self.session.scalars(select(ExecutionTokenRow))
            if row.approval_request_id in approval_ids
        ]
        cases = [
            row
            for row in self.session.scalars(select(RiskCaseRow))
            if (
                row.source_reference in refs
                or bool(set(row.subject_refs_json) & refs)
                or bool(set(row.subject_refs_json) & entity_ids)
            )
            and self._in_window(row.opened_at, request)
        ]
        case_ids = {row.id for row in cases}
        freezes = [
            row
            for row in self.session.scalars(select(FreezeRow))
            if row.risk_case_id in case_ids or row.subject_ref in refs
        ]
        freeze_ids = {row.id for row in freezes}
        releases = [
            row
            for row in self.session.scalars(select(FreezeReleaseRow))
            if row.freeze_id in freeze_ids
        ]
        screenings = [
            row
            for row in self.session.scalars(select(ScreeningRunRow))
            if row.id in refs or row.entity_id in entity_ids
        ]
        screening_ids = {row.id for row in screenings}
        screening_matches = [
            row
            for row in self.session.scalars(select(ScreeningMatchRow))
            if row.screening_run_id in screening_ids
        ]
        landed = [
            row
            for row in self.session.scalars(select(LandedCostScenarioRow))
            if row.id in refs or row.route_id in refs or row.supplier_quote_id in refs
        ]
        landed_ids = {row.id for row in landed}
        landed_lines = [
            row
            for row in self.session.scalars(select(LandedCostLineRow))
            if row.scenario_id in landed_ids
        ]
        cashflows = [
            row
            for row in self.session.scalars(select(CashflowPlanRow))
            if row.id in refs or row.route_id in refs or row.scenario_id in landed_ids
        ]
        cashflow_ids = {row.id for row in cashflows}
        cashflow_events = [
            row
            for row in self.session.scalars(select(CashflowEventRow))
            if row.plan_id in cashflow_ids
        ]
        sensitivities = [
            row
            for row in self.session.scalars(select(SensitivityRunRow))
            if row.id in refs
            or row.route_id in refs
            or row.scenario_id in landed_ids
            or row.cashflow_plan_id in cashflow_ids
        ]
        credit = [
            row
            for row in self.session.scalars(select(CreditAssessmentRow))
            if row.id in refs or row.entity_id in entity_ids
        ]
        credit_ids = {row.id for row in credit}
        overrides = [
            row
            for row in self.session.scalars(select(CreditOverrideRow))
            if row.assessment_id in credit_ids
        ]
        export_controls = [
            row
            for row in self.session.scalars(select(ExportControlAssessmentRow))
            if row.id in refs or row.product_concept_id in refs or row.buyer_entity_id in entity_ids
        ]
        trade_requirements = [
            row
            for row in self.session.scalars(select(TradeRequirementAssessmentRow))
            if row.id in refs or row.product_concept_id in refs
        ]
        communications = [
            row
            for row in self.session.scalars(select(CommunicationDecisionRow))
            if row.id in refs or row.contact_id in refs
        ]
        claim_ids = {
            claim_id
            for collection in (approval_decisions, cases, releases, overrides)
            for row in collection
            for claim_id in getattr(row, "evidence_claim_ids_json", [])
        }
        claims = [row for row in self.session.scalars(select(ClaimRow)) if row.id in claim_ids]
        collections = {
            "policy_decisions": policy,
            "approval_requests": approvals,
            "approval_steps": steps,
            "approval_decisions": approval_decisions,
            "execution_tokens": tokens,
            "risk_cases": cases,
            "freezes": freezes,
            "freeze_releases": releases,
            "screening_runs": screenings,
            "screening_matches": screening_matches,
            "landed_cost_scenarios": landed,
            "landed_cost_lines": landed_lines,
            "cashflow_plans": cashflows,
            "cashflow_events": cashflow_events,
            "sensitivity_runs": sensitivities,
            "credit_assessments": credit,
            "credit_overrides": overrides,
            "export_control_assessments": export_controls,
            "trade_requirement_assessments": trade_requirements,
            "communication_decisions": communications,
            "evidence_claims": claims,
        }
        package = {
            "schema_version": "board8-audit-export-1.0",
            "generated_at": utcnow().isoformat(),
            "resource_refs": sorted(refs),
            "requested_by": request.requested_by,
            "requester_role": request.requester_role,
            "redaction_profile": "auditor_full" if full else "operational_redacted",
            "records": {
                key: [_row(row, full=full) for row in values] for key, values in collections.items()
            },
        }
        row = AuditExportRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            resource_refs_json=sorted(refs),
            from_time=request.from_time,
            to_time=request.to_time,
            requested_by=request.requested_by,
            requester_role=request.requester_role,
            redaction_profile=package["redaction_profile"],
            package_json=package,
            package_hash=payload_hash(package),
        )
        self.session.add(row)
        self.session.commit()
        return row

    @staticmethod
    def _in_window(value: datetime, request: AuditExportCreate) -> bool:
        timestamp = aware(value)
        if request.from_time and timestamp < aware(request.from_time):
            return False
        return not (request.to_time and timestamp > aware(request.to_time))

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.bilateral.common import (
    aware,
    idempotent_row,
    money,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.bilateral.contracts import (
    BuyerQuoteBuildRequest,
    ConstraintAssessmentRequest,
    MeetingImport,
    MeetingImportResult,
    NegotiationTermCreate,
)
from tradefoundry.bilateral.models import (
    BilateralTaskRow,
    BuyerQuoteVersionRow,
    ConstraintAssessmentRow,
    InteractionRow,
    MeetingImportRow,
    NegotiationTermVersionRow,
    QualificationSnapshotRow,
    SupplierQuoteRow,
)
from tradefoundry.bilateral.ports import CostScenarioPort
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.ingestion.models import utcnow


class ConstraintCoordinationService:
    def __init__(self, session: Session):
        self.session = session

    def assess(
        self, route_id: str, request: ConstraintAssessmentRequest
    ) -> ConstraintAssessmentRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        qualification = require_row(
            self.session,
            QualificationSnapshotRow,
            request.qualification_snapshot_id,
            "qualification snapshot",
        )
        if qualification.route_id != route_id:
            raise ValueError("qualification snapshot belongs to another route")
        request_hash = request_fingerprint(
            {"operation": "constraint.assess", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, ConstraintAssessmentRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        quotes = [
            require_row(self.session, SupplierQuoteRow, quote_id, "supplier quote")
            for quote_id in request.quote_ids
        ]
        if any(quote.route_id != route_id for quote in quotes):
            raise ValueError("all supplier quotes must belong to the route")
        matrix: list[dict] = []
        conflicts: list[dict] = []
        for quote in quotes:
            quote_matrix, quote_conflicts = _compare_constraints(qualification, quote)
            matrix.extend(quote_matrix)
            conflicts.extend(quote_conflicts)
        solutions = _candidate_solutions(conflicts)
        row = ConstraintAssessmentRow(
            id=new_id(),
            route_id=route_id,
            qualification_snapshot_id=qualification.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            quote_ids_json=request.quote_ids,
            matrix_json=matrix,
            conflicts_json=conflicts,
            candidate_solutions_json=solutions,
            route_reassessment_required=bool(conflicts),
        )
        self.session.add(row)
        self.session.commit()
        return row


class BuyerQuoteService:
    def __init__(self, session: Session, costs: CostScenarioPort):
        self.session = session
        self.costs = costs

    def build(self, route_id: str, request: BuyerQuoteBuildRequest) -> BuyerQuoteVersionRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        request_hash = request_fingerprint(
            {"operation": "buyer_quote.build", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, BuyerQuoteVersionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        if aware(request.valid_until) <= aware(utcnow()):
            raise ValueError("buyer quote valid_until must be in the future")
        scenario = self.costs.get(request.cost_scenario_ref)
        if scenario.reference != request.cost_scenario_ref:
            raise ValueError("cost service returned a mismatched scenario reference")
        version_no = (
            self.session.scalar(
                select(func.max(BuyerQuoteVersionRow.version_no)).where(
                    BuyerQuoteVersionRow.route_id == route_id,
                    BuyerQuoteVersionRow.quote_key == request.quote_key,
                )
            )
            or 0
        ) + 1
        selling_amount = money(scenario.total_cost / (Decimal("1") - request.margin_rate))
        assumptions = [
            *scenario.assumptions,
            "Selling amount uses gross-margin formula: total_cost / (1 - margin_rate).",
        ]
        if scenario.status == "estimated":
            assumptions.append(
                "Cost scenario is estimated and must be confirmed before commitment."
            )
        row = BuyerQuoteVersionRow(
            id=new_id(),
            route_id=route_id,
            quote_key=request.quote_key,
            version_no=version_no,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            cost_scenario_ref=scenario.reference,
            cost_scenario_hash=scenario.snapshot_hash,
            calculator_version=scenario.calculator_version,
            cost_status=scenario.status,
            cost_amount=scenario.total_cost,
            margin_rate=request.margin_rate,
            selling_amount=selling_amount,
            currency=scenario.currency,
            quantity=scenario.quantity,
            quantity_unit=scenario.quantity_unit,
            valid_until=request.valid_until,
            assumptions_json=assumptions,
            status="draft",
            approval_status="pending",
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return row


class NegotiationTermService:
    def __init__(self, session: Session):
        self.session = session

    def append(self, route_id: str, request: NegotiationTermCreate) -> NegotiationTermVersionRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        request_hash = request_fingerprint(
            {"operation": "negotiation.append", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, NegotiationTermVersionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        previous = self.session.scalar(
            select(NegotiationTermVersionRow)
            .where(
                NegotiationTermVersionRow.route_id == route_id,
                NegotiationTermVersionRow.term_key == request.term_key,
            )
            .order_by(NegotiationTermVersionRow.version_no.desc())
        )
        diff = _term_diff(previous.terms_json if previous else {}, request.terms)
        if previous is not None and not diff:
            raise ValueError("new negotiation version must change at least one term")
        violations = _floor_violations(request.terms, request.internal_floors)
        row = NegotiationTermVersionRow(
            id=new_id(),
            route_id=route_id,
            term_key=request.term_key,
            version_no=1 if previous is None else previous.version_no + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            terms_json=request.terms,
            diff_json=diff,
            floor_snapshot_hash=payload_hash(request.internal_floors),
            floor_violations_json=violations,
            approval_required=bool(violations),
            counterparty_ref=request.counterparty_ref,
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return row


class MeetingSyncService:
    def __init__(self, session: Session):
        self.session = session

    def import_meeting(self, route_id: str, request: MeetingImport) -> MeetingImportResult:
        require_row(self.session, DealRouteRow, route_id, "route")
        request_hash = request_fingerprint(
            {"operation": "meeting.import", "route_id": route_id}, request
        )
        existing = self.session.scalar(
            select(MeetingImportRow).where(MeetingImportRow.external_ref == request.external_ref)
        )
        external_message_id = f"meeting:{payload_hash(request.external_ref)}"
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("meeting external_ref was reused with different inputs")
            interaction = self.session.scalar(
                select(InteractionRow).where(
                    InteractionRow.external_message_id == external_message_id
                )
            )
            tasks = self.session.scalars(
                select(BilateralTaskRow).where(BilateralTaskRow.meeting_import_id == existing.id)
            ).all()
            return MeetingImportResult(
                meeting_import_id=existing.id,
                interaction_id=interaction.id,
                task_ids=[task.id for task in tasks],
                duplicate=True,
            )
        if any(item.due_at < request.occurred_at for item in request.action_items):
            raise ValueError("meeting action due_at cannot be before the meeting")
        meeting = MeetingImportRow(
            id=new_id(),
            route_id=route_id,
            external_ref=request.external_ref,
            request_hash=request_hash,
            raw_artifact_ref=request.raw_artifact_ref,
            summary=request.summary,
            occurred_at=request.occurred_at,
            imported_by=request.imported_by,
        )
        interaction = InteractionRow(
            id=new_id(),
            external_message_id=external_message_id,
            request_hash=payload_hash(
                {"meeting_request_hash": request_hash, "interaction_version": 1}
            ),
            route_id=route_id,
            contact_id=None,
            thread_key=request.external_ref,
            channel="meeting",
            direction="inbound",
            raw_artifact_ref=request.raw_artifact_ref,
            raw_hash=request.raw_hash,
            body_text=request.summary,
            metadata_json={"meeting_import_id": meeting.id},
            attachment_refs_json=[],
            link_method="meeting_explicit_route",
            link_confidence=1.0,
            status="linked",
            occurred_at=request.occurred_at,
        )
        tasks = [
            BilateralTaskRow(
                id=new_id(),
                meeting_import_id=meeting.id,
                route_id=route_id,
                task_key=item.task_key,
                owner=item.owner,
                description=item.description,
                due_at=item.due_at,
                status="proposed",
                action_proposal_json={
                    "action_type": "meeting_follow_up",
                    "description": item.description,
                    "owner": item.owner,
                    "due_at": item.due_at.isoformat(),
                    "external_side_effect": False,
                    "source_meeting_import_id": meeting.id,
                },
            )
            for item in request.action_items
        ]
        self.session.add_all([meeting, interaction, *tasks])
        self.session.commit()
        return MeetingImportResult(
            meeting_import_id=meeting.id,
            interaction_id=interaction.id,
            task_ids=[task.id for task in tasks],
            duplicate=False,
        )


def _qualification_value(field: dict | None):
    return field.get("value") if field else None


def _compare_constraints(qualification: QualificationSnapshotRow, quote: SupplierQuoteRow):
    matrix: list[dict] = []
    conflicts: list[dict] = []

    quantity = _qualification_value(qualification.quantity_json)
    if isinstance(quantity, dict):
        buyer_amount = quantity.get("amount")
        buyer_unit = quantity.get("unit")
        comparable = buyer_amount is not None and buyer_unit == quote.moq_unit
        status = "unknown"
        if comparable and quote.moq_quantity is not None:
            status = "conflict" if Decimal(str(buyer_amount)) < quote.moq_quantity else "satisfied"
        matrix.append(
            {
                "quote_id": quote.id,
                "constraint": "moq",
                "buyer": quantity,
                "supplier": {
                    "amount": str(quote.moq_quantity) if quote.moq_quantity is not None else None,
                    "unit": quote.moq_unit,
                },
                "status": status,
            }
        )
        if status == "conflict":
            conflicts.append(
                {
                    "quote_id": quote.id,
                    "type": "moq",
                    "buyer": quantity,
                    "supplier": str(quote.moq_quantity),
                }
            )

    timing = _qualification_value(qualification.timing_json)
    if isinstance(timing, dict) and timing.get("required_lead_time_days") is not None:
        buyer_days = int(timing["required_lead_time_days"])
        status = (
            "unknown"
            if quote.lead_time_days is None
            else ("conflict" if quote.lead_time_days > buyer_days else "satisfied")
        )
        matrix.append(
            {
                "quote_id": quote.id,
                "constraint": "lead_time",
                "buyer": buyer_days,
                "supplier": quote.lead_time_days,
                "status": status,
            }
        )
        if status == "conflict":
            conflicts.append(
                {
                    "quote_id": quote.id,
                    "type": "lead_time",
                    "buyer": buyer_days,
                    "supplier": quote.lead_time_days,
                }
            )

    specification = _qualification_value(qualification.specification_json)
    if isinstance(specification, dict):
        required_certifications = set(specification.get("certifications", []))
        offered_certifications = set(quote.specifications_json.get("certifications", []))
        if required_certifications:
            missing = sorted(required_certifications - offered_certifications)
            status = "conflict" if missing else "satisfied"
            matrix.append(
                {
                    "quote_id": quote.id,
                    "constraint": "certification",
                    "buyer": sorted(required_certifications),
                    "supplier": sorted(offered_certifications),
                    "status": status,
                }
            )
            if missing:
                conflicts.append(
                    {"quote_id": quote.id, "type": "certification", "missing": missing}
                )
        required_specs = specification.get("specifications", {})
        for key, expected in required_specs.items():
            actual = quote.specifications_json.get(key)
            status = "satisfied" if actual == expected else "conflict"
            matrix.append(
                {
                    "quote_id": quote.id,
                    "constraint": f"specification:{key}",
                    "buyer": expected,
                    "supplier": actual,
                    "status": status,
                }
            )
            if status == "conflict":
                conflicts.append(
                    {
                        "quote_id": quote.id,
                        "type": "specification",
                        "field": key,
                        "buyer": expected,
                        "supplier": actual,
                    }
                )

    procurement = _qualification_value(qualification.procurement_process_json)
    if isinstance(procurement, dict) and procurement.get("payment_terms"):
        expected = procurement["payment_terms"]
        status = "satisfied" if quote.payment_terms == expected else "conflict"
        matrix.append(
            {
                "quote_id": quote.id,
                "constraint": "payment_terms",
                "buyer": expected,
                "supplier": quote.payment_terms,
                "status": status,
            }
        )
        if status == "conflict":
            conflicts.append(
                {
                    "quote_id": quote.id,
                    "type": "payment_terms",
                    "buyer": expected,
                    "supplier": quote.payment_terms,
                }
            )
    return matrix, conflicts


def _candidate_solutions(conflicts: list[dict]) -> list[dict]:
    mappings = {
        "moq": ["aggregate_buyers", "switch_supplier", "negotiate_moq"],
        "lead_time": ["switch_supplier", "staged_delivery", "adjust_buyer_timing"],
        "certification": ["switch_supplier", "certification_plan", "adjust_requirement"],
        "payment_terms": ["negotiate_payment", "trade_finance", "switch_supplier"],
        "specification": ["adjust_specification", "switch_supplier", "engineering_review"],
    }
    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for conflict in conflicts:
        for action in mappings.get(conflict["type"], ["human_review"]):
            key = (conflict["type"], action)
            if key not in seen:
                seen.add(key)
                result.append(
                    {
                        "conflict_type": conflict["type"],
                        "action": action,
                        "status": "candidate_only",
                        "requires_human_decision": True,
                    }
                )
    return result


def _term_diff(previous: dict, current: dict) -> dict:
    result = {}
    for key in sorted(set(previous) | set(current)):
        if previous.get(key) != current.get(key):
            result[key] = {"from": previous.get(key), "to": current.get(key)}
    return result


def _floor_violations(terms: dict, floors: dict) -> list[dict]:
    violations: list[dict] = []
    for field, rule in floors.items():
        if not isinstance(rule, dict) or set(rule) != {"operator", "value"}:
            raise ValueError(f"internal floor {field} must contain exactly operator and value")
        operator = rule["operator"]
        if operator not in {"gte", "lte", "eq"}:
            raise ValueError(f"unsupported floor operator {operator}")
        if field not in terms:
            violations.append({"field": field, "reason": "term_missing", "operator": operator})
            continue
        actual, threshold = terms[field], rule["value"]
        if operator == "gte":
            passed = actual >= threshold
        elif operator == "lte":
            passed = actual <= threshold
        else:
            passed = actual == threshold
        if not passed:
            violations.append(
                {
                    "field": field,
                    "reason": "floor_breached",
                    "operator": operator,
                    "actual": actual,
                }
            )
    return violations

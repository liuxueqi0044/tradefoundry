from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.controltower.common import (
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.controltower.contracts import ExportControlCreate, TradeRequirementCreate
from tradefoundry.controltower.models import (
    ComplianceDatasetRow,
    ComplianceEntryRow,
    ExportControlAssessmentRow,
    TradeRequirementAssessmentRow,
)
from tradefoundry.master.models import EntityRow, ProductConceptRow


def _active_on(entry: ComplianceEntryRow, as_of: date) -> bool:
    return not (
        (entry.effective_from and entry.effective_from > as_of)
        or (entry.effective_to and entry.effective_to < as_of)
    )


def _matches_code(candidate: str, listed: str) -> bool:
    normalized_candidate = candidate.replace(".", "").replace(" ", "").upper()
    normalized_listed = listed.replace(".", "").replace(" ", "").upper()
    return normalized_candidate.startswith(normalized_listed) or normalized_listed.startswith(
        normalized_candidate
    )


def _matches_location(value: str, allowed: list[str] | None) -> bool:
    if not allowed:
        return True
    normalized = {item.upper() for item in allowed}
    return "*" in normalized or value.upper() in normalized


class _RuleDatasetMixin:
    session: Session

    def _dataset(self, dataset_id: str | None, dataset_type: str) -> ComplianceDatasetRow:
        if dataset_id:
            dataset = require_row(
                self.session, ComplianceDatasetRow, dataset_id, "compliance dataset"
            )
        else:
            dataset = self.session.scalar(
                select(ComplianceDatasetRow)
                .where(
                    ComplianceDatasetRow.dataset_type == dataset_type,
                    ComplianceDatasetRow.status == "active",
                )
                .order_by(ComplianceDatasetRow.published_at.desc())
            )
            if dataset is None:
                raise LookupError(f"active {dataset_type} dataset was not found")
        if dataset.status != "active" or dataset.dataset_type != dataset_type:
            raise ValueError(f"assessment requires an active {dataset_type} dataset")
        return dataset


class ExportControlService(_RuleDatasetMixin):
    def __init__(self, session: Session):
        self.session = session

    def assess(self, request: ExportControlCreate) -> ExportControlAssessmentRow:
        request_hash = request_fingerprint({"operation": "risk.export_control.assess"}, request)
        existing = idempotent_row(
            self.session, ExportControlAssessmentRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        require_row(self.session, ProductConceptRow, request.product_concept_id, "product")
        require_row(self.session, EntityRow, request.buyer_entity_id, "buyer entity")
        dataset = self._dataset(request.dataset_id, "export_controls")
        candidates: list[dict[str, Any]] = []
        for entry in self.session.scalars(
            select(ComplianceEntryRow).where(ComplianceEntryRow.dataset_id == dataset.id)
        ):
            if not _active_on(entry, request.as_of):
                continue
            listed_codes = entry.fields_json.get("product_codes") or []
            destinations = entry.fields_json.get("destinations") or []
            if not _matches_location(request.destination_country, destinations):
                continue
            matched_codes = [
                item.model_dump(mode="json")
                for item in request.product_code_candidates
                if any(_matches_code(item.code, listed) for listed in listed_codes)
            ]
            if not matched_codes:
                continue
            keywords = [
                value.casefold() for value in entry.fields_json.get("end_use_keywords") or []
            ]
            end_use_hit = bool(
                request.end_use
                and any(keyword in request.end_use.casefold() for keyword in keywords)
            )
            candidates.append(
                {
                    "entry_id": entry.id,
                    "external_id": entry.external_id,
                    "programs": entry.programs_json,
                    "matched_product_codes": matched_codes,
                    "end_use_keyword_hit": end_use_hit,
                    "restriction": entry.fields_json.get("restriction", "review"),
                    "effective_from": (
                        entry.effective_from.isoformat() if entry.effective_from else None
                    ),
                    "effective_to": (
                        entry.effective_to.isoformat() if entry.effective_to else None
                    ),
                    "source_dataset_hash": dataset.content_hash,
                }
            )
        questions = ["Confirm the final controlled-product classification with a reviewer."]
        if not request.end_use or not request.end_use.strip():
            questions.append("Document the specific civilian/military end use and end user.")
        if len(request.product_code_candidates) > 1:
            questions.append("Resolve the competing product-code candidates and their impacts.")
        if not request.end_use or candidates:
            outcome = "review_required"
        else:
            outcome = "no_candidate"
        row = ExportControlAssessmentRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            product_concept_id=request.product_concept_id,
            buyer_entity_id=request.buyer_entity_id,
            dataset_id=dataset.id,
            destination_country=request.destination_country.upper(),
            product_code_candidates_json=[
                value.model_dump(mode="json") for value in request.product_code_candidates
            ],
            end_use=request.end_use,
            restriction_candidates_json=candidates,
            questions_json=questions,
            outcome=outcome,
            rule_version=f"{dataset.dataset_key}:v{dataset.version_no}:{dataset.content_hash}",
        )
        self.session.add(row)
        self.session.commit()
        return row


class TradeRequirementService(_RuleDatasetMixin):
    def __init__(self, session: Session):
        self.session = session

    def assess(self, request: TradeRequirementCreate) -> TradeRequirementAssessmentRow:
        request_hash = request_fingerprint({"operation": "risk.trade_requirements.assess"}, request)
        existing = idempotent_row(
            self.session, TradeRequirementAssessmentRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        require_row(self.session, ProductConceptRow, request.product_concept_id, "product")
        dataset = self._dataset(request.dataset_id, "trade_requirements")
        groups: dict[str, list[dict[str, Any]]] = {
            "tariff": [],
            "certification": [],
            "trade_remedy": [],
        }
        for entry in self.session.scalars(
            select(ComplianceEntryRow).where(ComplianceEntryRow.dataset_id == dataset.id)
        ):
            if entry.entry_type not in groups or not _active_on(entry, request.as_of):
                continue
            fields = entry.fields_json
            if not _matches_location(request.origin_country, fields.get("origins")):
                continue
            if not _matches_location(request.destination_country, fields.get("destinations")):
                continue
            listed_codes = fields.get("product_codes") or []
            matched_codes = [
                candidate.model_dump(mode="json")
                for candidate in request.product_code_candidates
                if any(_matches_code(candidate.code, listed) for listed in listed_codes)
            ]
            if not matched_codes:
                continue
            groups[entry.entry_type].append(
                {
                    "entry_id": entry.id,
                    "external_id": entry.external_id,
                    "matched_product_codes": matched_codes,
                    "fields": fields,
                    "effective_from": (
                        entry.effective_from.isoformat() if entry.effective_from else None
                    ),
                    "effective_to": (
                        entry.effective_to.isoformat() if entry.effective_to else None
                    ),
                    "source_dataset_hash": dataset.content_hash,
                }
            )
        assumptions: list[str] = []
        uncertain_codes = len(request.product_code_candidates) > 1 or any(
            candidate.confidence < 1 for candidate in request.product_code_candidates
        )
        if uncertain_codes:
            assumptions.append(
                "Product classification is uncertain; all candidate rules and impacts are retained."
            )
        candidate_count = sum(len(values) for values in groups.values())
        if uncertain_codes:
            outcome = "review_required"
        elif candidate_count:
            outcome = "candidates_found"
        else:
            outcome = "no_candidate"
        row = TradeRequirementAssessmentRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            product_concept_id=request.product_concept_id,
            dataset_id=dataset.id,
            origin_country=request.origin_country.upper(),
            destination_country=request.destination_country.upper(),
            product_code_candidates_json=[
                value.model_dump(mode="json") for value in request.product_code_candidates
            ],
            tariff_candidates_json=groups["tariff"],
            certification_candidates_json=groups["certification"],
            remedy_candidates_json=groups["trade_remedy"],
            assumptions_json=assumptions,
            outcome=outcome,
            rule_version=f"{dataset.dataset_key}:v{dataset.version_no}:{dataset.content_hash}",
        )
        self.session.add(row)
        self.session.commit()
        return row

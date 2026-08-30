from __future__ import annotations

from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.conflicts import ConflictService
from tradefoundry.evidence.contracts import ClaimCandidate, ClaimView, ExtractionRequest
from tradefoundry.evidence.models import (
    ClaimEvidenceRow,
    ClaimRow,
    EvidenceDocumentRow,
    EvidenceFragmentRow,
    ExtractionRunRow,
)
from tradefoundry.evidence.normalization import ClaimNormalizer
from tradefoundry.evidence.schemas import ExtractionSchemaRegistry


class ExtractionValidationError(ValueError):
    pass


class ClaimExtractionService:
    def __init__(self, session: Session):
        self.session = session
        self.schemas = ExtractionSchemaRegistry(session)
        self.normalizer = ClaimNormalizer()

    def extract(self, document_id: str, request: ExtractionRequest) -> list[ClaimView]:
        document = self.session.get(EvidenceDocumentRow, document_id)
        if document is None:
            raise LookupError(f"document {document_id} not found")
        if document.status != "accepted":
            raise ExtractionValidationError("quarantined documents cannot produce Claims")
        schema = self.schemas.resolve(request.schema_key, request.schema_version)
        run = ExtractionRunRow(
            id=str(uuid4()),
            document_id=document.id,
            schema_id=schema.id,
            method=request.method,
            model_name=request.model_name,
            prompt_version=request.prompt_version,
            status="validating",
            raw_output_json=request.output,
            errors_json=[],
        )
        self.session.add(run)
        self.session.flush()

        errors = self._validation_errors(schema.json_schema, request.output)
        candidates: list[ClaimCandidate] = []
        if not errors:
            raw_claims = request.output.get("claims")
            if not isinstance(raw_claims, list):
                errors.append({"path": "claims", "message": "claims must be an array"})
            else:
                for index, raw in enumerate(raw_claims):
                    try:
                        candidates.append(ClaimCandidate.model_validate(raw))
                    except ValidationError as exc:
                        errors.append(
                            {"path": f"claims.{index}", "message": str(exc), "type": "contract"}
                        )
        fragment_map = self._fragments(document.id)
        for index, candidate in enumerate(candidates):
            missing = [key for key in candidate.evidence if key not in fragment_map]
            if missing:
                errors.append(
                    {
                        "path": f"claims.{index}.evidence",
                        "message": f"unknown evidence fragments: {missing}",
                    }
                )
        if errors:
            run.status = "failed_validation"
            run.errors_json = errors
            self.session.commit()
            raise ExtractionValidationError(f"extraction output rejected: {errors}")

        claims: list[ClaimRow] = []
        for candidate in candidates:
            rule = schema.field_rules.get(candidate.field_path, {})
            normalized = self.normalizer.normalize(candidate.value, rule)
            status = "validated" if normalized.status == "normalized" else "needs_review"
            claim = ClaimRow(
                id=str(uuid4()),
                document_id=document.id,
                extraction_run_id=run.id,
                schema_id=schema.id,
                subject_key=candidate.subject_key,
                field_path=candidate.field_path,
                value_json=candidate.value,
                normalized_value_json=normalized.value,
                normalization_status=normalized.status,
                unit=normalized.unit,
                currency=normalized.currency,
                confidence=candidate.confidence,
                method=request.method,
                method_version=request.prompt_version or request.model_name,
                status=status,
                valid_from=candidate.valid_from,
                valid_to=candidate.valid_to,
            )
            self.session.add(claim)
            self.session.flush()
            for key in dict.fromkeys(candidate.evidence):
                self.session.add(
                    ClaimEvidenceRow(
                        id=str(uuid4()), claim_id=claim.id, fragment_id=fragment_map[key].id
                    )
                )
            ConflictService(self.session).detect(claim)
            claims.append(claim)
        run.status = "succeeded"
        self.session.commit()
        return [ClaimView.model_validate(claim) for claim in claims]

    def _fragments(self, document_id: str) -> dict[str, EvidenceFragmentRow]:
        rows = self.session.scalars(
            select(EvidenceFragmentRow).where(EvidenceFragmentRow.document_id == document_id)
        ).all()
        return {row.fragment_key: row for row in rows}

    @staticmethod
    def _validation_errors(schema: dict, output: dict) -> list[dict[str, str]]:
        validator = Draft202012Validator(schema)
        return [
            {
                "path": ".".join(str(part) for part in error.absolute_path),
                "message": error.message,
                "type": "json_schema",
            }
            for error in sorted(
                validator.iter_errors(output), key=lambda item: str(list(item.path))
            )
        ]

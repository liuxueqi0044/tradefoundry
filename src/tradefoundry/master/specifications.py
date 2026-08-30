from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.normalization import ClaimNormalizer
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.contracts import (
    RequirementInput,
    RequirementView,
    SpecificationCreate,
    SpecificationDifference,
    SpecificationView,
)
from tradefoundry.master.evidence import require_reliable_claim
from tradefoundry.master.models import (
    ProductConceptRow,
    ProductRequirementRow,
    ProductSpecificationRow,
)


class ProductSpecificationService:
    def __init__(self, session: Session):
        self.session = session
        self.normalizer = ClaimNormalizer()

    def create(self, request: SpecificationCreate) -> SpecificationView:
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(ProductSpecificationRow).where(
                ProductSpecificationRow.specification_key == request.specification_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError(
                    f"specification key {request.specification_key} has a different payload"
                )
            return self.get(existing.id)
        if self.session.get(ProductConceptRow, request.concept_id) is None:
            raise LookupError(f"product concept {request.concept_id} not found")
        require_reliable_claim(self.session, request.source_claim_id)
        keys = [item.requirement_key for item in request.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("requirement keys must be unique within a specification")
        row = ProductSpecificationRow(
            id=str(uuid4()),
            specification_key=request.specification_key,
            request_hash=request_hash,
            concept_id=request.concept_id,
            version_no=request.version_no,
            original_text=request.original_text,
            source_claim_id=request.source_claim_id,
        )
        self.session.add(row)
        self.session.flush()
        for item in request.requirements:
            claim_id = item.source_claim_id or request.source_claim_id
            require_reliable_claim(self.session, claim_id)
            normalized, unit = self._normalize_requirement(item)
            self.session.add(
                ProductRequirementRow(
                    id=str(uuid4()),
                    specification_id=row.id,
                    requirement_key=item.requirement_key,
                    mode=item.mode,
                    value_json=item.value,
                    normalized_value_json=normalized,
                    unit=unit,
                    original_text=item.original_text,
                    source_claim_id=claim_id,
                )
            )
        self.session.commit()
        return self.get(row.id)

    def get(self, specification_id: str) -> SpecificationView:
        row = self.session.get(ProductSpecificationRow, specification_id)
        if row is None:
            raise LookupError(f"product specification {specification_id} not found")
        requirements = self.session.scalars(
            select(ProductRequirementRow)
            .where(ProductRequirementRow.specification_id == row.id)
            .order_by(ProductRequirementRow.requirement_key)
        ).all()
        return SpecificationView(
            id=row.id,
            specification_key=row.specification_key,
            concept_id=row.concept_id,
            version_no=row.version_no,
            original_text=row.original_text,
            source_claim_id=row.source_claim_id,
            requirements=[RequirementView.model_validate(item) for item in requirements],
        )

    def diff(self, left_id: str, right_id: str) -> list[SpecificationDifference]:
        left = self.get(left_id)
        right = self.get(right_id)
        left_map = {item.requirement_key: item for item in left.requirements}
        right_map = {item.requirement_key: item for item in right.requirements}
        result: list[SpecificationDifference] = []
        for key in sorted(left_map.keys() | right_map.keys()):
            before = left_map.get(key)
            after = right_map.get(key)
            if before is None:
                change = "added"
            elif after is None:
                change = "removed"
            elif (
                before.normalized_value_json == after.normalized_value_json
                and before.mode == after.mode
            ):
                change = "unchanged"
            else:
                change = "changed"
            result.append(
                SpecificationDifference(
                    requirement_key=key, change_type=change, left=before, right=after
                )
            )
        return result

    def _normalize_requirement(self, item: RequirementInput) -> tuple[object, str | None]:
        if item.mode == "range":
            if not isinstance(item.value, dict) or not {"min", "max"} <= item.value.keys():
                raise ValueError("range requirement requires min and max")
            minimum, unit = self._quantity(item.value["min"], item)
            maximum, maximum_unit = self._quantity(item.value["max"], item)
            if Decimal(minimum["amount"]) > Decimal(maximum["amount"]):
                raise ValueError("range minimum cannot exceed maximum")
            if unit != maximum_unit:
                raise ValueError("range endpoints must normalize to the same unit")
            return {"min": minimum["amount"], "max": maximum["amount"], "unit": unit}, unit
        if item.mode == "tolerance":
            if not isinstance(item.value, dict) or not {"target", "tolerance"} <= item.value.keys():
                raise ValueError("tolerance requirement requires target and tolerance")
            target, unit = self._quantity(item.value["target"], item)
            tolerance, tolerance_unit = self._quantity(item.value["tolerance"], item)
            if unit != tolerance_unit:
                raise ValueError("target and tolerance must normalize to the same unit")
            return {
                "target": target["amount"],
                "tolerance": tolerance["amount"],
                "unit": unit,
            }, unit
        if item.unit:
            normalized, unit = self._quantity(item.value, item)
            return normalized, unit
        return item.value, None

    def _quantity(self, value: object, item: RequirementInput) -> tuple[dict, str]:
        result = self.normalizer.normalize(
            {"amount": value, "unit": item.unit},
            {"type": "quantity", "target_unit": item.target_unit},
        )
        if result.status != "normalized" or result.unit is None:
            raise ValueError(f"invalid requirement quantity: {result.reason or result.status}")
        return result.value, result.unit

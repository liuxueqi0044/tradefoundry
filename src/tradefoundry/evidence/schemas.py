from __future__ import annotations

from uuid import uuid4

from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.evidence.contracts import ExtractionSchemaCreate, ExtractionSchemaView
from tradefoundry.evidence.models import ExtractionSchemaRow


class ExtractionSchemaRegistry:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: ExtractionSchemaCreate) -> ExtractionSchemaView:
        Draft202012Validator.check_schema(request.json_schema)
        current = self.session.scalar(
            select(func.max(ExtractionSchemaRow.version_no)).where(
                ExtractionSchemaRow.schema_key == request.schema_key
            )
        )
        row = ExtractionSchemaRow(
            id=str(uuid4()),
            schema_key=request.schema_key,
            version_no=(current or 0) + 1,
            status="draft",
            json_schema=request.json_schema,
            field_rules=request.field_rules,
            instructions=request.instructions,
        )
        self.session.add(row)
        self.session.commit()
        return ExtractionSchemaView.model_validate(row)

    def activate(self, schema_key: str, version_no: int) -> ExtractionSchemaView:
        target = self._get(schema_key, version_no)
        active = self.session.scalars(
            select(ExtractionSchemaRow).where(
                ExtractionSchemaRow.schema_key == schema_key,
                ExtractionSchemaRow.status == "active",
            )
        ).all()
        for row in active:
            row.status = "deprecated"
        self.session.flush()
        target.status = "active"
        self.session.commit()
        return ExtractionSchemaView.model_validate(target)

    def deprecate(self, schema_key: str, version_no: int) -> ExtractionSchemaView:
        target = self._get(schema_key, version_no)
        target.status = "deprecated"
        self.session.commit()
        return ExtractionSchemaView.model_validate(target)

    def resolve(self, schema_key: str, version_no: int | None = None) -> ExtractionSchemaRow:
        if version_no is not None:
            return self._get(schema_key, version_no)
        row = self.session.scalar(
            select(ExtractionSchemaRow).where(
                ExtractionSchemaRow.schema_key == schema_key,
                ExtractionSchemaRow.status == "active",
            )
        )
        if row is None:
            raise LookupError(f"no active schema for {schema_key}")
        return row

    def list(self, schema_key: str) -> list[ExtractionSchemaView]:
        rows = self.session.scalars(
            select(ExtractionSchemaRow)
            .where(ExtractionSchemaRow.schema_key == schema_key)
            .order_by(ExtractionSchemaRow.version_no)
        ).all()
        return [ExtractionSchemaView.model_validate(row) for row in rows]

    def _get(self, schema_key: str, version_no: int) -> ExtractionSchemaRow:
        row = self.session.scalar(
            select(ExtractionSchemaRow).where(
                ExtractionSchemaRow.schema_key == schema_key,
                ExtractionSchemaRow.version_no == version_no,
            )
        )
        if row is None:
            raise LookupError(f"schema {schema_key} v{version_no} not found")
        return row

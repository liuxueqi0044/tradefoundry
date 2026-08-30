import pytest
from jsonschema import SchemaError

from tradefoundry.evidence.contracts import ExtractionSchemaCreate
from tradefoundry.evidence.schemas import ExtractionSchemaRegistry


def _request(key: str, value_type: str = "string") -> ExtractionSchemaCreate:
    return ExtractionSchemaCreate(
        schema_key=key,
        json_schema={
            "type": "object",
            "required": ["claims"],
            "properties": {"claims": {"type": "array", "items": {"type": value_type}}},
        },
    )


def test_schema_versions_activate_deprecate_and_rollback(session):
    registry = ExtractionSchemaRegistry(session)
    first = registry.create(_request("notice.schema"))
    registry.activate(first.schema_key, first.version_no)
    second = registry.create(_request("notice.schema", "object"))
    registry.activate(second.schema_key, second.version_no)
    rolled_back = registry.activate(first.schema_key, first.version_no)
    versions = registry.list("notice.schema")

    assert [row.version_no for row in versions] == [1, 2]
    assert rolled_back.status == "active"
    assert versions[1].status == "deprecated"


def test_invalid_json_schema_never_enters_registry(session):
    registry = ExtractionSchemaRegistry(session)
    with pytest.raises(SchemaError):
        registry.create(
            ExtractionSchemaCreate(
                schema_key="bad.schema",
                json_schema={"type": "definitely-not-a-json-schema-type"},
            )
        )


def test_missing_active_schema_and_missing_version_are_explicit(session):
    registry = ExtractionSchemaRegistry(session)
    with pytest.raises(LookupError, match="no active schema"):
        registry.resolve("missing.schema")
    with pytest.raises(LookupError, match="v9 not found"):
        registry.resolve("missing.schema", 9)

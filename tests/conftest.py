from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from tradefoundry.bilateral import models as bilateral_models  # noqa: F401
from tradefoundry.controltower import models as controltower_models  # noqa: F401
from tradefoundry.db import Base
from tradefoundry.deals import models as deal_models  # noqa: F401
from tradefoundry.evidence import models as evidence_models  # noqa: F401
from tradefoundry.evidence.contracts import ExtractionSchemaCreate
from tradefoundry.evidence.conversion import ConversionService, StructuredTextConverter
from tradefoundry.evidence.intake import FileIntakeService
from tradefoundry.evidence.schemas import ExtractionSchemaRegistry
from tradefoundry.ingestion import models  # noqa: F401
from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.contracts import SourceCreate, SourceKind
from tradefoundry.ingestion.registry import SourceRegistry
from tradefoundry.master import models as master_models  # noqa: F401
from tradefoundry.master.contracts import AttributeInput, EntityCreate
from tradefoundry.master.entities import EntityService
from tradefoundry.opportunity import models as opportunity_models  # noqa: F401
from tradefoundry.tradealpha import models as tradealpha_models  # noqa: F401


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        yield value
    Base.metadata.drop_all(engine)


@pytest.fixture
def artifact_store(tmp_path):
    return FileSystemArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def evidence_document_factory(session, artifact_store):
    def create(
        *,
        logical_id: str = "tender-001",
        content: bytes = b"<html><body><h1>Tender</h1><p>Deadline 2026-10-01</p></body></html>",
        filename: str = "tender.html",
        media_type: str = "text/html",
        convert: bool = True,
    ):
        document = FileIntakeService(session, artifact_store).ingest(
            logical_document_id=logical_id,
            filename=filename,
            content=content,
            declared_media_type=media_type,
        )
        if convert and document.status == "accepted":
            ConversionService(session, artifact_store).convert(
                document.id, StructuredTextConverter()
            )
        return document

    return create


@pytest.fixture
def extraction_schema_factory(session):
    def create(*, key: str = "tender.claims", field_rules: dict | None = None):
        request = ExtractionSchemaCreate(
            schema_key=key,
            json_schema={
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["claims"],
                "additionalProperties": False,
                "properties": {
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["subject_key", "field_path", "value", "evidence"],
                            "properties": {
                                "subject_key": {"type": "string"},
                                "field_path": {"type": "string"},
                                "value": {},
                                "evidence": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string"},
                                },
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "valid_from": {"type": "string", "format": "date-time"},
                                "valid_to": {"type": "string", "format": "date-time"},
                            },
                            "additionalProperties": False,
                        },
                    }
                },
            },
            field_rules=field_rules or {},
            instructions="Return only evidence-grounded Claims.",
        )
        registry = ExtractionSchemaRegistry(session)
        schema = registry.create(request)
        return registry.activate(schema.schema_key, schema.version_no)

    return create


@pytest.fixture
def master_claim_factory(session, evidence_document_factory, extraction_schema_factory):
    from tradefoundry.evidence.claims import ClaimExtractionService
    from tradefoundry.evidence.contracts import ExtractionRequest, ReviewRequest
    from tradefoundry.evidence.review import ClaimReviewService

    state = {"index": 0, "document": None, "schema": None}

    def create(*, value="evidence", field_path="master_seed", verified=False):
        state["index"] += 1
        if state["document"] is None:
            state["document"] = evidence_document_factory(logical_id="master-seed")
            state["schema"] = extraction_schema_factory(key="master.seed.claims")
        claim = ClaimExtractionService(session).extract(
            state["document"].id,
            ExtractionRequest(
                schema_key="master.seed.claims",
                method="golden_fixture",
                output={
                    "claims": [
                        {
                            "subject_key": f"master:seed:{state['index']}",
                            "field_path": field_path,
                            "value": value,
                            "evidence": ["html:1"],
                        }
                    ]
                },
            ),
        )[0]
        if verified:
            claim = ClaimReviewService(session).review(
                claim.id,
                ReviewRequest(
                    action="verify",
                    reviewer="master-fixture-reviewer",
                    reason="Verified golden master-data fixture.",
                ),
            )
        return claim

    return create


@pytest.fixture
def master_entity_factory(session, master_claim_factory):
    state = {"index": 0}

    def create(
        *,
        name: str = "Acme Limited",
        entity_type: str = "organization",
        key: str | None = None,
        claim_id: str | None = None,
        attributes: dict | None = None,
        priority: int = 0,
        risk_tier: str = "normal",
    ):
        state["index"] += 1
        claim = None if claim_id else master_claim_factory(value=name)
        source_claim_id = claim_id or claim.id
        return EntityService(session).create(
            EntityCreate(
                entity_key=key or f"entity:{state['index']}",
                entity_type=entity_type,
                source_claim_id=source_claim_id,
                primary_name=name,
                attributes=[
                    AttributeInput(
                        field_name=field_name,
                        value=value,
                        source_priority=priority,
                    )
                    for field_name, value in (attributes or {}).items()
                ],
                risk_tier=risk_tier,
            )
        )

    return create


@pytest.fixture
def product_concept_factory(session, master_claim_factory):
    from tradefoundry.master.contracts import ProductConceptCreate
    from tradefoundry.master.products import ProductOntologyService

    state = {"index": 0}

    def create(*, label: str = "Industrial Valve", key: str | None = None):
        state["index"] += 1
        claim = master_claim_factory(value=label, field_path="product.name", verified=True)
        return ProductOntologyService(session).create(
            ProductConceptCreate(
                concept_key=key or f"opportunity-product-{state['index']}",
                preferred_label=label,
                source_claim_id=claim.id,
            )
        )

    return create


@pytest.fixture
def world_event_factory(session, master_claim_factory, master_entity_factory):
    from datetime import timedelta

    from tradefoundry.opportunity.contracts import (
        EventProductInput,
        EventSubjectInput,
        EventType,
        WorldEventCreate,
    )
    from tradefoundry.opportunity.events import WorldEventService

    state = {"index": 0}

    def create(
        *,
        event_type: str = "rfq",
        title: str = "Verified RFQ for industrial equipment",
        subject=None,
        subject_role: str = "buyer",
        product_concept_id: str | None = None,
        country_code: str = "KE",
        occurred_at: datetime | None = None,
        expires_at: datetime | None = None,
        field_path: str = "procurement.notice",
        value: str = "verified demand",
        reliability: float = 0.95,
    ):
        state["index"] += 1
        at = occurred_at or datetime(2026, 8, 30, tzinfo=UTC)
        subject = subject or master_entity_factory(
            name=f"Opportunity subject {state['index']}",
            entity_type="organization" if subject_role == "buyer" else "project",
        )
        event_claim = master_claim_factory(value=value, field_path=field_path, verified=True)
        products = []
        if product_concept_id:
            product_claim = master_claim_factory(
                value="industrial product", field_path="procurement.product", verified=True
            )
            products.append(
                EventProductInput(
                    product_concept_id=product_concept_id,
                    claim_id=product_claim.id,
                    certainty=0.94,
                )
            )
        request = WorldEventCreate(
            title=title,
            event_type=EventType(event_type),
            occurred_at=at,
            expires_at=expires_at or at + timedelta(days=60),
            country_code=country_code,
            reliability=reliability,
            evidence_claim_ids=[event_claim.id],
            subjects=[
                EventSubjectInput(
                    entity_id=subject.id,
                    role=subject_role,
                    claim_id=event_claim.id,
                )
            ],
            products=products,
            correlation_id=f"opportunity-fixture-{state['index']}",
        )
        return WorldEventService(session).build(request)

    return create


@pytest.fixture
def opportunity_template_factory(session):
    from tradefoundry.opportunity.contracts import (
        TemplateCreate,
        TemplateStateRequest,
    )
    from tradefoundry.opportunity.templates import OpportunityTemplateService

    state = {"index": 0}

    def create(
        *,
        product_concept_id: str,
        event_types: list[str] | None = None,
        signal_types: list[str] | None = None,
        required_claim_fields: list[str] | None = None,
        product_need_rules: list[dict] | None = None,
        forbidden_conditions: list[dict] | None = None,
        key: str | None = None,
    ):
        state["index"] += 1
        service = OpportunityTemplateService(session)
        template = service.create(
            TemplateCreate(
                template_key=key or f"fixture-template-{state['index']}",
                idempotency_key=f"fixture-template-create-{state['index']}",
                name=f"Fixture opportunity template {state['index']}",
                event_types=event_types or ["rfq", "project_approval"],
                signal_types=signal_types or [],
                required_claim_fields=required_claim_fields or [],
                product_concept_ids=[product_concept_id],
                product_need_rules=product_need_rules or [],
                forbidden_conditions=forbidden_conditions or [],
                created_by="fixture-architect",
            )
        )
        return service.activate(
            template.id,
            TemplateStateRequest(
                actor="fixture-architect",
                reason="Activate golden acceptance template.",
            ),
        )

    return create


@pytest.fixture
def ready_issuance_factory(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    from tradefoundry.opportunity.auditor import HypothesisAuditor
    from tradefoundry.opportunity.compiler import OpportunityCompiler
    from tradefoundry.opportunity.contracts import AuditRequest, CompileRequest, IssuanceRequest
    from tradefoundry.opportunity.issuance import DealCellIssuanceService

    state = {"index": 0}

    def create():
        state["index"] += 1
        index = state["index"]
        product = product_concept_factory()
        event = world_event_factory(product_concept_id=product.id)
        template = opportunity_template_factory(
            product_concept_id=product.id,
            event_types=["rfq"],
            signal_types=["explicit_rfq"],
        )
        hypothesis = OpportunityCompiler(session).compile(
            CompileRequest(
                event_id=event.id,
                template_id=template.id,
                correlation_id=f"deal-fixture-compile-{index}",
            )
        )[0]
        HypothesisAuditor(session).audit(
            hypothesis.id,
            AuditRequest(
                idempotency_key=f"deal-fixture-audit-{index}",
                actor="sol-auditor",
                as_of=datetime(2026, 9, 1, tzinfo=UTC),
            ),
        )
        issuance = DealCellIssuanceService(session).issue(
            hypothesis.id,
            IssuanceRequest(
                idempotency_key=f"deal-fixture-issue-{index}",
                requested_by="deal-fixture",
                correlation_id=f"deal-fixture-issue-{index}",
            ),
        )
        return issuance, hypothesis

    return create


@pytest.fixture
def deal_route_factory(session, ready_issuance_factory):
    from decimal import Decimal

    from tradefoundry.deals.aggregates import DealCellService, DealRouteService
    from tradefoundry.deals.contracts import DealCellCreate, DealRouteCreate
    from tradefoundry.opportunity.models import RouteCandidateRow

    state = {"index": 0}

    def create(*, cell_budget="1000.00", route_budget="500.00"):
        state["index"] += 1
        index = state["index"]
        issuance, hypothesis = ready_issuance_factory()
        cell = DealCellService(session).create(
            DealCellCreate(
                issuance_command_id=issuance.id,
                owner="deal-owner",
                amount=Decimal(cell_budget),
                currency="USD",
            )
        )
        candidate = next(
            session.get(RouteCandidateRow, candidate_id)
            for candidate_id in hypothesis.route_candidate_ids_json
            if session.get(RouteCandidateRow, candidate_id).feasibility == "feasible"
        )
        route = DealRouteService(session).create(
            cell.id,
            DealRouteCreate(
                route_key=f"deal-route-{index}",
                source_route_candidate_id=candidate.id,
                roles={"owner": "deal-owner"},
                amount=Decimal(route_budget),
                currency="USD",
            ),
        )
        return cell, route

    return create


@pytest.fixture
def source_factory(session):
    def create(
        *,
        kind: SourceKind = SourceKind.MEMORY,
        key: str = "test-source",
        config: dict | None = None,
        quality: dict | None = None,
    ):
        registry = SourceRegistry(session)
        source = registry.create(
            SourceCreate(
                key=key,
                name=f"Source {key}",
                kind=kind,
                owner="data-owner",
                access_url="https://example.invalid/data",
                access_method="official fixture",
                schedule_cron="0 * * * *",
                sla_hours=24,
                license_name="Fixture License",
                license_url="https://example.invalid/license",
                terms_checked_at=datetime.now(UTC),
                commercial_use_allowed=True,
                retention_allowed=True,
                redistribution_allowed=False,
                connector_config=config or {"pages": [[{"id": "1", "value": "a"}]]},
                quality_config=quality or {},
            )
        )
        return registry.activate(source.id)

    return create

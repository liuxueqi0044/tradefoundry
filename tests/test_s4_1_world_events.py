from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from tradefoundry.opportunity.contracts import (
    EventSubjectInput,
    EventType,
    WorldEventCreate,
)
from tradefoundry.opportunity.events import WorldEventService
from tradefoundry.opportunity.models import WorldEventClaimRow, WorldEventRow


def test_same_verified_fact_set_builds_one_traceable_world_event(
    session, master_claim_factory, master_entity_factory
):
    buyer = master_entity_factory(name="Nairobi Water Authority")
    claim = master_claim_factory(
        value="RFQ for valves", field_path="procurement.notice", verified=True
    )
    occurred = datetime(2026, 8, 30, tzinfo=UTC)
    request = WorldEventCreate(
        title="Valve RFQ",
        event_type=EventType.RFQ,
        occurred_at=occurred,
        expires_at=occurred + timedelta(days=30),
        country_code="ke",
        reliability=0.96,
        evidence_claim_ids=[claim.id],
        subjects=[EventSubjectInput(entity_id=buyer.id, role="buyer", claim_id=claim.id)],
        correlation_id="event-build-1",
    )
    service = WorldEventService(session)
    first = service.build(request)
    repeated = service.build(request.model_copy(update={"correlation_id": "retry"}))

    assert repeated.id == first.id
    assert first.country_code == "KE"
    assert first.reliability == 0.96
    assert first.facts_snapshot_json["claim_facts"][0]["field_path"] == "procurement.notice"
    assert session.scalar(select(func.count()).select_from(WorldEventRow)) == 1
    assert session.scalar(select(func.count()).select_from(WorldEventClaimRow)) == 1


def test_world_event_rejects_unverified_claims(
    session, master_claim_factory, master_entity_factory
):
    entity = master_entity_factory()
    claim = master_claim_factory(value="unreviewed", field_path="event.kind")
    request = WorldEventCreate(
        title="Unreviewed event",
        event_type="other",
        occurred_at=datetime(2026, 8, 30, tzinfo=UTC),
        reliability=0.5,
        evidence_claim_ids=[claim.id],
        subjects=[EventSubjectInput(entity_id=entity.id, role="owner", claim_id=claim.id)],
        correlation_id="event-unverified",
    )

    with pytest.raises(ValueError, match="verified Claim is required"):
        WorldEventService(session).build(request)

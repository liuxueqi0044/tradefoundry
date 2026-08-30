from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tradefoundry.bilateral.contracts import (
    IntentClassifyRequest,
    InteractionIntake,
    QualificationCreate,
    QualificationField,
)
from tradefoundry.bilateral.messaging import (
    IntentClassificationService,
    InteractionService,
    QualificationService,
)
from tradefoundry.bilateral.models import InteractionReviewQueueRow


def _interaction(session, *, message_id, body, route_id=None, thread_key=None):
    return InteractionService(session).intake(
        InteractionIntake(
            external_message_id=message_id,
            channel="email",
            direction="inbound",
            raw_artifact_ref=f"artifact://message/{message_id}",
            raw_hash=(message_id[0] if message_id[0].isalnum() else "a") * 64,
            body_text=body,
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
            explicit_route_id=route_id,
            thread_key=thread_key,
            metadata={"subject": "Valve sourcing discussion"},
            attachment_refs=["artifact://attachment/spec.pdf"],
        )
    )


def test_interaction_exact_thread_link_is_reused_and_raw_reference_preserved(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    first = _interaction(
        session,
        message_id="message-explicit-1",
        body="Please quote the valve.",
        route_id=route.id,
        thread_key="thread-abc",
    )
    reply = _interaction(
        session,
        message_id="message-reply-1",
        body="Can you improve delivery?",
        thread_key="thread-abc",
    )

    assert first.link_method == "explicit_route"
    assert reply.route_id == route.id
    assert reply.link_method == "exact_thread"
    assert reply.link_confidence == 0.99
    assert reply.raw_artifact_ref == "artifact://message/message-reply-1"
    assert reply.attachment_refs_json == ["artifact://attachment/spec.pdf"]


def test_ambiguous_interaction_goes_to_human_queue_without_guessing_route(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    interaction = _interaction(
        session,
        message_id="unmatched-1",
        body=f"General follow-up mentioning {route.route_key}",
    )
    queue_item = session.scalar(
        select(InteractionReviewQueueRow).where(
            InteractionReviewQueueRow.interaction_id == interaction.id
        )
    )

    assert interaction.route_id is None
    assert interaction.status == "needs_review"
    assert queue_item.status == "open"
    assert queue_item.candidate_routes_json[0]["route_id"] == route.id


@pytest.mark.parametrize(
    ("body", "expected_intent", "needs_review"),
    [
        ("We are interested, please quote.", "positive_interest", False),
        ("No thanks, we are not interested.", "rejection", False),
        ("Can you improve the delivery lead time?", "clarification", False),
        ("The price is too expensive.", "clarification", False),
        ("Following up on our prior note.", "unknown", True),
    ],
)
def test_intent_classifier_golden_replies(
    body, expected_intent, needs_review, session, deal_route_factory
):
    _, route = deal_route_factory()
    interaction = _interaction(
        session,
        message_id=f"intent-{expected_intent}-{abs(hash(body))}",
        body=body,
        route_id=route.id,
    )
    stage_before = route.stage
    assessment = IntentClassificationService(session).classify(
        interaction.id,
        IntentClassifyRequest(
            idempotency_key=f"classify-{interaction.id}", confidence_threshold=0.75
        ),
    )

    assert assessment.intent == expected_intent
    assert assessment.needs_review is needs_review
    assert route.stage == stage_before


def test_qualification_keeps_six_dimensions_separate_and_does_not_impute_missing(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    interaction = _interaction(
        session,
        message_id="qualification-source-1",
        body="We need 100 pieces within 30 days.",
        route_id=route.id,
    )
    snapshot = QualificationService(session).snapshot(
        route.id,
        QualificationCreate(
            idempotency_key="qualification-1",
            as_of=datetime(2026, 9, 2, tzinfo=UTC),
            quantity=QualificationField(
                value={"amount": 100, "unit": "piece"},
                source_interaction_id=interaction.id,
                confidence=0.95,
            ),
            timing=QualificationField(
                value={"required_lead_time_days": 30},
                source_interaction_id=interaction.id,
                confidence=0.9,
            ),
        ),
    )

    assert snapshot.quantity_json["value"]["amount"] == 100
    assert snapshot.timing_json["value"]["required_lead_time_days"] == 30
    assert snapshot.specification_json is None
    assert snapshot.budget_json is None
    assert set(snapshot.missing_fields_json) == {
        "specification",
        "budget",
        "authority",
        "procurement_process",
    }

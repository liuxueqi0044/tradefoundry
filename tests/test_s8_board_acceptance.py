from datetime import UTC, datetime

import pytest
from bilateral_helpers import (
    AllowPolicy,
    RecordingGateway,
    create_buyer_contact,
    create_supplier,
)
from control_helpers import approved_action
from sqlalchemy import select

from tradefoundry.bilateral.contracts import (
    EligibilityRequest,
    GroundedContextItem,
    MessageDraftCreate,
    SendCommand,
)
from tradefoundry.bilateral.crm import CommunicationEligibilityService
from tradefoundry.bilateral.messaging import MessageDraftService
from tradefoundry.bilateral.outbound import OutboundSendService
from tradefoundry.controltower.adapters import Board7ExecutionGuard
from tradefoundry.controltower.contracts import (
    ComplianceEntryInput,
    DatasetSyncCreate,
    ExecutionTokenIssue,
    FreezeRelease,
    ScreeningCreate,
)
from tradefoundry.controltower.datasets import ComplianceDatasetService
from tradefoundry.controltower.governance import ExecutionTokenService, FreezeService
from tradefoundry.controltower.models import FreezeRow
from tradefoundry.controltower.screening import ScreeningService

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def test_possible_match_freezes_board7_send_until_review_then_one_control_token_executes_once(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    buyer, contact, buyer_claim, _ = create_buyer_contact(
        session, master_entity_factory, master_claim_factory, index=88
    )
    _, _, _, capability_claim = create_supplier(
        session,
        master_entity_factory,
        master_claim_factory,
        product_concept_factory,
        index=88,
    )
    eligibility = CommunicationEligibilityService(session, AllowPolicy()).evaluate(
        contact.id,
        EligibilityRequest(
            idempotency_key="board8-eligibility",
            channel="email",
            jurisdiction="KE",
            purpose="first_contact",
            evaluated_at=NOW,
        ),
    )
    draft = MessageDraftService(session).create(
        route.id,
        MessageDraftCreate(
            idempotency_key="board8-draft",
            draft_key="board8-first-contact",
            buyer_profile_id=buyer.id,
            contact_id=contact.id,
            eligibility_decision_id=eligibility.id,
            buyer_context=[
                GroundedContextItem(text="Buyer 88 issued a valve tender", claim_id=buyer_claim.id)
            ],
            capability_context=[
                GroundedContextItem(text="Supplier 88 makes valves", claim_id=capability_claim.id)
            ],
            desired_next_step="安排一次规格确认会议",
            created_by="operator-1",
        ),
    )
    dataset = ComplianceDatasetService(session).sync(
        DatasetSyncCreate(
            dataset_key="board8-sanctions",
            idempotency_key="board8-sanctions",
            dataset_type="sanctions",
            source_uri="https://official.example.invalid/sanctions.json",
            publisher="Official Authority Fixture",
            published_at=NOW,
            license_name="Official fixture",
            entries=[
                ComplianceEntryInput(
                    external_id="LIST-88",
                    entry_type="organization",
                    names=["Buyer Eighty Eight Limited"],
                    countries=["KE"],
                )
            ],
        )
    )
    screening = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="board8-screening",
            entity_id=buyer.entity_id,
            dataset_id=dataset.id,
            names=["Buyer Eighty Eight Ltd"],
            countries=["KE"],
            identity_complete=True,
            requested_by="screening-worker",
        )
    )
    assert screening.outcome == "possible_match"
    params = {
        "recipient_ref": contact.id,
        "payload_hash": draft.content_hash,
        "resource_version": draft.version_no,
        "actor": "operator-1",
    }
    _, approval, _ = approved_action(
        session,
        resource_id=draft.id,
        params=params,
        subject_refs=[buyer.entity_id, f"entity:{buyer.entity_id}", contact.id],
        suffix="board-acceptance",
    )
    with pytest.raises(ValueError, match="active freeze"):
        ExecutionTokenService(session).issue(
            ExecutionTokenIssue(
                approval_request_id=approval.id,
                params=params,
                issued_by="control-tower",
            )
        )
    exclusion_evidence = master_claim_factory(
        value="Official registration number excludes the candidate match",
        field_path="compliance.screening_resolution",
        verified=True,
    )
    active = list(
        session.scalars(
            select(FreezeRow).where(
                FreezeRow.risk_case_id == session.get(FreezeRow, screening.freeze_id).risk_case_id,
                FreezeRow.active.is_(True),
            )
        )
    )
    for index, freeze in enumerate(active):
        FreezeService(session).release(
            freeze.id,
            FreezeRelease(
                idempotency_key=f"board8-release-{index}",
                reviewed_by="independent-compliance-reviewer",
                reason="Official registration evidence excludes the possible match.",
                evidence_claim_ids=[exclusion_evidence.id],
            ),
        )
    issued = ExecutionTokenService(session).issue(
        ExecutionTokenIssue(
            approval_request_id=approval.id,
            params=params,
            issued_by="control-tower",
        )
    )
    gateway = RecordingGateway()
    command = SendCommand(
        idempotency_key="board8-governed-send",
        control_token=issued.token,
        actor="operator-1",
    )
    sent = OutboundSendService(
        session, gateway, execution_guard=Board7ExecutionGuard(session)
    ).send(command)
    replay = OutboundSendService(
        session, gateway, execution_guard=Board7ExecutionGuard(session)
    ).send(command)
    assert sent.id == replay.id
    assert sent.control_token_id == issued.token_id
    assert sent.token_id is None
    assert len(gateway.payloads) == 1
    with pytest.raises(ValueError, match="consumed"):
        OutboundSendService(session, gateway, execution_guard=Board7ExecutionGuard(session)).send(
            SendCommand(
                idempotency_key="board8-illegal-reuse",
                control_token=issued.token,
                actor="operator-1",
            )
        )

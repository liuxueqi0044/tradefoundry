from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tradefoundry.controltower.contracts import (
    ComplianceEntryInput,
    DatasetSyncCreate,
    DatasetSyncFailure,
    ExportControlCreate,
    FreezeRelease,
    ProductCodeCandidate,
    ScreeningCreate,
    TradeRequirementCreate,
)
from tradefoundry.controltower.datasets import ComplianceDatasetService
from tradefoundry.controltower.governance import FreezeService
from tradefoundry.controltower.models import FreezeRow
from tradefoundry.controltower.screening import ScreeningService
from tradefoundry.controltower.trade_rules import (
    ExportControlService,
    TradeRequirementService,
)

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def _sync(session, *, key="official-sanctions", suffix="1", entries=None):
    return ComplianceDatasetService(session).sync(
        DatasetSyncCreate(
            dataset_key=key,
            idempotency_key=f"sync-{key}-{suffix}",
            dataset_type="sanctions",
            source_uri="https://official.example.invalid/sanctions.xml",
            publisher="Official Authority Fixture",
            published_at=NOW,
            license_name="Official public data fixture",
            entries=entries
            or [
                ComplianceEntryInput(
                    external_id="LIST-001",
                    entry_type="organization",
                    names=["Acme Trading Limited"],
                    identifiers={"registration": ["REG-9988"]},
                    countries=["KE"],
                    programs=["TEST-PROGRAM"],
                )
            ],
        )
    )


def test_dataset_sync_is_versioned_and_failed_sync_keeps_previous_active(session):
    first = _sync(session)
    failed = ComplianceDatasetService(session).record_failure(
        DatasetSyncFailure(
            dataset_key="official-sanctions",
            idempotency_key="sync-failed-2",
            source_uri="https://official.example.invalid/sanctions.xml",
            error_message="Fixture signature verification failed.",
        )
    )
    assert failed.previous_active_dataset_id == first.id
    assert ComplianceDatasetService(session).active("official-sanctions").id == first.id
    second = _sync(
        session,
        suffix="3",
        entries=[
            ComplianceEntryInput(
                external_id="LIST-002",
                entry_type="organization",
                names=["Different Listed Company"],
            )
        ],
    )
    session.refresh(first)
    assert second.version_no == 2
    assert first.status == "superseded"
    assert second.status == "active"


def test_exact_identifier_blocks_and_automatically_freezes(session, master_entity_factory):
    dataset = _sync(session)
    entity = master_entity_factory(name="Possibly Different Name")
    run = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="screen-exact-id",
            entity_id=entity.id,
            dataset_id=dataset.id,
            names=["Possibly Different Name"],
            identifiers={"registration": ["REG-9988"]},
            countries=["KE"],
            identity_complete=True,
            requested_by="screening-worker",
        )
    )
    assert run.outcome == "blocked"
    assert run.freeze_id is not None
    freeze = session.get(FreezeRow, run.freeze_id)
    assert freeze.active is True


def test_fuzzy_name_and_incomplete_identity_never_auto_clear(session, master_entity_factory):
    dataset = _sync(session)
    fuzzy_entity = master_entity_factory(name="Acme Trading Ltd")
    fuzzy = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="screen-fuzzy",
            entity_id=fuzzy_entity.id,
            dataset_id=dataset.id,
            names=["Acme Trading Ltd"],
            countries=["KE"],
            identity_complete=True,
            requested_by="screening-worker",
        )
    )
    assert fuzzy.outcome == "possible_match"
    incomplete_entity = master_entity_factory(name="Unrelated Sparse Identity")
    incomplete = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="screen-incomplete",
            entity_id=incomplete_entity.id,
            dataset_id=dataset.id,
            names=["Unrelated Sparse Identity"],
            identity_complete=False,
            requested_by="screening-worker",
        )
    )
    assert incomplete.outcome == "review"
    assert incomplete.freeze_id is not None


def test_complete_non_match_can_clear_and_owner_risk_propagates(session, master_entity_factory):
    dataset = _sync(session)
    owner_entity = master_entity_factory(name="Listed Owner")
    owner = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="screen-owner",
            entity_id=owner_entity.id,
            dataset_id=dataset.id,
            names=["Listed Owner"],
            identifiers={"registration": ["REG-9988"]},
            identity_complete=True,
            requested_by="screening-worker",
        )
    )
    child_entity = master_entity_factory(name="Clean Subsidiary")
    child = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="screen-child",
            entity_id=child_entity.id,
            dataset_id=dataset.id,
            names=["Clean Subsidiary"],
            identifiers={"registration": ["CLEAN-1"]},
            countries=["US"],
            identity_complete=True,
            owner_screening_run_ids=[owner.id],
            requested_by="screening-worker",
        )
    )
    assert child.outcome == "blocked"
    clean_entity = master_entity_factory(name="Clean Independent Company")
    clean = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="screen-clean",
            entity_id=clean_entity.id,
            dataset_id=dataset.id,
            names=["Clean Independent Company"],
            identifiers={"registration": ["CLEAN-2"]},
            countries=["US"],
            identity_complete=True,
            requested_by="screening-worker",
        )
    )
    assert clean.outcome == "clear"
    assert clean.freeze_id is None


def test_freeze_release_requires_independent_reviewer_and_evidence(
    session, master_entity_factory, master_claim_factory
):
    dataset = _sync(session)
    entity = master_entity_factory(name="Listed Company")
    run = ScreeningService(session).screen(
        ScreeningCreate(
            idempotency_key="screen-release",
            entity_id=entity.id,
            dataset_id=dataset.id,
            names=["Listed Company"],
            identifiers={"registration": ["REG-9988"]},
            identity_complete=True,
            requested_by="screening-worker",
        )
    )
    evidence = master_claim_factory(value="Official registry excludes the candidate", verified=True)
    with pytest.raises(ValueError, match="creator"):
        FreezeService(session).release(
            run.freeze_id,
            FreezeRelease(
                idempotency_key="release-self",
                reviewed_by="screening-worker",
                reason="Reviewed official registry evidence and excluded the candidate.",
                evidence_claim_ids=[evidence.id],
            ),
        )
    release = FreezeService(session).release(
        run.freeze_id,
        FreezeRelease(
            idempotency_key="release-independent",
            reviewed_by="compliance-reviewer",
            reason="Reviewed official registry evidence and excluded the candidate.",
            evidence_claim_ids=[evidence.id],
        ),
    )
    assert release.decision == "release"
    assert session.get(FreezeRow, run.freeze_id).active is False


def test_export_control_missing_end_use_requires_review_and_retains_rule_source(
    session, product_concept_factory, master_entity_factory
):
    dataset = ComplianceDatasetService(session).sync(
        DatasetSyncCreate(
            dataset_key="official-export-controls",
            idempotency_key="sync-export-controls",
            dataset_type="export_controls",
            source_uri="https://official.example.invalid/export-controls.json",
            publisher="Official Export Authority",
            published_at=NOW,
            license_name="Official fixture",
            entries=[
                ComplianceEntryInput(
                    external_id="EC-001",
                    entry_type="export_control",
                    programs=["DUAL-USE"],
                    fields={
                        "product_codes": ["8481"],
                        "destinations": ["KE"],
                        "restriction": "license_candidate",
                    },
                    effective_from=date(2026, 1, 1),
                )
            ],
        )
    )
    product = product_concept_factory(label="Industrial Valve")
    buyer = master_entity_factory(name="Buyer")
    result = ExportControlService(session).assess(
        ExportControlCreate(
            idempotency_key="export-assessment",
            product_concept_id=product.id,
            buyer_entity_id=buyer.id,
            dataset_id=dataset.id,
            destination_country="KE",
            product_code_candidates=[
                ProductCodeCandidate(code="848180", confidence=Decimal("0.82"))
            ],
            end_use=None,
            as_of=date(2026, 8, 31),
        )
    )
    assert result.outcome == "review_required"
    assert result.restriction_candidates_json[0]["external_id"] == "EC-001"
    assert dataset.content_hash in result.rule_version


def test_trade_requirement_candidates_keep_ambiguity_effective_dates_and_rates_from_data(
    session, product_concept_factory
):
    dataset = ComplianceDatasetService(session).sync(
        DatasetSyncCreate(
            dataset_key="official-trade-rules",
            idempotency_key="sync-trade-rules",
            dataset_type="trade_requirements",
            source_uri="https://official.example.invalid/tariff.json",
            publisher="Official Customs Authority",
            published_at=NOW,
            license_name="Official fixture",
            entries=[
                ComplianceEntryInput(
                    external_id="TARIFF-8481",
                    entry_type="tariff",
                    fields={
                        "product_codes": ["8481"],
                        "origins": ["CN"],
                        "destinations": ["KE"],
                        "tariff_rate": "0.12",
                    },
                    effective_from=date(2026, 7, 1),
                ),
                ComplianceEntryInput(
                    external_id="CERT-848180",
                    entry_type="certification",
                    fields={
                        "product_codes": ["848180"],
                        "destinations": ["KE"],
                        "certificate": "PVOC",
                    },
                    effective_from=date(2026, 1, 1),
                ),
            ],
        )
    )
    product = product_concept_factory(label="Industrial Valve")
    result = TradeRequirementService(session).assess(
        TradeRequirementCreate(
            idempotency_key="trade-requirement-assessment",
            product_concept_id=product.id,
            dataset_id=dataset.id,
            origin_country="CN",
            destination_country="KE",
            product_code_candidates=[
                ProductCodeCandidate(code="848180", confidence=Decimal("0.80")),
                ProductCodeCandidate(code="848190", confidence=Decimal("0.20")),
            ],
            as_of=date(2026, 8, 31),
        )
    )
    assert result.outcome == "review_required"
    assert result.tariff_candidates_json[0]["fields"]["tariff_rate"] == "0.12"
    assert result.certification_candidates_json[0]["fields"]["certificate"] == "PVOC"
    assert "uncertain" in result.assumptions_json[0].lower()

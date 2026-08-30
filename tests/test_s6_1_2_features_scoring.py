from datetime import UTC, datetime, timedelta

import pytest

from tradefoundry.tradealpha.contracts import (
    FeatureDefinitionCreate,
    FeatureSnapshotRequest,
    HardRule,
    ScoreRequest,
    ScoringPolicyCreate,
)
from tradefoundry.tradealpha.explanation import ExplanationService
from tradefoundry.tradealpha.features import FeatureRegistryService, FeatureSnapshotService
from tradefoundry.tradealpha.scoring import ScoreService, ScoringPolicyService


def _snapshot(session, route):
    FeatureRegistryService(session).seed_defaults()
    return FeatureSnapshotService(session).materialize(
        route.id,
        FeatureSnapshotRequest(
            idempotency_key=f"features:{route.id}", as_of=datetime.now(UTC) + timedelta(seconds=1)
        ),
    )


def test_builtin_registry_is_versioned_and_idempotent(session):
    service = FeatureRegistryService(session)
    first = service.seed_defaults()
    second = service.seed_defaults()
    assert len(first) == len(second) == 8
    assert [item.id for item in first] == [item.id for item in second]
    assert all(item.version_no == 1 and item.status == "active" for item in first)


def test_new_feature_version_deprecates_old_version(session):
    service = FeatureRegistryService(session)
    old = service.create(
        FeatureDefinitionCreate(
            feature_key="custom_signal",
            idempotency_key="custom-signal-v1",
            source_kind="derived",
            source_field="signal",
            value_type="ratio",
            calculation_ref="evidence_completeness",
            available_time_rule="created_at",
            description="First custom signal",
            created_by="sol",
        )
    )
    new = service.create(
        FeatureDefinitionCreate(
            feature_key="custom_signal",
            idempotency_key="custom-signal-v2",
            source_kind="derived",
            source_field="signal",
            value_type="ratio",
            calculation_ref="evidence_completeness",
            available_time_rule="created_at",
            description="Second custom signal",
            created_by="sol",
        )
    )
    assert old.version_no == 1 and new.version_no == 2
    assert [item.id for item in service.list_active() if item.feature_key == "custom_signal"] == [
        new.id
    ]


def test_feature_snapshot_is_pinned_and_replayable(session, deal_route_factory):
    _, route = deal_route_factory()
    first = _snapshot(session, route)
    repeated = FeatureSnapshotService(session).materialize(
        route.id,
        FeatureSnapshotRequest(idempotency_key=f"features:{route.id}", as_of=first.as_of),
    )
    assert repeated.id == first.id
    assert first.features_json["route_stage_progress"] == 0.05
    assert first.registry_hash and first.source_max_available_at <= first.as_of


def test_feature_snapshot_rejects_time_before_route_exists(session, deal_route_factory):
    _, route = deal_route_factory()
    FeatureRegistryService(session).seed_defaults()
    with pytest.raises(ValueError, match="did not exist"):
        FeatureSnapshotService(session).materialize(
            route.id,
            FeatureSnapshotRequest(
                idempotency_key="feature-before-route",
                as_of=route.created_at.replace(tzinfo=UTC) - timedelta(seconds=1),
            ),
        )


def test_rule_score_hard_veto_and_explanation(session, deal_route_factory):
    _, route = deal_route_factory()
    snapshot = _snapshot(session, route)
    policy = ScoringPolicyService(session).create(
        ScoringPolicyCreate(
            policy_key="baseline",
            idempotency_key="baseline-v1",
            name="Deterministic baseline",
            weights={"event_reliability": 2, "route_stage_progress": 1},
            hard_rules=[
                HardRule(
                    field="context.lifecycle_status",
                    operator="eq",
                    value="active",
                    reason="Fixture hard stop for active routes.",
                )
            ],
            created_by="sol",
        )
    )
    score = ScoreService(session).score(
        route.id,
        ScoreRequest(
            idempotency_key="route-score-v1",
            feature_snapshot_id=snapshot.id,
            policy_id=policy.id,
            as_of=snapshot.as_of,
        ),
    )
    explanation = ExplanationService(session).explain(score.id)
    assert score.hard_decision == "veto"
    assert 50 <= score.total_score <= 100
    assert explanation.why_high_or_low
    assert explanation.hard_constraints == ["Fixture hard stop for active routes."]
    assert explanation.most_valuable_new_evidence

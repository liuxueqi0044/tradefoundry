from tradefoundry.master.contracts import IdentifierCreate, MatchReviewRequest
from tradefoundry.master.identifiers import IdentifierResolutionService
from tradefoundry.master.matching import ProbabilisticResolutionService


def _weak_identifiers(session, entity_id, claim_factory, *, domain, phone=None):
    service = IdentifierResolutionService(session)
    service.add(
        entity_id,
        IdentifierCreate(
            scheme="domain", value=domain, strength="weak", source_claim_id=claim_factory().id
        ),
    )
    if phone:
        service.add(
            entity_id,
            IdentifierCreate(
                scheme="phone:us",
                value=phone,
                strength="weak",
                source_claim_id=claim_factory().id,
            ),
        )


def test_probability_candidates_include_feature_explanation_and_review_queue(
    session, master_entity_factory, master_claim_factory
):
    english = master_entity_factory(name="Shanghai Example Limited", attributes={"country": "CN"})
    chinese = master_entity_factory(
        name="上海示例有限公司", attributes={"country": "CN"}, risk_tier="high"
    )
    _weak_identifiers(
        session,
        english.id,
        master_claim_factory,
        domain="example.cn",
        phone="+1 415 555 2671",
    )
    _weak_identifiers(
        session,
        chinese.id,
        master_claim_factory,
        domain="example.cn",
        phone="+1 415 555 2671",
    )

    candidates = ProbabilisticResolutionService(session).resolve(chinese.id, auto_merge=True)
    candidate = next(item for item in candidates if item.candidate_entity_id == english.id)

    assert 0.55 <= candidate.probability < 0.995
    assert candidate.decision == "review"
    assert candidate.features_json["domain_exact"] == 1
    assert candidate.features_json["phone_exact"] == 1
    assert "log_odds" in candidate.features_json

    reviewed = ProbabilisticResolutionService(session).review_candidate(
        candidate.id,
        MatchReviewRequest(
            action="reject",
            reviewer="entity-reviewer",
            reason="Shared contact channel belongs to a corporate group, not one legal entity.",
        ),
    )
    assert reviewed.decision == "rejected_by_human"


def test_golden_pair_evaluation_meets_precision_and_recall_thresholds(
    session, master_entity_factory, master_claim_factory
):
    acme_a = master_entity_factory(
        name="Acme Limited",
        attributes={"address": "12 Main Street", "country": "US"},
    )
    acme_b = master_entity_factory(
        name="ACME Co Ltd",
        attributes={"address": "12 Main St.", "country": "US"},
    )
    other = master_entity_factory(
        name="Acme Hospital",
        attributes={"address": "99 Other Road", "country": "US"},
    )
    entity_domains = (
        (acme_a, "acme.example"),
        (acme_b, "acme.example"),
        (other, "hospital.example"),
    )
    for entity, domain in entity_domains:
        _weak_identifiers(session, entity.id, master_claim_factory, domain=domain)
    service = ProbabilisticResolutionService(session)
    evaluation = service.evaluate(
        [(acme_a.id, acme_b.id, True), (acme_a.id, other.id, False)], threshold=0.55
    )

    assert evaluation.precision == 1.0
    assert evaluation.recall == 1.0


def test_high_probability_pair_auto_merges(session, master_entity_factory, master_claim_factory):
    first = master_entity_factory(
        name="Exact Match Limited",
        attributes={"address": "1 Market Street", "country": "US"},
    )
    second = master_entity_factory(
        name="EXACT MATCH LTD",
        attributes={"address": "1 Market St", "country": "US"},
    )
    for entity in (first, second):
        _weak_identifiers(session, entity.id, master_claim_factory, domain="exact-match.example")
    service = ProbabilisticResolutionService(session)
    candidates = service.resolve(second.id, auto_merge=True)
    candidate = next(item for item in candidates if item.candidate_entity_id == first.id)

    assert candidate.probability >= 0.98
    assert candidate.decision == "auto_merged"
    assert candidate.merge_command_id


def test_reviewer_can_accept_queued_match(session, master_entity_factory, master_claim_factory):
    first = master_entity_factory(name="东方设备", risk_tier="high")
    second = master_entity_factory(name="Eastern Equipment", risk_tier="high")
    for entity in (first, second):
        _weak_identifiers(
            session,
            entity.id,
            master_claim_factory,
            domain="eastern.example",
            phone="+1 415 555 2671",
        )
    service = ProbabilisticResolutionService(session)
    candidate = next(
        item
        for item in service.resolve(second.id, auto_merge=True)
        if item.candidate_entity_id == first.id
    )
    reviewed = service.review_candidate(
        candidate.id,
        MatchReviewRequest(
            action="merge",
            reviewer="entity-reviewer",
            reason="Bilingual registry aliases and contacts confirm one company.",
        ),
    )

    assert reviewed.decision == "human_merged"
    assert reviewed.merge_command_id

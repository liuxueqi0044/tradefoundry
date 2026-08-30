from __future__ import annotations

import math
from collections.abc import Iterable
from uuid import uuid4

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.contracts import (
    DistinctRequest,
    MatchCandidateView,
    MatchEvaluation,
    MatchReviewRequest,
    MergeRequest,
)
from tradefoundry.master.entities import EntityService
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.models import (
    EntityAttributeRow,
    EntityIdentifierRow,
    EntityRow,
    MatchCandidateRow,
    MatchRunRow,
)
from tradefoundry.master.resolution import ResolutionService


class ProbabilisticResolutionService:
    model_version = "interpretable-logistic-v1"
    review_threshold = 0.55

    def __init__(self, session: Session):
        self.session = session
        self.entities = EntityService(session)
        self.resolution = ResolutionService(session)

    def resolve(self, entity_id: str, *, auto_merge: bool = False) -> list[MatchCandidateView]:
        query = canonical_root(self.session, entity_id)
        roots = self._roots(query.entity_type)
        snapshot = {
            "query": self.entities.profile(query.id).model_dump(mode="json"),
            "candidates": [
                self.entities.profile(root.id).model_dump(mode="json")
                for root in roots
                if root.id != query.id
            ],
        }
        snapshot_hash = payload_hash(snapshot)
        existing = self.session.scalar(
            select(MatchRunRow).where(
                MatchRunRow.query_entity_id == query.id,
                MatchRunRow.model_version == self.model_version,
                MatchRunRow.snapshot_hash == snapshot_hash,
            )
        )
        if existing is not None:
            return self._run_candidates(existing.id)
        run = MatchRunRow(
            id=str(uuid4()),
            query_entity_id=query.id,
            model_version=self.model_version,
            snapshot_hash=snapshot_hash,
            status="running",
            metrics_json={},
        )
        self.session.add(run)
        self.session.flush()
        created: list[MatchCandidateRow] = []
        for candidate in roots:
            if candidate.id == query.id:
                continue
            probability, features = self.score_pair(query.id, candidate.id)
            threshold = self._auto_threshold(query, candidate)
            decision = "rejected"
            merge_command_id = None
            if probability >= threshold and auto_merge:
                older, newer = sorted(
                    (query, candidate), key=lambda value: (value.created_at, value.id)
                )
                try:
                    command = self.resolution.merge(
                        MergeRequest(
                            winner_entity_id=older.id,
                            loser_entity_id=newer.id,
                            idempotency_key=(
                                f"probabilistic:{self.model_version}:"
                                + payload_hash(sorted((query.id, candidate.id)))
                            ),
                            decision_source="probabilistic_model",
                            actor="system:entity-matcher",
                            reason=(f"probability {probability:.6f} met threshold {threshold:.6f}"),
                            score=probability,
                            features=features,
                        )
                    )
                    decision = "auto_merged"
                    merge_command_id = command.id
                except ValueError:
                    decision = "review"
            elif probability >= self.review_threshold:
                decision = "review"
            row = MatchCandidateRow(
                id=str(uuid4()),
                run_id=run.id,
                query_entity_id=query.id,
                candidate_entity_id=candidate.id,
                probability=probability,
                features_json={**features, "auto_merge_threshold": threshold},
                decision=decision,
                merge_command_id=merge_command_id,
            )
            self.session.add(row)
            created.append(row)
        run.status = "succeeded"
        run.metrics_json = {
            "candidate_count": len(created),
            "review_count": sum(item.decision == "review" for item in created),
            "auto_merge_count": sum(item.decision == "auto_merged" for item in created),
        }
        self.session.commit()
        return [MatchCandidateView.model_validate(row) for row in created]

    def score_pair(self, left_id: str, right_id: str) -> tuple[float, dict[str, float]]:
        left = self._features(left_id)
        right = self._features(right_id)
        name_similarity = self._maximum_similarity(left["names"], right["names"])
        address_similarity = self._maximum_similarity(left["addresses"], right["addresses"])
        domain_exact = float(bool(left["domains"] & right["domains"]))
        phone_exact = float(bool(left["phones"] & right["phones"]))
        country_exact = float(bool(left["countries"] & right["countries"]))
        features = {
            "name_similarity": name_similarity,
            "address_similarity": address_similarity,
            "domain_exact": domain_exact,
            "phone_exact": phone_exact,
            "country_exact": country_exact,
        }
        log_odds = (
            -6.0
            + 5.0 * name_similarity
            + 2.0 * address_similarity
            + 3.0 * domain_exact
            + 3.0 * phone_exact
            + 0.5 * country_exact
        )
        probability = 1.0 / (1.0 + math.exp(-log_odds))
        return probability, {**features, "log_odds": log_odds}

    def evaluate(
        self, labelled_pairs: Iterable[tuple[str, str, bool]], *, threshold: float = 0.55
    ) -> MatchEvaluation:
        tp = fp = fn = tn = 0
        for left_id, right_id, expected in labelled_pairs:
            probability, _ = self.score_pair(left_id, right_id)
            predicted = probability >= threshold
            if predicted and expected:
                tp += 1
            elif predicted:
                fp += 1
            elif expected:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return MatchEvaluation(
            threshold=threshold,
            true_positive=tp,
            false_positive=fp,
            false_negative=fn,
            true_negative=tn,
            precision=precision,
            recall=recall,
        )

    def review_candidate(
        self, candidate_id: str, request: MatchReviewRequest
    ) -> MatchCandidateView:
        candidate = self.session.get(MatchCandidateRow, candidate_id)
        if candidate is None:
            raise LookupError(f"match candidate {candidate_id} not found")
        if candidate.decision in {"human_merged", "rejected_by_human"}:
            return MatchCandidateView.model_validate(candidate)
        if request.action == "merge":
            left = canonical_root(self.session, candidate.query_entity_id)
            right = canonical_root(self.session, candidate.candidate_entity_id)
            older, newer = sorted((left, right), key=lambda item: (item.created_at, item.id))
            command = self.resolution.merge(
                MergeRequest(
                    winner_entity_id=older.id,
                    loser_entity_id=newer.id,
                    idempotency_key=f"human-match:{candidate.id}",
                    decision_source="human_match_review",
                    actor=request.reviewer,
                    reason=request.reason,
                    score=candidate.probability,
                    features=candidate.features_json,
                )
            )
            candidate.decision = "human_merged"
            candidate.merge_command_id = command.id
        else:
            self.resolution.mark_distinct(
                DistinctRequest(
                    left_entity_id=candidate.query_entity_id,
                    right_entity_id=candidate.candidate_entity_id,
                    actor=request.reviewer,
                    reason=request.reason,
                )
            )
            candidate.decision = "rejected_by_human"
        self.session.commit()
        return MatchCandidateView.model_validate(candidate)

    def _features(self, entity_id: str) -> dict[str, set[str]]:
        profile = self.entities.profile(entity_id)
        members = profile.member_ids
        attributes = self.session.scalars(
            select(EntityAttributeRow).where(EntityAttributeRow.entity_id.in_(members))
        ).all()
        identifiers = self.session.scalars(
            select(EntityIdentifierRow).where(EntityIdentifierRow.entity_id.in_(members))
        ).all()
        return {
            "names": {alias.normalized_value for alias in profile.aliases},
            "addresses": {
                str(item.normalized_value_json)
                for item in attributes
                if item.field_name == "address"
            },
            "countries": {
                str(item.normalized_value_json)
                for item in attributes
                if item.field_name in {"country", "country_code"}
            },
            "domains": {item.normalized_value for item in identifiers if item.scheme == "domain"},
            "phones": {
                item.normalized_value for item in identifiers if item.scheme.startswith("phone")
            },
        }

    def _roots(self, entity_type: str) -> list[EntityRow]:
        entities = self.session.scalars(
            select(EntityRow).where(EntityRow.entity_type == entity_type)
        ).all()
        roots = {
            canonical_root(self.session, entity.id).id: canonical_root(self.session, entity.id)
            for entity in entities
        }
        return sorted(roots.values(), key=lambda value: (value.created_at, value.id))

    @staticmethod
    def _maximum_similarity(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return max(fuzz.WRatio(a, b) for a in left for b in right) / 100.0

    @staticmethod
    def _auto_threshold(left: EntityRow, right: EntityRow) -> float:
        if "critical" in {left.risk_tier, right.risk_tier}:
            return 0.999
        if "high" in {left.risk_tier, right.risk_tier}:
            return 0.995
        if left.entity_type == "person":
            return 0.995
        return 0.98

    def _run_candidates(self, run_id: str) -> list[MatchCandidateView]:
        rows = self.session.scalars(
            select(MatchCandidateRow)
            .where(MatchCandidateRow.run_id == run_id)
            .order_by(MatchCandidateRow.probability.desc())
        ).all()
        return [MatchCandidateView.model_validate(row) for row in rows]

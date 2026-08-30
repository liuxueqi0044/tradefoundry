from __future__ import annotations

import re

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.bilateral.common import (
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.bilateral.contracts import (
    IntentClassifyRequest,
    InteractionIntake,
    MessageDraftCreate,
    QualificationCreate,
)
from tradefoundry.bilateral.models import (
    BuyerProfileRow,
    ContactAffiliationRow,
    ContactRow,
    EligibilityDecisionRow,
    IntentAssessmentRow,
    InteractionReviewQueueRow,
    InteractionRow,
    MessageDraftRow,
    QualificationSnapshotRow,
)
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash


class MessageDraftService:
    ASSERTION_LABELS = {
        "customer": "customer reference",
        "certification": "certification",
        "price": "price",
        "delivery": "delivery commitment",
    }

    def __init__(self, session: Session):
        self.session = session

    def create(self, route_id: str, request: MessageDraftCreate) -> MessageDraftRow:
        if request.proposed_subject is not None or request.proposed_body is not None:
            raise ValueError(
                "free-form proposed message text is disabled; use the evidence-grounded template"
            )
        require_row(self.session, DealRouteRow, route_id, "route")
        require_row(self.session, BuyerProfileRow, request.buyer_profile_id, "buyer profile")
        require_row(self.session, ContactRow, request.contact_id, "contact")
        eligibility = require_row(
            self.session,
            EligibilityDecisionRow,
            request.eligibility_decision_id,
            "eligibility decision",
        )
        if eligibility.contact_id != request.contact_id:
            raise ValueError("eligibility decision belongs to another contact")
        if eligibility.decision != "allow":
            raise ValueError("a sendable draft cannot be generated for an ineligible contact")
        affiliation = self.session.scalar(
            select(ContactAffiliationRow).where(
                ContactAffiliationRow.contact_id == request.contact_id,
                ContactAffiliationRow.buyer_profile_id == request.buyer_profile_id,
            )
        )
        if affiliation is None:
            raise ValueError("contact has no evidenced affiliation with this buyer")
        request_hash = request_fingerprint(
            {"operation": "message_draft.create", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, MessageDraftRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing

        context_items = [*request.buyer_context, *request.capability_context]
        claims = {
            item.claim_id: require_row(self.session, ClaimRow, item.claim_id, "context Claim")
            for item in context_items
        }
        rejected = [claim.id for claim in claims.values() if claim.status == "rejected"]
        if rejected:
            raise ValueError(f"rejected Claims cannot ground a draft: {', '.join(rejected)}")
        for item in context_items:
            evidence_value = str(claims[item.claim_id].value_json).strip().casefold()
            if evidence_value and evidence_value not in item.text.casefold():
                raise ValueError(
                    f"context text is not grounded in Claim {item.claim_id}'s recorded value"
                )
        required_confirmations = [
            f"Confirm unverified Claim {claim.id} ({claim.field_path})."
            for claim in claims.values()
            if claim.status != "verified"
        ]
        evidence_text = " ".join(
            [item.text for item in context_items]
            + [str(claim.value_json) for claim in claims.values()]
        ).casefold()
        prohibited_findings: list[str] = []
        for key, label in self.ASSERTION_LABELS.items():
            asserted_value = request.assertions.get(key)
            if not asserted_value:
                required_confirmations.append(f"Human must confirm any {label} before sending.")
            elif asserted_value.casefold() not in evidence_text:
                prohibited_findings.append(f"unsupported_{key}:{asserted_value}")
        buyer_summary = "；".join(item.text for item in request.buyer_context)
        capability_summary = "；".join(item.text for item in request.capability_context)
        subject = f"关于 {buyer_summary[:60]} 的供应协作建议"
        body = (
            f"您好，\n\n我们注意到贵方的相关背景：{buyer_summary}。\n"
            f"目前可核实的供应能力包括：{capability_summary}。\n"
            f"建议下一步：{request.desired_next_step}\n\n"
            "本邮件中的价格、认证和交付条件仅在书面确认后生效。"
        )
        version_no = (
            self.session.scalar(
                select(func.max(MessageDraftRow.version_no)).where(
                    MessageDraftRow.route_id == route_id,
                    MessageDraftRow.draft_key == request.draft_key,
                )
            )
            or 0
        ) + 1
        content_hash = payload_hash({"subject": subject, "body": body})
        row = MessageDraftRow(
            id=new_id(),
            route_id=route_id,
            buyer_profile_id=request.buyer_profile_id,
            contact_id=request.contact_id,
            eligibility_decision_id=request.eligibility_decision_id,
            draft_key=request.draft_key,
            version_no=version_no,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            subject=subject,
            body=body,
            buyer_context_json=[item.model_dump(mode="json") for item in request.buyer_context],
            capability_context_json=[
                item.model_dump(mode="json") for item in request.capability_context
            ],
            context_claim_ids_json=sorted(claims),
            required_confirmations_json=sorted(set(required_confirmations)),
            prohibited_findings_json=prohibited_findings,
            content_hash=content_hash,
            status="draft",
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return row


class InteractionService:
    def __init__(self, session: Session):
        self.session = session

    def intake(self, request: InteractionIntake) -> InteractionRow:
        request_hash = request_fingerprint({"operation": "interaction.intake"}, request)
        existing = self.session.scalar(
            select(InteractionRow).where(
                InteractionRow.external_message_id == request.external_message_id
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("external_message_id was reused with different content")
            return existing
        if request.contact_id:
            require_row(self.session, ContactRow, request.contact_id, "contact")
        route_id, link_method, link_confidence, candidate_routes = self._link_route(request)
        status = "linked" if route_id else "needs_review"
        row = InteractionRow(
            id=new_id(),
            external_message_id=request.external_message_id,
            request_hash=request_hash,
            route_id=route_id,
            contact_id=request.contact_id,
            thread_key=request.thread_key,
            channel=request.channel.value,
            direction=request.direction,
            raw_artifact_ref=request.raw_artifact_ref,
            raw_hash=request.raw_hash,
            body_text=request.body_text,
            metadata_json=request.metadata,
            attachment_refs_json=request.attachment_refs,
            link_method=link_method,
            link_confidence=link_confidence,
            status=status,
            occurred_at=request.occurred_at,
        )
        self.session.add(row)
        self.session.flush()
        if route_id is None:
            self.session.add(
                InteractionReviewQueueRow(
                    id=new_id(),
                    interaction_id=row.id,
                    reason="No unambiguous explicit route or existing thread link.",
                    candidate_routes_json=candidate_routes,
                    status="open",
                )
            )
        self.session.commit()
        return row

    def _link_route(self, request: InteractionIntake):
        if request.explicit_route_id:
            require_row(self.session, DealRouteRow, request.explicit_route_id, "route")
            return request.explicit_route_id, "explicit_route", 1.0, []
        if request.thread_key:
            linked_routes = list(
                self.session.scalars(
                    select(InteractionRow.route_id)
                    .where(
                        InteractionRow.thread_key == request.thread_key,
                        InteractionRow.route_id.is_not(None),
                    )
                    .distinct()
                ).all()
            )
            if len(linked_routes) == 1:
                return linked_routes[0], "exact_thread", 0.99, []
        routes = self.session.scalars(
            select(DealRouteRow).where(DealRouteRow.lifecycle_status == "active")
        ).all()
        haystack = f"{request.metadata.get('subject', '')} {request.body_text}"
        candidates = sorted(
            [
                {
                    "route_id": route.id,
                    "route_key": route.route_key,
                    "score": round(fuzz.partial_ratio(route.route_key, haystack) / 100, 4),
                }
                for route in routes
            ],
            key=lambda item: (-item["score"], item["route_id"]),
        )[:3]
        return None, "unresolved", 0.0, candidates


class IntentClassificationService:
    VERSION = "deterministic-rules-v1"
    POSITIVE = ("interested", "please quote", "send quote", "可以", "有兴趣", "请报价")
    NEGATIVE = ("not interested", "no thanks", "do not contact", "不感兴趣", "不用联系")
    OBJECTIONS = {
        "price": ("price", "expensive", "价格", "太贵"),
        "delivery": ("lead time", "delivery", "交期", "发货"),
        "payment": ("payment", "credit", "账期", "付款"),
        "certification": ("certificate", "certification", "认证", "证书"),
        "specification": ("specification", "spec", "规格", "参数"),
    }

    def __init__(self, session: Session):
        self.session = session

    def classify(self, interaction_id: str, request: IntentClassifyRequest) -> IntentAssessmentRow:
        interaction = require_row(self.session, InteractionRow, interaction_id, "interaction")
        request_hash = request_fingerprint(
            {"operation": "interaction.classify", "interaction_id": interaction_id}, request
        )
        existing = idempotent_row(
            self.session, IntentAssessmentRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        text = interaction.body_text.casefold()
        positive = [token for token in self.POSITIVE if token in text]
        negative = [token for token in self.NEGATIVE if token in text]
        questions = [
            value.strip()
            for value in re.split(r"(?<=[?？])", interaction.body_text)
            if value.strip().endswith(("?", "？"))
        ]
        objections = [
            name
            for name, tokens in self.OBJECTIONS.items()
            if any(token in text for token in tokens)
        ]
        if negative:
            intent, sentiment, confidence = "rejection", "negative", 0.92
        elif positive:
            intent, sentiment, confidence = "positive_interest", "positive", 0.9
        elif questions or objections:
            intent, sentiment, confidence = "clarification", "neutral", 0.8
        else:
            intent, sentiment, confidence = "unknown", "neutral", 0.4
        row = IntentAssessmentRow(
            id=new_id(),
            interaction_id=interaction_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            classifier_version=self.VERSION,
            intent=intent,
            questions_json=questions,
            objections_json=objections,
            sentiment=sentiment,
            confidence=confidence,
            needs_review=confidence < request.confidence_threshold,
        )
        self.session.add(row)
        self.session.commit()
        return row


class QualificationService:
    FIELDS = (
        "quantity",
        "specification",
        "budget",
        "timing",
        "authority",
        "procurement_process",
    )

    def __init__(self, session: Session):
        self.session = session

    def snapshot(self, route_id: str, request: QualificationCreate) -> QualificationSnapshotRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        request_hash = request_fingerprint(
            {"operation": "qualification.snapshot", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, QualificationSnapshotRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        values: dict[str, dict | None] = {}
        source_ids: set[str] = set()
        for field in self.FIELDS:
            value = getattr(request, field)
            if value is None:
                values[field] = None
                continue
            interaction = require_row(
                self.session, InteractionRow, value.source_interaction_id, "source interaction"
            )
            if interaction.route_id != route_id:
                raise ValueError(f"{field} source interaction belongs to another route")
            values[field] = value.model_dump(mode="json")
            source_ids.add(value.source_interaction_id)
        row = QualificationSnapshotRow(
            id=new_id(),
            route_id=route_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            quantity_json=values["quantity"],
            specification_json=values["specification"],
            budget_json=values["budget"],
            timing_json=values["timing"],
            authority_json=values["authority"],
            procurement_process_json=values["procurement_process"],
            missing_fields_json=[field for field in self.FIELDS if values[field] is None],
            source_interaction_ids_json=sorted(source_ids),
        )
        self.session.add(row)
        self.session.commit()
        return row

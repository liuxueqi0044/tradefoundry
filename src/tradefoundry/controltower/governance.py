from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.controltower.common import (
    aware,
    idempotent_row,
    money,
    new_id,
    request_fingerprint,
    require_row,
    utcnow,
)
from tradefoundry.controltower.contracts import (
    ApprovalDecisionCreate,
    ApprovalRequestCreate,
    ExecutionConsumption,
    ExecutionReservation,
    ExecutionTokenIssue,
    ExecutionTokenView,
    FreezeRelease,
    RiskCaseOpen,
)
from tradefoundry.controltower.models import (
    ApprovalDecisionRow,
    ApprovalRequestRow,
    ApprovalStepRow,
    ExecutionTokenRow,
    FreezeReleaseRow,
    FreezeRow,
    PolicyDecisionRow,
    RiskCaseRow,
)
from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash


class FreezeService:
    def __init__(self, session: Session):
        self.session = session

    def open_case(self, request: RiskCaseOpen) -> RiskCaseRow:
        request_hash = request_fingerprint({"operation": "risk.case.open"}, request)
        existing = idempotent_row(self.session, RiskCaseRow, request.idempotency_key, request_hash)
        if existing is not None:
            return existing
        if self.session.scalar(select(RiskCaseRow).where(RiskCaseRow.case_key == request.case_key)):
            raise ValueError("risk case key already exists")
        for claim_id in request.evidence_claim_ids:
            require_row(self.session, ClaimRow, claim_id, "evidence claim")
        subjects = sorted(set(request.subject_refs))
        scopes = sorted(set(request.scopes))
        case = RiskCaseRow(
            id=new_id(),
            case_key=request.case_key,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            case_type=request.case_type,
            severity=request.severity,
            source_reference=request.source_reference,
            subject_refs_json=subjects,
            status="open",
            reason=request.reason,
            evidence_claim_ids_json=request.evidence_claim_ids,
            opened_by=request.opened_by,
        )
        self.session.add(case)
        self.session.flush()
        for subject in subjects:
            for scope in scopes:
                self.session.add(
                    FreezeRow(
                        id=new_id(),
                        risk_case_id=case.id,
                        subject_ref=subject,
                        scope=scope,
                        reason=request.reason,
                        active=True,
                        created_by=request.opened_by,
                    )
                )
        self.session.commit()
        return case

    def active_freezes(self, subject_refs: list[str], action: str) -> list[FreezeRow]:
        subjects = sorted(set(subject_refs))
        if not subjects:
            return []
        return list(
            self.session.scalars(
                select(FreezeRow).where(
                    FreezeRow.subject_ref.in_(subjects),
                    FreezeRow.active.is_(True),
                    FreezeRow.scope.in_(["*", "external_action", action]),
                )
            )
        )

    def require_unfrozen(self, subject_refs: list[str], action: str) -> None:
        freezes = self.active_freezes(subject_refs, action)
        if freezes:
            refs = ", ".join(sorted({row.id for row in freezes}))
            raise ValueError(f"action is blocked by active freeze(s): {refs}")

    def release(self, freeze_id: str, request: FreezeRelease) -> FreezeReleaseRow:
        request_hash = request_fingerprint(
            {"operation": "risk.freeze.release", "freeze_id": freeze_id}, request
        )
        existing = idempotent_row(
            self.session, FreezeReleaseRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        freeze = require_row(self.session, FreezeRow, freeze_id, "freeze")
        if not freeze.active:
            raise ValueError("freeze has already been released")
        case = require_row(self.session, RiskCaseRow, freeze.risk_case_id, "risk case")
        if request.reviewed_by == case.opened_by:
            raise ValueError("freeze creator cannot release their own freeze")
        for claim_id in request.evidence_claim_ids:
            require_row(self.session, ClaimRow, claim_id, "evidence claim")
        row = FreezeReleaseRow(
            id=new_id(),
            freeze_id=freeze.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            reviewed_by=request.reviewed_by,
            reason=request.reason,
            evidence_claim_ids_json=request.evidence_claim_ids,
            decision="release",
        )
        freeze.active = False
        freeze.released_at = utcnow()
        self.session.add(row)
        self.session.flush()
        remaining = self.session.scalar(
            select(func.count(FreezeRow.id)).where(
                FreezeRow.risk_case_id == case.id, FreezeRow.active.is_(True)
            )
        )
        if not remaining:
            case.status = "closed"
            case.closed_at = utcnow()
        self.session.commit()
        return row


class ApprovalService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: ApprovalRequestCreate) -> ApprovalRequestRow:
        request_hash = request_fingerprint({"operation": "risk.approval.create"}, request)
        existing = idempotent_row(
            self.session, ApprovalRequestRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return self._refresh(existing)
        policy = require_row(
            self.session, PolicyDecisionRow, request.policy_decision_id, "policy decision"
        )
        if policy.decision != "require_approval":
            raise ValueError("approval request requires a require_approval policy decision")
        if policy.actor != request.requester:
            raise ValueError("approval requester must match the evaluated policy actor")
        params_hash = payload_hash(request.params)
        evaluated_params_hash = policy.context_snapshot_json.get("context", {}).get("params_hash")
        if evaluated_params_hash != params_hash:
            raise ValueError("approval parameters do not match the policy-evaluated parameters")
        expires_at = aware(request.expires_at)
        if expires_at <= aware(utcnow()):
            raise ValueError("approval request expiry must be in the future")
        chain = policy.obligations_json.get("approval_chain")
        if not isinstance(chain, list) or not chain:
            raise ValueError("policy decision is missing a reviewed approval chain")
        normalized_chain: list[dict] = []
        for raw in chain:
            role = raw.get("role") if isinstance(raw, dict) else None
            approvals = raw.get("approvals", 1) if isinstance(raw, dict) else None
            if (
                not isinstance(role, str)
                or not role
                or not isinstance(approvals, int)
                or approvals < 1
            ):
                raise ValueError("approval chain contains an invalid step")
            normalized_chain.append({"role": role, "approvals": approvals})
        row = ApprovalRequestRow(
            id=new_id(),
            policy_decision_id=policy.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            requester=request.requester,
            action=policy.action,
            resource_type=policy.resource_type,
            resource_id=policy.resource_id,
            params_hash=params_hash,
            subject_refs_json=sorted(set(request.subject_refs)),
            risk_tier=request.risk_tier,
            amount=money(request.amount.amount) if request.amount else None,
            currency=request.amount.currency if request.amount else None,
            separation_of_duties=bool(policy.obligations_json.get("separation_of_duties", True)),
            expires_at=expires_at,
            status="pending",
        )
        self.session.add(row)
        self.session.flush()
        for sequence, step in enumerate(normalized_chain, start=1):
            self.session.add(
                ApprovalStepRow(
                    id=new_id(),
                    approval_request_id=row.id,
                    sequence_no=sequence,
                    required_role=step["role"],
                    approvals_required=step["approvals"],
                    status="pending" if sequence == 1 else "queued",
                )
            )
        self.session.commit()
        return row

    def get(self, approval_request_id: str) -> ApprovalRequestRow:
        return self._refresh(
            require_row(self.session, ApprovalRequestRow, approval_request_id, "approval request")
        )

    def steps(self, approval_request_id: str) -> list[ApprovalStepRow]:
        self.get(approval_request_id)
        return list(
            self.session.scalars(
                select(ApprovalStepRow)
                .where(ApprovalStepRow.approval_request_id == approval_request_id)
                .order_by(ApprovalStepRow.sequence_no)
            )
        )

    def decide(
        self, approval_request_id: str, request: ApprovalDecisionCreate
    ) -> ApprovalRequestRow:
        request_hash = request_fingerprint(
            {"operation": "risk.approval.decide", "approval_id": approval_request_id},
            request,
        )
        existing = idempotent_row(
            self.session, ApprovalDecisionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return self.get(existing.approval_request_id)
        approval = self.get(approval_request_id)
        if approval.status != "pending":
            raise ValueError(f"approval request is {approval.status}")
        step = self.session.scalar(
            select(ApprovalStepRow).where(
                ApprovalStepRow.approval_request_id == approval.id,
                ApprovalStepRow.status == "pending",
            )
        )
        if step is None:
            raise ValueError("approval request has no pending step")
        if step.required_role not in request.approver_roles:
            raise ValueError(f"approver lacks required role {step.required_role}")
        if approval.separation_of_duties and request.approver == approval.requester:
            raise ValueError("requester cannot approve their own restricted action")
        for claim_id in request.evidence_claim_ids:
            require_row(self.session, ClaimRow, claim_id, "evidence claim")
        decision = ApprovalDecisionRow(
            id=new_id(),
            approval_request_id=approval.id,
            approval_step_id=step.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            approver=request.approver,
            approver_roles_json=sorted(set(request.approver_roles)),
            decision=request.decision,
            reason=request.reason,
            evidence_claim_ids_json=request.evidence_claim_ids,
        )
        self.session.add(decision)
        self.session.flush()
        if request.decision == "reject":
            step.status = "rejected"
            approval.status = "rejected"
            approval.resolved_at = utcnow()
        else:
            approval_count = self.session.scalar(
                select(func.count(ApprovalDecisionRow.id)).where(
                    ApprovalDecisionRow.approval_step_id == step.id,
                    ApprovalDecisionRow.decision == "approve",
                )
            )
            if approval_count >= step.approvals_required:
                step.status = "approved"
                next_step = self.session.scalar(
                    select(ApprovalStepRow).where(
                        ApprovalStepRow.approval_request_id == approval.id,
                        ApprovalStepRow.sequence_no == step.sequence_no + 1,
                    )
                )
                if next_step is None:
                    approval.status = "approved"
                    approval.resolved_at = utcnow()
                else:
                    next_step.status = "pending"
        self.session.commit()
        return approval

    def _refresh(self, approval: ApprovalRequestRow) -> ApprovalRequestRow:
        if approval.status == "pending" and aware(approval.expires_at) <= aware(utcnow()):
            approval.status = "expired"
            approval.resolved_at = utcnow()
            for step in self.session.scalars(
                select(ApprovalStepRow).where(
                    ApprovalStepRow.approval_request_id == approval.id,
                    ApprovalStepRow.status.in_(["pending", "queued"]),
                )
            ):
                step.status = "expired"
            self.session.commit()
        return approval


class ExecutionTokenService:
    def __init__(self, session: Session, freeze_service: FreezeService | None = None):
        self.session = session
        self.freezes = freeze_service or FreezeService(session)

    def issue(self, request: ExecutionTokenIssue) -> ExecutionTokenView:
        approval = ApprovalService(self.session).get(request.approval_request_id)
        if approval.status != "approved":
            raise ValueError("execution token requires an approved request")
        if payload_hash(request.params) != approval.params_hash:
            raise ValueError("execution token parameters differ from the approved parameters")
        if self.session.scalar(
            select(ExecutionTokenRow).where(ExecutionTokenRow.approval_request_id == approval.id)
        ):
            raise ValueError("approved request has already issued its one execution token")
        self.freezes.require_unfrozen(approval.subject_refs_json, approval.action)
        now = utcnow()
        expires_at = min(
            aware(approval.expires_at), aware(now) + timedelta(seconds=request.ttl_seconds)
        )
        if expires_at <= aware(now):
            raise ValueError("approval is expired")
        raw_token = secrets.token_urlsafe(32)
        row = ExecutionTokenRow(
            id=new_id(),
            approval_request_id=approval.id,
            token_hash=payload_hash(raw_token),
            action=approval.action,
            resource_type=approval.resource_type,
            resource_id=approval.resource_id,
            params_hash=approval.params_hash,
            params_json=request.params,
            subject_refs_json=approval.subject_refs_json,
            issued_by=request.issued_by,
            expires_at=expires_at,
            state="issued",
        )
        self.session.add(row)
        self.session.commit()
        return ExecutionTokenView(
            token=raw_token,
            token_id=row.id,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            params_hash=row.params_hash,
            subject_refs=row.subject_refs_json,
            expires_at=row.expires_at,
        )

    def reserve(self, request: ExecutionReservation) -> ExecutionTokenRow:
        row = self._find(request.token)
        if row.state == "consumed":
            raise ValueError("execution token has already been consumed")
        if aware(row.expires_at) <= aware(utcnow()):
            row.state = "expired"
            self.session.commit()
            raise ValueError("execution token has expired")
        if (
            row.action != request.action
            or row.resource_type != request.resource_type
            or row.resource_id != request.resource_id
            or row.params_hash != payload_hash(request.params)
        ):
            raise ValueError("execution token is not bound to this action and parameter set")
        self.freezes.require_unfrozen(row.subject_refs_json, row.action)
        if row.state == "reserved":
            if row.reservation_effect_key != request.effect_key:
                raise ValueError("execution token is reserved for a different effect")
            return row
        if row.state != "issued":
            raise ValueError(f"execution token cannot be reserved from state {row.state}")
        row.state = "reserved"
        row.reservation_effect_key = request.effect_key
        row.reserved_at = utcnow()
        self.session.commit()
        return row

    def inspect(self, raw_token: str) -> ExecutionTokenRow:
        row = self._find(raw_token)
        if row.state == "consumed":
            raise ValueError("execution token has already been consumed")
        if aware(row.expires_at) <= aware(utcnow()):
            row.state = "expired"
            self.session.commit()
            raise ValueError("execution token has expired")
        if row.state not in {"issued", "reserved"}:
            raise ValueError(f"execution token is not executable from state {row.state}")
        self.freezes.require_unfrozen(row.subject_refs_json, row.action)
        return row

    def consume(self, request: ExecutionConsumption) -> ExecutionTokenRow:
        row = self._find(request.token)
        if row.state == "consumed":
            if (
                row.reservation_effect_key == request.effect_key
                and row.execution_reference == request.execution_reference
            ):
                return row
            raise ValueError("execution token has already been consumed")
        if row.state != "reserved" or row.reservation_effect_key != request.effect_key:
            raise ValueError("execution token was not reserved for this effect")
        row.state = "consumed"
        row.consumed_at = utcnow()
        row.execution_reference = request.execution_reference
        self.session.commit()
        return row

    def _find(self, raw_token: str) -> ExecutionTokenRow:
        row = self.session.scalar(
            select(ExecutionTokenRow).where(ExecutionTokenRow.token_hash == payload_hash(raw_token))
        )
        if row is None:
            raise ValueError("execution token is invalid")
        return row

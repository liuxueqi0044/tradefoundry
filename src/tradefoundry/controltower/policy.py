from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.controltower.common import (
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
    utcnow,
)
from tradefoundry.controltower.contracts import (
    Decision,
    PolicyBundleCreate,
    PolicyCondition,
    PolicyDecisionCreate,
)
from tradefoundry.controltower.models import PolicyBundleRow, PolicyDecisionRow
from tradefoundry.ingestion.hashing import payload_hash


@dataclass(frozen=True)
class EvaluationResult:
    decision: str
    reasons: list[str]
    obligations: dict[str, Any]
    matched_rule_key: str | None
    policy_version: str | None = None
    backend_decision_id: str | None = None


class ExternalPolicyEvaluator(Protocol):
    def evaluate(self, input_document: dict[str, Any]) -> EvaluationResult: ...


class OpaPolicyEvaluator:
    """Thin OPA REST adapter; deployment and policy bundles stay outside this package."""

    def __init__(
        self,
        base_url: str,
        decision_path: str,
        *,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.decision_path = decision_path.strip("/")
        self.client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def evaluate(self, input_document: dict[str, Any]) -> EvaluationResult:
        response = self.client.post(
            f"{self.base_url}/v1/data/{self.decision_path}", json={"input": input_document}
        )
        response.raise_for_status()
        body = response.json()
        result = body.get("result")
        if not isinstance(result, dict):
            raise ValueError("OPA response did not contain a structured result")
        decision = result.get("decision")
        if decision not in {value.value for value in Decision}:
            raise ValueError("OPA returned an unsupported policy decision")
        return EvaluationResult(
            decision=decision,
            reasons=list(result.get("reasons") or []),
            obligations=dict(result.get("obligations") or {}),
            matched_rule_key=result.get("matched_rule_key"),
            policy_version=result.get("revision") or body.get("revision"),
            backend_decision_id=body.get("decision_id") or result.get("decision_id"),
        )


class PolicyBundleService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: PolicyBundleCreate) -> PolicyBundleRow:
        request_hash = request_fingerprint({"operation": "risk.policy_bundle.create"}, request)
        existing = idempotent_row(
            self.session, PolicyBundleRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        latest = self.session.scalar(
            select(PolicyBundleRow)
            .where(PolicyBundleRow.bundle_key == request.bundle_key)
            .order_by(PolicyBundleRow.version_no.desc())
        )
        rules = [rule.model_dump(mode="json") for rule in request.rules]
        rule_keys = [rule["rule_key"] for rule in rules]
        if len(rule_keys) != len(set(rule_keys)):
            raise ValueError("policy rule keys must be unique within a bundle")
        row = PolicyBundleRow(
            id=new_id(),
            bundle_key=request.bundle_key,
            version_no=1 if latest is None else latest.version_no + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            backend=request.backend,
            rules_json=rules,
            content_hash=payload_hash(rules),
            external_revision=request.external_revision,
            status="draft",
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def activate(self, bundle_id: str) -> PolicyBundleRow:
        bundle = require_row(self.session, PolicyBundleRow, bundle_id, "policy bundle")
        if bundle.status == "active":
            return bundle
        active = self.session.scalar(
            select(PolicyBundleRow).where(
                PolicyBundleRow.bundle_key == bundle.bundle_key,
                PolicyBundleRow.status == "active",
            )
        )
        if active is not None:
            active.status = "superseded"
        bundle.status = "active"
        bundle.activated_at = utcnow()
        self.session.commit()
        return bundle


def _path(document: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _matches(condition: PolicyCondition, document: dict[str, Any]) -> bool:
    exists, actual = _path(document, condition.path)
    operator = condition.operator
    expected = condition.value
    if operator == "exists":
        return exists is bool(expected)
    if not exists:
        return False
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return actual in expected
    if operator == "not_in":
        return actual not in expected
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "contains":
        return expected in actual
    raise ValueError(f"unsupported policy operator {operator}")


class PolicyEngine:
    RESTRICTIVENESS = {
        Decision.DENY.value: 0,
        Decision.REQUIRE_APPROVAL.value: 1,
        Decision.ALLOW.value: 2,
    }

    def __init__(
        self,
        session: Session,
        *,
        external_evaluators: dict[str, ExternalPolicyEvaluator] | None = None,
    ):
        self.session = session
        self.external_evaluators = external_evaluators or {}

    def decide(self, request: PolicyDecisionCreate) -> PolicyDecisionRow:
        request_hash = request_fingerprint({"operation": "risk.policy.decide"}, request)
        existing = idempotent_row(
            self.session, PolicyDecisionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        bundle = self.session.scalar(
            select(PolicyBundleRow).where(
                PolicyBundleRow.bundle_key == request.bundle_key,
                PolicyBundleRow.status == "active",
            )
        )
        if bundle is None:
            raise ValueError(f"no active policy bundle for {request.bundle_key}")
        document = {
            "actor": {"id": request.actor, "roles": sorted(request.actor_roles)},
            "action": request.action,
            "resource": {"type": request.resource_type, "id": request.resource_id},
            "context": request.context,
        }
        if bundle.backend == "local":
            result = self._evaluate_local(bundle, document)
        else:
            evaluator = self.external_evaluators.get(bundle.bundle_key)
            if evaluator is None:
                raise ValueError("OPA policy backend is not configured")
            result = evaluator.evaluate(document)
        context_hash = payload_hash(document)
        policy_version = result.policy_version or f"{bundle.bundle_key}:v{bundle.version_no}"
        row = PolicyDecisionRow(
            id=new_id(),
            bundle_id=bundle.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            actor=request.actor,
            actor_roles_json=sorted(request.actor_roles),
            action=request.action,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            context_hash=context_hash,
            context_snapshot_json=document,
            decision=result.decision,
            reasons_json=result.reasons,
            obligations_json=result.obligations,
            matched_rule_key=result.matched_rule_key,
            policy_version=policy_version,
            backend_decision_id=result.backend_decision_id,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def _evaluate_local(
        self, bundle: PolicyBundleRow, document: dict[str, Any]
    ) -> EvaluationResult:
        candidates: list[dict[str, Any]] = []
        for raw in bundle.rules_json:
            if document["action"] not in raw["actions"] and "*" not in raw["actions"]:
                continue
            conditions = [PolicyCondition.model_validate(value) for value in raw["conditions"]]
            if all(_matches(condition, document) for condition in conditions):
                candidates.append(raw)
        if not candidates:
            return EvaluationResult(
                decision=Decision.DENY.value,
                reasons=["No reviewed policy rule matched; default deny applied."],
                obligations={},
                matched_rule_key=None,
            )
        candidates.sort(
            key=lambda rule: (
                -int(rule["priority"]),
                self.RESTRICTIVENESS[rule["effect"]],
                rule["rule_key"],
            )
        )
        selected = candidates[0]
        return EvaluationResult(
            decision=selected["effect"],
            reasons=list(selected["reasons"]),
            obligations=dict(selected.get("obligations") or {}),
            matched_rule_key=selected["rule_key"],
        )

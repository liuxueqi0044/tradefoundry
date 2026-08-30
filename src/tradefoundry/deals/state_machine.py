from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.contracts import StageTransitionRequest, StageTransitionView
from tradefoundry.deals.models import (
    ActionRow,
    DealRouteRow,
    ExperimentRow,
    ObservationRow,
    StageTransitionRow,
)
from tradefoundry.ingestion.hashing import payload_hash

TRANSITIONS = {
    "hypothesized": {"probe_ready", "stopped"},
    "probe_ready": {"probing", "stopped"},
    "probing": {"engaged", "stopped"},
    "engaged": {"qualified", "stopped"},
    "qualified": {"priceable", "stopped"},
    "priceable": {"quoted", "stopped"},
    "quoted": {"negotiating", "committed", "stopped"},
    "negotiating": {"committed", "stopped"},
    "committed": {"collected", "stopped"},
    "collected": set(),
    "stopped": set(),
}

QUALIFICATION_TYPES = {
    "requirement_confirmed",
    "specification_confirmed",
    "quantity_or_budget_confirmed",
    "timeline_confirmed",
    "decision_role_confirmed",
}


class RouteStageService:
    def __init__(self, session: Session):
        self.session = session

    def transition(self, route_id: str, request: StageTransitionRequest) -> StageTransitionView:
        request_hash = payload_hash({"route_id": route_id, **request.model_dump(mode="json")})
        existing = self.session.scalar(
            select(StageTransitionRow).where(
                StageTransitionRow.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("transition key was reused with a different payload")
            return StageTransitionView.model_validate(existing)
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        reasons = []
        if route.version != request.expected_version:
            reasons.append(
                "route version conflict: "
                f"expected {request.expected_version}, actual {route.version}"
            )
        if route.lifecycle_status != "active":
            reasons.append(f"route lifecycle is {route.lifecycle_status}")
        if request.to_stage.value not in TRANSITIONS.get(route.stage, set()):
            reasons.append(f"illegal transition {route.stage} -> {request.to_stage.value}")
        gate_reasons, evidence = self._gate(route, request.to_stage.value)
        reasons.extend(gate_reasons)
        outcome = "rejected" if reasons else "accepted"
        if outcome == "accepted":
            result = self.session.execute(
                update(DealRouteRow)
                .where(
                    DealRouteRow.id == route.id,
                    DealRouteRow.version == request.expected_version,
                    DealRouteRow.stage == route.stage,
                    DealRouteRow.lifecycle_status == "active",
                )
                .values(
                    stage=request.to_stage.value,
                    version=DealRouteRow.version + 1,
                )
            )
            if result.rowcount != 1:
                self.session.rollback()
                reasons.append("route changed concurrently before transition commit")
                outcome = "rejected"
        row = StageTransitionRow(
            id=str(uuid4()),
            route_id=route.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            from_stage=route.stage,
            to_stage=request.to_stage.value,
            expected_version=request.expected_version,
            outcome=outcome,
            reasons_json=reasons,
            evidence_snapshot_json=evidence,
            actor=request.actor,
            reason=request.reason,
        )
        self.session.add(row)
        self.session.commit()
        return StageTransitionView.model_validate(row)

    def _gate(self, route: DealRouteRow, target: str) -> tuple[list[str], dict]:
        observations = self.session.scalars(
            select(ObservationRow).where(ObservationRow.route_id == route.id)
        ).all()
        observation_types = {row.observation_type for row in observations}
        experiments = self.session.scalars(
            select(ExperimentRow).where(ExperimentRow.route_id == route.id)
        ).all()
        actions = self.session.scalars(
            select(ActionRow).where(ActionRow.route_id == route.id)
        ).all()
        evidence = {
            "experiment_ids": sorted(row.id for row in experiments),
            "action_ids": sorted(row.id for row in actions),
            "observation_ids": sorted(row.id for row in observations),
            "observation_types": sorted(observation_types),
        }
        reasons = []
        if target == "probe_ready":
            if not experiments:
                reasons.append("PROBE_READY requires an Experiment")
            if not actions:
                reasons.append("PROBE_READY requires a proposed Action")
            if not any(row.budget_limit > 0 for row in experiments):
                reasons.append("PROBE_READY requires an experiment budget")
            if not any(
                row.failure_condition_json and row.inconclusive_condition_json
                for row in experiments
            ):
                reasons.append("PROBE_READY requires stop conditions")
            if any(
                row.external_side_effect and row.policy_status == "not_required" for row in actions
            ):
                reasons.append("PROBE_READY requires an action permission boundary")
        elif target == "probing":
            if not any(row.status in {"queued", "executing", "succeeded"} for row in actions):
                reasons.append("PROBING requires a queued or executed Action")
        elif target == "engaged":
            if not observation_types.intersection({"reply", "meeting", "portal_action"}):
                reasons.append("ENGAGED requires a verified interaction observation")
        elif target == "qualified":
            present = observation_types.intersection(QUALIFICATION_TYPES)
            if len(present) < 4:
                reasons.append("QUALIFIED requires at least four configured qualification signals")
            evidence["qualification_types"] = sorted(present)
        elif target == "priceable":
            for required in {"supplier_quote", "cost_inputs_complete"}:
                if required not in observation_types:
                    reasons.append(f"PRICEABLE requires {required}")
        elif target == "quoted":
            for required in {"buyer_quote_approved", "buyer_quote_sent"}:
                if required not in observation_types:
                    reasons.append(f"QUOTED requires {required}")
        elif target == "negotiating":
            if "negotiation_started" not in observation_types:
                reasons.append("NEGOTIATING requires negotiation_started")
        elif target == "committed":
            if not observation_types.intersection(
                {"purchase_order", "contract", "deposit", "letter_of_credit"}
            ):
                reasons.append("COMMITTED requires a configured formal commitment")
        elif target == "collected" and "payment_reconciled" not in observation_types:
            reasons.append("COLLECTED requires reconciled payment evidence")
        return reasons, evidence

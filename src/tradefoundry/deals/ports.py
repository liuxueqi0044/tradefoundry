from __future__ import annotations

from typing import Any, Protocol

from tradefoundry.deals.models import ActionRow


class PolicyDecisionPort(Protocol):
    def is_approved(self, decision_ref: str, action: ActionRow) -> bool: ...


class ActionExecutorPort(Protocol):
    name: str

    def execute(
        self, *, action: ActionRow, external_effect_key: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def compensate(
        self, *, action: ActionRow, external_effect_key: str, reason: str
    ) -> dict[str, Any]: ...


class DenyExternalPolicyPort:
    def is_approved(self, decision_ref: str, action: ActionRow) -> bool:
        return False


class InternalNoopExecutor:
    name = "internal-noop-v1"

    def execute(
        self, *, action: ActionRow, external_effect_key: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if action.external_side_effect:
            raise PermissionError("default executor cannot perform external side effects")
        return {"status": "recorded", "external_effect_key": external_effect_key}

    def compensate(
        self, *, action: ActionRow, external_effect_key: str, reason: str
    ) -> dict[str, Any]:
        return {
            "status": "compensated",
            "external_effect_key": external_effect_key,
            "reason": reason,
        }

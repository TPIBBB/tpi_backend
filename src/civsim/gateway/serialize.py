"""政府的觀察與決策 <-> JSON，給 HTTP API 與 gateway client 共用。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from civsim.world.government import GovernmentActionType, GovernmentDecision, GovernmentObservation


def observation_to_dict(obs: GovernmentObservation) -> dict[str, Any]:
    return asdict(obs)


def observation_from_dict(data: dict[str, Any]) -> GovernmentObservation:
    return GovernmentObservation(**data)


def decision_to_dict(decision: GovernmentDecision) -> dict[str, Any]:
    return {"type": decision.type.value, "params": decision.params, "reason": decision.reason}


def decision_from_dict(data: dict[str, Any]) -> GovernmentDecision:
    return GovernmentDecision(GovernmentActionType(data["type"]), data.get("params") or {},
                              str(data.get("reason", "")))

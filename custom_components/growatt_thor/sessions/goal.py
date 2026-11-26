"""The target and observed progress of an individual charging session."""

from collections.abc import Mapping
from typing import Literal, TypedDict

from ..coerce import optional_float


class SessionGoal(TypedDict):
    kind: Literal["energy", "duration", "budget"]
    value: float


class SessionGoalProgress(SessionGoal):
    actual: float | None


def session_goal(kind: object, value: object) -> SessionGoal | None:
    if (kind != "energy" and kind != "duration" and kind != "budget") or isinstance(value, bool):
        return None
    amount = optional_float(value, minimum=0, errors=(TypeError, ValueError, OverflowError))
    if not amount:
        return None
    return {"kind": kind, "value": amount}


def retained_session_goal(value: object) -> SessionGoal | None:
    if isinstance(value, Mapping):
        return session_goal(value.get("kind"), value.get("value"))
    return None


def session_goal_progress(
    goal: SessionGoal, *, energy: object, duration: object, cost: object
) -> SessionGoalProgress:
    # Budget uses the charger's completed cost, and duration excludes pauses.
    actual = {"energy": energy, "duration": duration, "budget": cost}[goal["kind"]]
    return {**goal, "actual": optional_float(actual, minimum=0)}

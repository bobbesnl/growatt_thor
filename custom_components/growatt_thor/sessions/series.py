"""Bounded, shape-preserving time-series helpers for charging sessions."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from math import isfinite
from typing import Any

SESSION_CURVE_POINT_LIMIT = 96
ACTIVE_POWER_THRESHOLD_W = 100.0


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp()


def valid_curve_points(value: Any, *, signed=False, gaps=False) -> list[list[Any]]:
    """Return valid ``[timestamp, value]`` pairs without inventing samples."""
    result: list[list[Any]] = []
    for raw in value if isinstance(value, (list, tuple)) else ():
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            continue
        timestamp = _timestamp(raw[0])
        if raw[1] is None and gaps and timestamp is not None:
            result.append([str(raw[0]), None])
            continue
        try:
            number = float(raw[1])
        except (TypeError, ValueError):
            continue
        if timestamp is None or not isfinite(number) or (number < 0 and not signed):
            continue
        result.append([str(raw[0]), number])
    return result


def _evenly_bounded(indices: Iterable[int], limit: int) -> set[int]:
    ordered = sorted(set(indices))
    if len(ordered) <= limit:
        return set(ordered)
    if limit <= 1:
        return {ordered[0]}
    return {
        ordered[round(position * (len(ordered) - 1) / (limit - 1))] for position in range(limit)
    }


def downsample_curve(
    value: Any,
    *,
    limit: int = SESSION_CURVE_POINT_LIMIT,
    event_times: Iterable[object] = (),
    signed: bool = False,
    gaps: bool = False,
) -> list[list[Any]]:
    """Reduce a curve while retaining endpoints, pauses and visible extrema.

    Samples adjacent to a transition across the effective-power threshold and
    samples nearest a semantic session event are mandatory.  Remaining slots
    are filled by the points with the largest local triangle area, which keeps
    peaks and valleys substantially better than periodically dropping samples.
    """
    points = valid_curve_points(value, signed=signed, gaps=gaps)
    if limit <= 0:
        return []
    if len(points) <= limit:
        return points

    times = [_timestamp(point[0]) for point in points]
    mandatory = {0, len(points) - 1}
    for index in range(1, len(points)):
        previous, current = points[index - 1][1], points[index][1]
        if previous is None or current is None:
            if previous != current:
                mandatory.update((index - 1, index))
            continue
        if signed and (previous < 0) != (current < 0):
            mandatory.update((index - 1, index))
        previous_flowing = previous > ACTIVE_POWER_THRESHOLD_W
        flowing = points[index][1] > ACTIVE_POWER_THRESHOLD_W
        if flowing != previous_flowing:
            mandatory.update((index - 1, index))

    valid_event_times = [
        timestamp for raw in event_times if (timestamp := _timestamp(raw)) is not None
    ]
    for event_time in valid_event_times:
        nearest = min(
            range(len(points)),
            key=lambda index: abs((times[index] or 0) - event_time),
        )
        mandatory.add(nearest)

    if len(mandatory) >= limit:
        selected = _evenly_bounded(mandatory, limit)
        selected.update((0, len(points) - 1))
        if len(selected) > limit:
            selected = _evenly_bounded(selected, limit)
        return [points[index] for index in sorted(selected)]

    candidates: list[tuple[float, int]] = []
    for index in range(1, len(points) - 1):
        if index in mandatory:
            continue
        previous_time = times[index - 1] or 0
        current_time = times[index] or 0
        next_time = times[index + 1] or 0
        previous_value = points[index - 1][1]
        current_value = points[index][1]
        next_value = points[index + 1][1]
        if any(value is None for value in (previous_value, current_value, next_value)):
            continue
        duration = max(next_time - previous_time, 1.0)
        expected = previous_value + (
            (next_value - previous_value) * (current_time - previous_time) / duration
        )
        candidates.append((abs(current_value - expected), index))

    remaining = limit - len(mandatory)
    selected = mandatory | {index for _, index in sorted(candidates, reverse=True)[:remaining]}
    return [points[index] for index in sorted(selected)]

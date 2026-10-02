"""Tests for shape-preserving charging-curve compaction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest


PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
    / "sessions/series.py"
)
SPEC = importlib.util.spec_from_file_location("thor_session_series_test", PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def curve(values):
    start = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    return [
        [(start + timedelta(minutes=index)).isoformat(), value]
        for index, value in enumerate(values)
    ]


class SessionSeriesTest(unittest.TestCase):
    def test_compaction_keeps_endpoints_and_pause_transitions(self):
        points = curve([0] * 20 + [7000] * 40 + [0] * 20 + [5000] * 40)

        compacted = module.downsample_curve(points, limit=16)

        self.assertLessEqual(len(compacted), 16)
        self.assertEqual(compacted[0], points[0])
        self.assertEqual(compacted[-1], points[-1])
        for index in (19, 20, 59, 60, 79, 80):
            self.assertIn(points[index], compacted)

    def test_compaction_keeps_sample_nearest_an_event(self):
        points = curve([1000] * 120)
        event_at = points[73][0]

        compacted = module.downsample_curve(
            points,
            limit=12,
            event_times=[event_at],
        )

        self.assertIn(points[73], compacted)
        self.assertLessEqual(len(compacted), 12)

    def test_invalid_points_are_removed_without_becoming_zero(self):
        self.assertEqual(
            module.downsample_curve(
                [["invalid", 10], ["2026-09-21T08:00:00Z", -1]],
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()

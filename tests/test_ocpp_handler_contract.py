"""Fallback responses captured from the handlers before their guard extraction."""

import asyncio
import importlib.util
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.support import build_coordinator, load_package_module

HAS_OCPP = all(importlib.util.find_spec(name) is not None for name in ("ocpp", "websockets"))

if HAS_OCPP:
    server = load_package_module("ocpp.server")

FIXTURE = Path(__file__).parent / "fixtures/ocpp_handler_fallbacks.json"


async def handler_fallbacks():
    coordinator = build_coordinator()
    coordinator.now = lambda: "2026-09-04T10:00:00Z"
    coordinator.hass.loop = asyncio.get_running_loop()
    coordinator.hass.async_create_task = lambda coroutine: coroutine.close()
    cp = server.GrowattChargePoint("TEST", SimpleNamespace(), coordinator, coordinator.hass)
    cases = (
        ("on_boot_notification", coordinator, "record_boot_notification", {}),
        ("on_heartbeat", cp, "_schedule_post_connect_init", {}),
        ("on_authorize", coordinator.authorization, "decide", {"id_tag": "TEST-CARD"}),
        (
            "on_start_transaction",
            coordinator,
            "async_allocate_transaction_id",
            {"connector_id": 1, "id_tag": "TEST-CARD", "meter_start": 0},
        ),
        (
            "on_stop_transaction",
            coordinator,
            "stop_transaction",
            {"transaction_id": 42, "meter_stop": 0},
        ),
        (
            "on_status_notification",
            coordinator,
            "record_status_notification",
            {"connector_id": 1, "status": "Charging"},
        ),
        (
            "on_meter_values",
            coordinator,
            "process_meter_values",
            {"connector_id": 1, "meter_value": []},
        ),
        (
            "on_data_transfer",
            coordinator,
            "process_fault_message",
            {"vendor_id": "Growatt", "message_id": "faultmessage", "data": "fault"},
        ),
    )
    replies = {}
    for name, owner, failing_method, arguments in cases:
        error = RuntimeError("handler test failure")
        options = (
            {"new": AsyncMock(side_effect=error)}
            if failing_method.startswith("async_")
            else {"side_effect": error}
        )
        with (
            patch.object(owner, failing_method, create=True, **options),
            unittest.TestCase().assertLogs(server._LOGGER, level="ERROR"),
        ):
            replies[name] = asdict(await getattr(cp, name)(**arguments))
    return replies


@unittest.skipUnless(HAS_OCPP, "Install tests/requirements-auth.txt for real OCPP responses")
class OcppHandlerFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_eight_handler_failures_keep_their_original_response_payloads(self):
        self.assertEqual(await handler_fallbacks(), json.loads(FIXTURE.read_text()))

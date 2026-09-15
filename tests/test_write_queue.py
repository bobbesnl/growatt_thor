"""Regression tests for charger write queue hardening."""
from __future__ import annotations

import ast
import asyncio
from collections import deque
import importlib.util
from pathlib import Path
import sys
import types
import unittest


PACKAGE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "growatt_thor"
)
MODULE_PATH = PACKAGE_PATH / "coordinator.py"


class _DataUpdateCoordinator:
    """Minimal Home Assistant stand-in needed to import the coordinator."""


class _Store:
    """Minimal Home Assistant storage stand-in."""


homeassistant = types.ModuleType("homeassistant")
helpers = types.ModuleType("homeassistant.helpers")
update_coordinator = types.ModuleType(
    "homeassistant.helpers.update_coordinator"
)
storage = types.ModuleType("homeassistant.helpers.storage")
update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
storage.Store = _Store
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault(
    "homeassistant.helpers.update_coordinator",
    update_coordinator,
)
sys.modules.setdefault("homeassistant.helpers.storage", storage)

package = types.ModuleType("custom_components.growatt_thor")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
sys.modules.setdefault("custom_components.growatt_thor", package)

SPEC = importlib.util.spec_from_file_location(
    "custom_components.growatt_thor.coordinator",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
coordinator_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coordinator_module
SPEC.loader.exec_module(coordinator_module)
write_queue_module = sys.modules["custom_components.growatt_thor.write_queue"]


class _FakeHass:
    def __init__(self, loop):
        self.loop = loop
        self.data = {"growatt_thor": {}}

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


def _build_coordinator(loop):
    coordinator = coordinator_module.GrowattCoordinator.__new__(
        coordinator_module.GrowattCoordinator
    )
    coordinator.hass = _FakeHass(loop)
    coordinator._write_queue = deque()
    coordinator._write_lock = asyncio.Lock()
    coordinator._write_task = None
    coordinator._write_queue_changed = asyncio.Event()
    coordinator._write_queue_idle = asyncio.Event()
    coordinator._write_queue_idle.set()
    coordinator._connection_changed = asyncio.Event()
    coordinator._connection_changed.set()
    coordinator._active_write_item = None
    coordinator._configuration_refresh_task = None
    coordinator._last_write_monotonic = None
    coordinator._min_write_interval = 0.0
    coordinator._poll_pause_after_write = 0.0
    coordinator.connected = True
    coordinator.configuration_writes = {}
    coordinator.async_set_updated_data = lambda data: None
    return coordinator


class WriteQueueTest(unittest.IsolatedAsyncioTestCase):
    """Verify deduplication and prompt transaction controls."""

    def _policy(self, expires_after, reconnect=None):
        """Create a short-lived policy so timing tests stay fast."""
        if reconnect is None:
            reconnect = (
                coordinator_module.ChargerWriteReconnectPolicy.RETAIN_UNTIL_EXPIRY
            )
        return coordinator_module.ChargerWriteQueuePolicy(
            expires_after=expires_after,
            reconnect=reconnect,
        )

    async def test_configuration_queue_metadata_requires_generation(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write():
            return None

        with self.assertRaisesRegex(ValueError, "key and generation"):
            await coordinator.queue_write(
                write,
                configuration_key="G_MaxCurrent",
            )

    async def test_duplicate_configuration_write_keeps_latest_value(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []

        async def write(value):
            calls.append(value)

        await coordinator.queue_write(
            write,
            "old",
            dedupe_key="G_LCDCloseEnable",
        )
        await coordinator.queue_write(
            write,
            "new",
            dedupe_key="G_LCDCloseEnable",
        )
        await coordinator._write_task

        self.assertEqual(calls, ["new"])

    async def test_replaced_cleanup_cannot_clear_newer_generation(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []
        visible_value = "13"

        async def write(value):
            calls.append(value)

        old_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "13",
        )

        def restore_old_value(_result):
            nonlocal visible_value
            if coordinator.configuration_write_is_current(
                "G_MaxCurrent",
                old_generation,
            ):
                visible_value = "reported"

        await coordinator.queue_write(
            write,
            "13",
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=old_generation,
            on_unsent=restore_old_value,
        )

        new_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        visible_value = "17"
        await coordinator.queue_write(
            write,
            "17",
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=new_generation,
        )
        await coordinator._write_task

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(calls, ["17"])
        self.assertEqual(visible_value, "17")
        self.assertEqual(tracked.generation, new_generation)
        self.assertEqual(tracked.status, coordinator_module.ConfigurationWriteStatus.PENDING)
        self.assertEqual(
            tracked.superseded_outcomes[-1].result,
            "replaced_by_newer_intent",
        )

    async def test_expired_configuration_is_never_sent(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        calls = []

        async def write(charge_point):
            calls.append(charge_point)

        generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await coordinator.queue_write(
                write,
                object(),
                requires_connection=True,
                configuration_key="G_MaxCurrent",
                configuration_generation=generation,
                policy=self._policy(0.01),
            )
            await coordinator._write_task

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(calls, [])
        self.assertEqual(
            tracked.status,
            coordinator_module.ConfigurationWriteStatus.EXPIRED,
        )
        self.assertEqual(tracked.result, "expired_before_send")

    async def test_expiry_does_not_discard_an_already_sent_outcome(self):
        """Once OCPP may have acted, its result remains authoritative."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        request_started = asyncio.Event()
        release_response = asyncio.Event()

        async def write(generation):
            request_started.set()
            await release_response.wait()
            coordinator.acknowledge_configuration_write(
                "G_MaxCurrent",
                generation=generation,
                accepted=True,
                result="Accepted",
            )
            return coordinator_module.ChargerWriteResult.success("Accepted")

        generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        await coordinator.queue_write(
            write,
            generation,
            configuration_key="G_MaxCurrent",
            configuration_generation=generation,
            policy=self._policy(0.01),
        )
        await request_started.wait()
        await asyncio.sleep(0.02)
        release_response.set()
        await coordinator._write_task

        self.assertEqual(
            coordinator.configuration_writes["G_MaxCurrent"].status,
            coordinator_module.ConfigurationWriteStatus.AWAITING_READBACK,
        )

    async def test_short_reconnect_retains_eligible_configuration(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        stale_charge_point = object()
        current_charge_point = object()
        calls = []

        async def write(charge_point):
            calls.append(charge_point)
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            stale_charge_point,
            requires_connection=True,
            policy=self._policy(0.2),
        )
        await asyncio.sleep(0.01)

        coordinator.hass.data["growatt_thor"][
            "charge_point"
        ] = current_charge_point
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task

        self.assertEqual(calls, [current_charge_point])

    async def test_volatile_command_is_discarded_during_disconnect(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        calls = []

        async def write(charge_point):
            calls.append(charge_point)

        with self.assertLogs(
            coordinator_module._LOGGER,
            level="WARNING",
        ) as logs:
            await coordinator.queue_write(
                write,
                object(),
                requires_connection=True,
                command_name="RemoteStartTransaction",
                policy=self._policy(
                    1.0,
                    coordinator_module.ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
                ),
            )
            await coordinator._write_task

        self.assertEqual(calls, [])
        self.assertTrue(
            any("discarded_on_disconnect" in line for line in logs.output)
        )

    async def test_volatile_command_expires_behind_active_write(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        calls = []

        async def blocker():
            calls.append("blocker")
            blocker_started.set()
            await release_blocker.wait()

        async def volatile_control():
            calls.append("volatile")

        await coordinator.queue_write(
            blocker,
            rate_limited=False,
            policy=self._policy(1.0),
        )
        await blocker_started.wait()
        await coordinator.queue_write(
            volatile_control,
            priority=True,
            rate_limited=False,
            command_name="RemoteStartTransaction",
            policy=self._policy(
                0.01,
                coordinator_module.ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
            ),
        )
        await asyncio.sleep(0.02)
        release_blocker.set()
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await coordinator._write_task

        self.assertEqual(calls, ["blocker"])

    async def test_superseded_expiry_cannot_clear_newer_pending_value(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        calls = []
        visible_value = "17"

        async def write(charge_point, value):
            calls.append(value)
            return coordinator_module.ChargerWriteResult.success("Accepted")

        old_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "13",
        )

        def restore_old_value(_result):
            nonlocal visible_value
            if coordinator.configuration_write_is_current(
                "G_MaxCurrent",
                old_generation,
            ):
                visible_value = "reported"

        await coordinator.queue_write(
            write,
            object(),
            "13",
            dedupe_key="old-max-current",
            requires_connection=True,
            configuration_key="G_MaxCurrent",
            configuration_generation=old_generation,
            policy=self._policy(0.02),
            on_unsent=restore_old_value,
        )
        await asyncio.sleep(0)

        new_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        await coordinator.queue_write(
            write,
            object(),
            "17",
            dedupe_key="new-max-current",
            requires_connection=True,
            configuration_key="G_MaxCurrent",
            configuration_generation=new_generation,
            policy=self._policy(0.2),
        )
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await asyncio.sleep(0.04)

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(tracked.generation, new_generation)
        self.assertEqual(tracked.requested_raw_value, "17")
        self.assertEqual(
            tracked.status,
            coordinator_module.ConfigurationWriteStatus.PENDING,
        )
        self.assertEqual(visible_value, "17")
        self.assertEqual(
            tracked.superseded_outcomes[-1].outcome,
            "expired",
        )

        coordinator.hass.data["growatt_thor"]["charge_point"] = object()
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task
        self.assertEqual(calls, ["17"])

    async def test_delayed_command_is_revalidated_before_execution(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        still_valid = True
        calls = []
        cleanup_results = []

        async def write():
            calls.append("sent")

        await coordinator.queue_write(
            write,
            revalidate=lambda: None if still_valid else "transaction_changed",
            on_unsent=cleanup_results.append,
        )
        still_valid = False
        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await coordinator._write_task

        self.assertEqual(calls, [])
        self.assertEqual(len(cleanup_results), 1)
        self.assertEqual(
            cleanup_results[0].status,
            coordinator_module.ChargerWriteStatus.SKIPPED,
        )
        self.assertEqual(cleanup_results[0].reason, "transaction_changed")

    async def test_callback_skip_runs_the_same_unsent_cleanup(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        cleanup_results = []

        async def write():
            return coordinator_module.ChargerWriteResult.skipped(
                "active_transaction"
            )

        with self.assertLogs(coordinator_module._LOGGER, level="WARNING"):
            await coordinator.queue_write(
                write,
                on_unsent=cleanup_results.append,
            )
            await coordinator._write_task

        self.assertEqual(len(cleanup_results), 1)
        self.assertEqual(cleanup_results[0].reason, "active_transaction")

    async def test_invalid_revalidation_result_fails_closed(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []
        cleanup_results = []

        async def write():
            calls.append("sent")

        with self.assertLogs(coordinator_module._LOGGER, level="ERROR"):
            await coordinator.queue_write(
                write,
                revalidate=lambda: False,
                on_unsent=cleanup_results.append,
            )
            await coordinator._write_task

        self.assertEqual(calls, [])
        self.assertEqual(cleanup_results[0].reason, "revalidation_error")

    async def test_active_older_write_cannot_overwrite_newer_intent(self):
        """Deduplication cannot cancel an in-flight OCPP request.

        The first callback is deliberately held after it became active. A
        second HA action then records and queues a newer value for the same key.
        When the old acknowledgement arrives, its generation must keep it from
        changing either the tracked request or the optimistic visible value.
        """
        coordinator = _build_coordinator(asyncio.get_running_loop())
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        visible_values = []

        async def write(value, generation):
            if value == "13":
                first_started.set()
                await release_first.wait()
            outcome_is_current = coordinator.acknowledge_configuration_write(
                "G_MaxCurrent",
                generation=generation,
                accepted=True,
                result="Accepted",
            )
            if outcome_is_current:
                visible_values.append(value)
            return coordinator_module.ChargerWriteResult.success("Accepted")

        old_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "13",
        )
        await coordinator.queue_write(
            write,
            "13",
            old_generation,
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=old_generation,
        )
        await first_started.wait()

        new_generation = coordinator.begin_configuration_write(
            "G_MaxCurrent",
            "17",
        )
        await coordinator.queue_write(
            write,
            "17",
            new_generation,
            dedupe_key="G_MaxCurrent",
            configuration_key="G_MaxCurrent",
            configuration_generation=new_generation,
        )
        release_first.set()
        await coordinator._write_task

        tracked = coordinator.configuration_writes["G_MaxCurrent"]
        self.assertEqual(tracked.generation, new_generation)
        self.assertEqual(tracked.requested_raw_value, "17")
        self.assertEqual(
            tracked.status,
            coordinator_module.ConfigurationWriteStatus.AWAITING_READBACK,
        )
        self.assertEqual(visible_values, ["17"])

    async def test_control_interrupts_configuration_rate_limit(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator._min_write_interval = 0.2
        coordinator._last_write_monotonic = coordinator.hass.loop.time()
        calls = []

        async def write(name):
            calls.append(name)

        await coordinator.queue_write(
            write,
            "configuration",
            command_name="ChangeConfiguration(G_LCDCloseEnable)",
        )
        await asyncio.sleep(0)

        await coordinator.queue_write(
            write,
            "start",
            priority=True,
            rate_limited=False,
            command_name="RemoteStartTransaction",
        )
        await asyncio.sleep(0.05)

        self.assertEqual(calls, ["start"])
        await coordinator._write_task
        self.assertEqual(calls, ["start", "configuration"])

    async def test_priority_controls_preserve_fifo_order(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = []

        async def write(name):
            calls.append(name)

        await coordinator.queue_write(write, "configuration")
        await coordinator.queue_write(
            write,
            "start",
            priority=True,
            rate_limited=False,
        )
        await coordinator.queue_write(
            write,
            "stop",
            priority=True,
            rate_limited=False,
        )
        await coordinator._write_task

        self.assertEqual(calls, ["start", "stop", "configuration"])

    async def test_connection_bound_write_waits_and_uses_reconnected_charge_point(self):
        """An unsent command survives disconnect and never uses the old socket."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        old_charge_point = object()
        new_charge_point = object()
        calls = []

        async def write(charge_point, value):
            calls.append((charge_point, value))
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            old_charge_point,
            "17",
            dedupe_key="G_MaxCurrent",
            requires_connection=True,
        )
        await asyncio.sleep(0)
        self.assertEqual(calls, [])
        self.assertEqual(len(coordinator._write_queue), 1)

        coordinator.hass.data["growatt_thor"]["charge_point"] = new_charge_point
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task

        self.assertEqual(calls, [(new_charge_point, "17")])

    async def test_last_value_wins_while_waiting_for_reconnect(self):
        """Reconnect retention must not regress the existing deduplication rule."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator.connected = False
        coordinator._connection_changed.clear()
        old_charge_point = object()
        new_charge_point = object()
        calls = []

        async def write(charge_point, value):
            calls.append((charge_point, value))
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            old_charge_point,
            "16",
            dedupe_key="G_MaxCurrent",
            requires_connection=True,
        )
        await asyncio.sleep(0)
        await coordinator.queue_write(
            write,
            old_charge_point,
            "13",
            dedupe_key="G_MaxCurrent",
            requires_connection=True,
        )

        coordinator.hass.data["growatt_thor"]["charge_point"] = new_charge_point
        coordinator.connected = True
        coordinator._connection_changed.set()
        await coordinator._write_task

        self.assertEqual(calls, [(new_charge_point, "13")])

    async def test_definitely_unsent_command_is_rebound_and_retried(self):
        """A stale connection error is safe to retry on the current connection."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        first_charge_point = object()
        second_charge_point = object()
        coordinator.hass.data["growatt_thor"]["charge_point"] = first_charge_point
        calls = []

        async def write(charge_point):
            calls.append(charge_point)
            if len(calls) == 1:
                coordinator.hass.data["growatt_thor"][
                    "charge_point"
                ] = second_charge_point
                raise coordinator_module.ChargerConnectionUnavailable(
                    "connection replaced before send"
                )
            return coordinator_module.ChargerWriteResult.success("Accepted")

        await coordinator.queue_write(
            write,
            first_charge_point,
            requires_connection=True,
        )
        await coordinator._write_task

        self.assertEqual(calls, [first_charge_point, second_charge_point])

    async def test_uncertain_command_is_not_blindly_retried(self):
        """A lost acknowledgement requires readback rather than duplicate send."""
        coordinator = _build_coordinator(asyncio.get_running_loop())
        calls = 0

        async def write():
            nonlocal calls
            calls += 1
            raise coordinator_module.ChargerRequestOutcomeUncertain(
                "connection lost after send"
            )

        with self.assertLogs(coordinator_module._LOGGER, level="WARNING") as logs:
            await coordinator.queue_write(write, command_name="ChangeConfiguration")
            await coordinator._write_task

        self.assertEqual(calls, 1)
        self.assertTrue(any("outcome uncertain" in line for line in logs.output))

    async def test_failed_outcome_is_never_logged_as_success(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())

        async def write():
            return coordinator_module.ChargerWriteResult.failed(
                "charger_rejected",
                "Rejected",
            )

        with self.assertLogs(coordinator_module._LOGGER, level="INFO") as logs:
            await coordinator.queue_write(write, command_name="ChangeConfiguration")
            await coordinator._write_task

        combined = "\n".join(logs.output)
        self.assertIn("Write failed", combined)
        self.assertNotIn("Write succeeded", combined)

    async def test_post_write_readbacks_are_coalesced_until_queue_is_idle(self):
        coordinator = _build_coordinator(asyncio.get_running_loop())
        coordinator._write_queue_idle.clear()
        calls = 0

        class ChargePoint:
            async def trigger_get_configuration(self, *, skip_if_writes_pending):
                nonlocal calls
                self.skip_if_writes_pending = skip_if_writes_pending
                calls += 1
                return True

        charge_point = ChargePoint()
        coordinator.hass.data["growatt_thor"]["charge_point"] = charge_point

        first = coordinator.schedule_configuration_refresh(delay=0)
        second = coordinator.schedule_configuration_refresh(delay=0)
        self.assertIs(first, second)
        await asyncio.sleep(0)
        self.assertEqual(calls, 0)

        coordinator._write_queue_idle.set()
        self.assertTrue(await first)
        self.assertEqual(calls, 1)
        self.assertTrue(charge_point.skip_if_writes_pending)


class WriteQueuePolicyWiringTest(unittest.TestCase):
    """Keep production call sites explicit about delayed-command semantics."""

    PRODUCTION_FILES = (
        "button.py",
        "config_flow.py",
        "configuration_control.py",
        "number.py",
        "select.py",
        "switch.py",
        "time.py",
    )

    def test_bundled_policy_windows_are_deliberate_and_bounded(self):
        self.assertEqual(
            write_queue_module.CONFIGURATION_WRITE_POLICY.expires_after,
            300.0,
        )
        self.assertEqual(
            write_queue_module.TRANSACTION_CONTROL_WRITE_POLICY.expires_after,
            60.0,
        )
        self.assertEqual(
            write_queue_module.VOLATILE_CONTROL_WRITE_POLICY.expires_after,
            15.0,
        )
        self.assertEqual(
            write_queue_module.VOLATILE_CONTROL_WRITE_POLICY.reconnect,
            write_queue_module.ChargerWriteReconnectPolicy.DISCARD_WHEN_DISCONNECTED,
        )

        for invalid_expiry in (0, float("nan")):
            with self.subTest(invalid_expiry=invalid_expiry):
                with self.assertRaisesRegex(ValueError, "greater than zero"):
                    write_queue_module.ChargerWriteQueuePolicy(
                        expires_after=invalid_expiry,
                        reconnect=(
                            write_queue_module.ChargerWriteReconnectPolicy.RETAIN_UNTIL_EXPIRY
                        ),
                    )

    def test_every_production_queue_call_declares_a_policy(self):
        missing = []
        for filename in self.PRODUCTION_FILES:
            tree = ast.parse((PACKAGE_PATH / filename).read_text())
            for call in (
                node for node in ast.walk(tree) if isinstance(node, ast.Call)
            ):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "queue_write"
                ):
                    continue
                keyword_names = {keyword.arg for keyword in call.keywords}
                if "policy" not in keyword_names:
                    missing.append(f"{filename}:{call.lineno}")

        self.assertEqual(missing, [])

    def test_start_stop_and_ap_mode_use_their_specific_policies(self):
        expected = {
            ("button.py", "RemoteStartTransaction"): (
                "VOLATILE_CONTROL_WRITE_POLICY",
                True,
            ),
            ("button.py", "RemoteStopTransaction"): (
                "TRANSACTION_CONTROL_WRITE_POLICY",
                True,
            ),
            ("config_flow.py", "DataTransfer(appconfigmode)"): (
                "VOLATILE_CONTROL_WRITE_POLICY",
                False,
            ),
        }

        found = {}
        for filename in {item[0] for item in expected}:
            tree = ast.parse((PACKAGE_PATH / filename).read_text())
            for call in (
                node for node in ast.walk(tree) if isinstance(node, ast.Call)
            ):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "queue_write"
                ):
                    continue
                keywords = {
                    keyword.arg: keyword.value
                    for keyword in call.keywords
                    if keyword.arg is not None
                }
                command = keywords.get("command_name")
                policy = keywords.get("policy")
                if not (
                    isinstance(command, ast.Constant)
                    and isinstance(command.value, str)
                    and isinstance(policy, ast.Name)
                ):
                    continue
                key = (filename, command.value)
                if key in expected:
                    found[key] = (
                        policy.id,
                        "revalidate" in keywords,
                    )

        self.assertEqual(found, expected)

    def test_stop_no_longer_invents_transaction_zero(self):
        tree = ast.parse((PACKAGE_PATH / "button.py").read_text())
        stop_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "StopChargingButton"
        )
        integer_constants = [
            node.value
            for node in ast.walk(stop_class)
            if isinstance(node, ast.Constant)
            and type(node.value) is int
        ]
        attributes = [
            node.attr
            for node in ast.walk(stop_class)
            if isinstance(node, ast.Attribute)
        ]

        self.assertNotIn(0, integer_constants)
        self.assertIn("transaction_id", attributes)
        self.assertIn("transaction_is_active", attributes)


if __name__ == "__main__":
    unittest.main()

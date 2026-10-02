"""HA service boundary tested with small storage/registry fakes, no charger."""

import asyncio
import importlib
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

HAS_DEPS = all(importlib.util.find_spec(name) for name in ["ocpp", "voluptuous"])


class Store:
    retained = None

    def __init__(self, *args):
        pass

    async def async_load(self):
        return self.retained

    async def async_save(self, value):
        type(self).retained = value


class Services:
    def __init__(self):
        self.registered = {}

    def async_register(self, domain, name, handler, **kwargs):
        self.registered[name] = (handler, kwargs["schema"])

    def async_remove(self, domain, name):
        self.registered.pop(name)

    async def invoke(self, name, **data):
        handler, schema = self.registered[name]
        return await handler(SimpleNamespace(data=schema(data)))


class TimerHandle:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class Loop:
    def __init__(self):
        self.timers = []

    def time(self):
        return 0

    def call_later(self, delay, callback):
        handle = TimerHandle(delay, callback)
        self.timers.append(handle)
        return handle


@unittest.skipUnless(HAS_DEPS, "Requires tests/requirements-auth.txt")
class TargetServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        package = ModuleType("thor_target_service_test")
        package.__path__ = [
            str(Path(__file__).parents[1] / "custom_components/growatt_thor")
        ]
        sys.modules[package.__name__] = package
        stubs = {}
        for name in [
            "homeassistant",
            "homeassistant.core",
            "homeassistant.exceptions",
            "homeassistant.helpers",
            "homeassistant.helpers.storage",
        ]:
            stubs[name] = ModuleType(name)
        stubs["homeassistant.core"].SupportsResponse = SimpleNamespace(ONLY="only")
        stubs["homeassistant.exceptions"].HomeAssistantError = RuntimeError
        stubs["homeassistant.helpers.storage"].Store = Store
        with patch.dict(sys.modules, stubs):
            self.module = importlib.import_module(
                package.__name__ + ".targets.services"
            )
            self.runtime = sys.modules[package.__name__ + ".targets.runtime"]
        config = importlib.import_module(package.__name__ + ".configuration.values")
        self.cp = SimpleNamespace(
            id="TEST-CHARGER",
            call=AsyncMock(return_value=SimpleNamespace(status="Accepted")),
        )
        self.queue = []
        self.now_utc = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)

        async def queue_write(function):
            self.queue.append(function)

        self.coordinator = SimpleNamespace(
            connected=True,
            transaction_is_active=False,
            charger_is_faulted=False,
            status="Available",
            connection_started_at="connection-1",
            boot_notification={
                "request": {"firmware_version": self.runtime.CAPTURE_FIRMWARE}
            },
            configuration_values={
                key: config.configuration_value_from_item({"key": key, "value": value})
                for key, value in {
                    "G_WorkingMode": "Fast",
                    "G_ChargerMode": "1",
                }.items()
            },
            authorization=SimpleNamespace(
                policy=SimpleNamespace(allows_ha_remote_start=lambda: True),
                begin_ha_remote_start=lambda tag: True,
                cancel_ha_remote_start=lambda: None,
            ),
            now=lambda: "2026-09-10T10:00:00Z",
            async_set_updated_data=lambda value: None,
            queue_write=queue_write,
            _poll_pause_after_write=10,
            _min_write_interval=0,
        )
        self.hass = SimpleNamespace(
            services=Services(),
            data={"growatt_thor": {"charge_point": self.cp}},
            loop=Loop(),
            config=SimpleNamespace(time_zone="Europe/Berlin"),
            async_create_task=asyncio.create_task,
        )
        Store.retained = None
        self.module.async_register_target_services(self.hass)
        self.runtime._TARGET_START_PAUSE_SECONDS = 0
        self.runtime._TARGET_RESERVATION_PAUSE_SECONDS = 0
        await self.module.async_setup_target_services(
            self.hass,
            SimpleNamespace(entry_id="TEST"),
            self.coordinator,
            now_utc=lambda: self.now_utc,
        )

    async def start(self, **overrides):
        return await self.hass.services.invoke(
            "start_charging_target",
            **{
                "kind": "duration",
                "value": "1",
                "confirm_experimental": True,
                **overrides,
            },
        )

    async def test_preview_is_read_only_and_omits_internal_capture_references(self):
        result = await self.hass.services.invoke(
            "preview_charging_target", kind="budget", value="49,99", start="once"
        )
        self.assertTrue(result["pilot_supported"])
        self.assertNotIn("capture", result)
        self.assertFalse(result["automatic_stop_verified"])
        self.assertEqual(self.queue, [])
        self.cp.call.assert_not_called()

    async def test_unloaded_entry_keeps_schema_and_explains_unavailability(self):
        self.module.async_unload_target_services(self.hass)
        self.assertIn("start_charging_target", self.hass.services.registered)
        with self.assertRaisesRegex(RuntimeError, "not_loaded"):
            await self.start()

    async def test_unload_cancels_schedule_and_reload_restores_it_once(self):
        await self.schedule(recurrence="daily")
        timer = self.hass.loop.timers[-1]
        retained = Store.retained.copy()
        self.module.async_unload_target_services(self.hass)
        self.module.async_unload_target_services(self.hass)
        self.assertTrue(timer.cancelled)
        self.assertIsNone(self.coordinator._charging_target_transaction_started)
        self.assertIsNone(self.coordinator._charging_target_transaction_stopped)
        self.assertIsNone(self.coordinator._cancel_charging_target_schedule)
        self.assertEqual(Store.retained, retained)
        await self.module.async_setup_target_services(
            self.hass, SimpleNamespace(entry_id="TEST"), self.coordinator,
            now_utc=lambda: self.now_utc,
        )
        self.assertEqual(sum(not timer.cancelled for timer in self.hass.loop.timers), 1)
        self.cp.call.assert_not_called()
        self.module.async_unload_target_services(self.hass)

    async def test_explicit_confirmation_is_required(self):
        import voluptuous as vol

        for value in [False, "true", 1]:
            with self.assertRaises(vol.Invalid):
                await self.start(confirm_experimental=value)
        self.assertEqual(self.queue, [])

    async def test_budget_uses_captured_decimal_comma_and_is_marked_unverified(self):
        result = await self.start(kind="budget", value="1.25")
        self.assertFalse(result["enforcement_verified"])
        await self.queue[0]()
        target = self.cp.call.call_args_list[0].args[0]
        self.assertEqual(target.message_id, "G_SetAmount")
        self.assertEqual(target.data, "1,25")

    async def test_sequence_and_persistence_block_duplicate_requests(self):
        result = await self.start()
        self.assertEqual(result["state"], "queued")
        with self.assertRaisesRegex(RuntimeError, "reconciliation"):
            await self.start()
        await self.queue[0]()
        self.assertEqual(Store.retained["state"], "start_accepted")
        self.assertEqual(self.cp.call.await_count, 2)
        self.assertNotIn("TEST-CHARGER", str(Store.retained))

    async def test_immediate_start_reconciles_transaction_callback_race(self):
        async def accepted_with_fast_start(payload, **_kwargs):
            if type(payload).__name__ == "RemoteStartTransaction":
                self.coordinator.transaction_is_active = True
            return SimpleNamespace(status="Accepted")

        self.cp.call.side_effect = accepted_with_fast_start
        await self.start()
        await self.queue[0]()
        self.assertEqual(Store.retained["state"], "active")

    async def test_disconnect_before_execution_never_sends(self):
        await self.start()
        self.coordinator.connected = False
        await self.queue[0]()
        self.cp.call.assert_not_called()
        self.assertEqual(Store.retained["state"], "blocked_before_target")

    async def test_reconnect_before_execution_never_sends(self):
        await self.start()
        self.hass.data["growatt_thor"]["charge_point"] = SimpleNamespace()
        await self.queue[0]()
        self.cp.call.assert_not_called()

    async def test_auth_fault_and_transaction_guards(self):
        for field, value in [
            ("transaction_is_active", True),
            ("charger_is_faulted", True),
            ("connected", False),
            ("status", "Reserved"),
        ]:
            old = getattr(self.coordinator, field)
            setattr(self.coordinator, field, value)
            with self.assertRaises(RuntimeError):
                await self.start()
            setattr(self.coordinator, field, old)
        self.coordinator.authorization.policy.allows_ha_remote_start = lambda: False
        with self.assertRaisesRegex(RuntimeError, "not_authorized"):
            await self.start()

    async def test_restart_restores_uncertain_request_without_replaying(self):
        await self.start()
        await self.module.async_setup_target_services(
            self.hass, SimpleNamespace(entry_id="TEST"), self.coordinator
        )
        with self.assertRaisesRegex(RuntimeError, "reconciliation"):
            await self.start()
        self.cp.call.assert_not_called()

    async def test_acknowledgement_is_not_a_stop_or_cancel_command(self):
        await self.start()
        with self.assertRaisesRegex(RuntimeError, "busy"):
            await self.hass.services.invoke(
                "acknowledge_target_reset", confirm_native_target_reset=True
            )
        await self.queue[0]()
        self.cp.call.reset_mock()
        await self.hass.services.invoke(
            "acknowledge_target_reset", confirm_native_target_reset=True
        )
        self.assertIsNone(Store.retained)
        self.cp.call.assert_not_called()

    async def test_rfid_target_only_never_sends_remote_start(self):
        config = importlib.import_module("thor_target_service_test.configuration.values")
        self.coordinator.configuration_values["G_ChargerMode"] = (
            config.configuration_value_from_item({"key": "G_ChargerMode", "value": "2"})
        )
        self.coordinator.authorization.policy.allows_ha_remote_start = lambda: False
        result = await self.hass.services.invoke(
            "prepare_rfid_charging_target", value="1", confirm_experimental=True
        )
        self.assertEqual(result["state"], "queued")
        self.cp.call.assert_not_called()
        await self.queue[0]()
        self.cp.call.assert_awaited_once()
        payload = self.cp.call.call_args.args[0]
        self.assertEqual(type(payload).__name__, "DataTransfer")
        self.assertEqual(payload.message_id, "G_SetEnergy")
        self.assertEqual(payload.data, "1")
        result = await self.hass.services.invoke("charging_target_status")
        self.assertEqual(result["request"]["state"], "target_accepted_waiting_for_rfid")

    async def test_rfid_target_rejects_app_mode(self):
        with self.assertRaisesRegex(RuntimeError, "rfid_authorization_mode_required"):
            await self.hass.services.invoke(
                "prepare_rfid_charging_target", value="1", confirm_experimental=True
            )
        self.cp.call.assert_not_called()

    def plug_mode(self):
        config = importlib.import_module("thor_target_service_test.configuration.values")
        self.coordinator.configuration_values["G_ChargerMode"] = (
            config.configuration_value_from_item({"key": "G_ChargerMode", "value": "3"})
        )
        self.coordinator.status = "Available"

    async def prepare_plug(self, **overrides):
        return await self.hass.services.invoke(
            "prepare_plug_charging_target",
            **{
                "entry_id": "TEST",
                "value": "1",
                "confirm_experimental": True,
                **overrides,
            },
        )

    async def schedule(self, **overrides):
        return await self.hass.services.invoke(
            "schedule_charging_target",
            **{
                "entry_id": "TEST",
                "value": "1",
                "start_at": "2026-09-11T12:05:00+02:00",
                "confirm_experimental": True,
                **overrides,
            },
        )

    async def test_plug_only_sends_energy_and_retains_confirmation(self):
        self.plug_mode()
        await self.prepare_plug()
        self.cp.call.assert_not_called()
        await self.queue[0]()
        self.cp.call.assert_awaited_once()
        self.assertEqual(self.cp.call.call_args.args[0].message_id, "G_SetEnergy")
        self.assertEqual(Store.retained["state"], "target_accepted_waiting_for_plug")
        self.assertEqual(Store.retained["connection_started_at"], "connection-1")

    async def test_plug_refresh_requires_exact_request_and_same_accepted_value(self):
        self.plug_mode()
        previous = {
            "request_id": "old",
            "kind": "energy",
            "value": "1",
            "state": "target_accepted_waiting_for_rfid",
        }
        self.coordinator.charging_target_request = previous
        for arguments in (
            {},
            {"replace_request_id": "wrong"},
            {"replace_request_id": "old", "value": "2"},
        ):
            with self.assertRaises(RuntimeError):
                await self.prepare_plug(**arguments)
        await self.prepare_plug(replace_request_id="old", value="1.00")
        self.assertEqual(Store.retained["previous_requests"][0]["request_id"], "old")
        await self.queue[0]()
        self.cp.call.assert_awaited_once()

    async def test_plug_cannot_refresh_unknown_outcome(self):
        self.plug_mode()
        self.coordinator.charging_target_request = {
            "request_id": "old",
            "kind": "energy",
            "value": "1",
            "state": "outcome_unknown",
        }
        with self.assertRaises(RuntimeError):
            await self.prepare_plug(replace_request_id="old")
        self.cp.call.assert_not_called()

    async def test_plug_rechecks_unplugged_state_before_sending(self):
        self.plug_mode()
        await self.prepare_plug()
        self.coordinator.status = "Preparing"
        await self.queue[0]()
        self.cp.call.assert_not_called()
        self.assertEqual(Store.retained["state"], "blocked_before_target")

    async def test_plug_rejects_wrong_entry_and_connected_vehicle(self):
        self.plug_mode()
        with self.assertRaisesRegex(RuntimeError, "wrong_charger_entry"):
            await self.prepare_plug(entry_id="OTHER")
        self.coordinator.status = "Preparing"
        with self.assertRaisesRegex(RuntimeError, "unplug_vehicle"):
            await self.prepare_plug()
        self.cp.call.assert_not_called()

    async def test_plug_timeout_keeps_unknown_without_retry(self):
        self.plug_mode()
        self.cp.call.side_effect = TimeoutError
        await self.prepare_plug()
        await self.queue[0]()
        self.assertEqual(Store.retained["state"], "outcome_unknown")
        self.cp.call.assert_awaited_once()

    async def arm_one_time(self, **overrides):
        await self.schedule(**overrides)
        self.assertEqual(Store.retained["state"], "reservation_queued")
        self.assertEqual(len(self.queue), 1)
        await self.queue[0]()
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(len(self.hass.loop.timers), 1)

    async def run_due_one_time(self):
        task = self.hass.loop.timers[-1].callback()
        await task
        self.assertEqual(len(self.queue), 2)
        await self.queue[1]()

    async def test_one_time_sets_target_then_reserves_without_starting_early(self):
        await self.arm_one_time()
        self.assertEqual(Store.retained["scheduled_for"], "2026-09-11T10:05:00Z")
        self.assertEqual(Store.retained["reservation_expiry"], "2026-09-11T12:05:00.000")
        self.assertEqual(Store.retained["activation"], "charger_reservation_remote_start")
        self.assertEqual(self.hass.loop.timers[0].delay, 300)
        self.assertEqual(self.cp.call.await_count, 2)
        target, reservation = [call.args[0] for call in self.cp.call.call_args_list]
        self.assertEqual(target.message_id, "G_SetEnergy")
        self.assertEqual(type(reservation).__name__, "ReserveNow")
        self.assertEqual(reservation.expiry_date, "2026-09-11T12:05:00.000")

    async def test_due_one_time_refreshes_target_then_remote_starts(self):
        await self.arm_one_time()
        await self.run_due_one_time()
        self.assertEqual(self.cp.call.await_count, 4)
        target, start = [call.args[0] for call in self.cp.call.call_args_list[-2:]]
        self.assertEqual(target.message_id, "G_SetEnergy")
        self.assertEqual(target.data, "1")
        self.assertEqual(type(start).__name__, "RemoteStartTransaction")
        self.assertEqual(Store.retained["state"], "start_accepted")

    async def test_all_target_kinds_use_the_same_one_time_reservation_flow(self):
        expected = {
            "energy": ("1.5", "G_SetEnergy", "1.5", True),
            "duration": ("5", "G_SetTime", "5", True),
            "budget": ("1.25", "G_SetAmount", "1,25", False),
        }
        for kind, (value, message, wire, verified) in expected.items():
            with self.subTest(kind=kind):
                self.cp.call.reset_mock()
                self.queue.clear()
                self.hass.loop.timers.clear()
                self.coordinator.charging_target_request = None
                Store.retained = None
                await self.arm_one_time(kind=kind, value=value)
                self.assertEqual(self.cp.call.call_args_list[0].args[0].message_id, message)
                self.assertEqual(self.cp.call.call_args_list[0].args[0].data, wire)
                self.assertEqual(Store.retained["enforcement_verified"], verified)
                await self.run_due_one_time()
                self.assertEqual(self.cp.call.call_args_list[-2].args[0].message_id, message)
                self.assertEqual(type(self.cp.call.call_args_list[-1].args[0]).__name__, "RemoteStartTransaction")

    async def test_schedule_validates_time_entry_and_mode_before_persisting(self):
        for start_at in (
            "2026-09-11T09:59:00Z",
            "2026-09-11T10:05:00",
            "2026-11-01T10:00:00Z",
            "not-a-time",
        ):
            with self.assertRaises(RuntimeError):
                await self.schedule(start_at=start_at)
        with self.assertRaisesRegex(RuntimeError, "wrong_charger_entry"):
            await self.schedule(entry_id="OTHER")
        self.coordinator.status = "Preparing"
        with self.assertRaisesRegex(RuntimeError, "unplug_vehicle_before_setting_reservation"):
            await self.schedule()

    async def test_one_time_plug_and_charge_uses_reservation_and_remote_start(self):
        self.plug_mode()
        await self.arm_one_time()
        self.coordinator.status = "Preparing"
        await self.run_due_one_time()
        self.assertEqual(type(self.cp.call.call_args_list[-1].args[0]).__name__, "RemoteStartTransaction")
        self.assertEqual(Store.retained["state"], "start_accepted")

    async def test_due_schedule_rechecks_safety_and_never_sends_when_mode_changed(self):
        await self.arm_one_time()
        calls_before_due = self.cp.call.await_count
        config = importlib.import_module("thor_target_service_test.configuration.values")
        self.coordinator.configuration_values["G_ChargerMode"] = (
            config.configuration_value_from_item({"key": "G_ChargerMode", "value": "2"})
        )
        task = self.hass.loop.timers[0].callback()
        await task
        await self.queue[1]()
        self.assertEqual(self.cp.call.await_count, calls_before_due)
        self.assertEqual(Store.retained["state"], "blocked_before_target")

    async def test_one_time_cancellation_sends_cancel_reservation(self):
        await self.arm_one_time()
        request_id = Store.retained["request_id"]
        handle = self.hass.loop.timers[0]
        with self.assertRaisesRegex(RuntimeError, "requires_cancel"):
            await self.hass.services.invoke(
                "acknowledge_target_reset", confirm_native_target_reset=True
            )
        await self.hass.services.invoke(
            "cancel_scheduled_charging_target",
            request_id=request_id,
            confirm_cancel=True,
        )
        self.assertTrue(handle.cancelled)
        self.assertEqual(Store.retained["state"], "cancellation_queued")
        await self.queue[1]()
        self.assertEqual(Store.retained["state"], "scheduled_cancelled")
        self.assertEqual(type(self.cp.call.call_args.args[0]).__name__, "CancelReservation")
        with self.assertRaisesRegex(RuntimeError, "not_cancellable"):
            await self.hass.services.invoke(
                "cancel_scheduled_charging_target",
                request_id=request_id,
                confirm_cancel=True,
            )

    async def test_reschedule_requires_cancelled_exact_retained_request(self):
        await self.arm_one_time()
        request_id = Store.retained["request_id"]
        with self.assertRaises(RuntimeError):
            await self.schedule(replace_request_id="wrong")
        await self.hass.services.invoke(
            "cancel_scheduled_charging_target",
            request_id=request_id,
            confirm_cancel=True,
        )
        await self.queue[1]()
        await self.schedule(
            value="2", replace_request_id=request_id, start_at="2026-09-11T10:10:00Z"
        )
        self.assertEqual(Store.retained["value"], "2")
        self.assertEqual(Store.retained["scheduled_for"], "2026-09-11T10:10:00Z")
        self.assertEqual(Store.retained["previous_requests"][0]["request_id"], request_id)
        self.assertTrue(self.hass.loop.timers[0].cancelled)

    async def test_restart_restores_future_schedule_and_marks_missed_one(self):
        await self.arm_one_time()
        timer_count = len(self.hass.loop.timers)
        await self.module.async_setup_target_services(
            self.hass,
            SimpleNamespace(entry_id="TEST"),
            self.coordinator,
            now_utc=lambda: self.now_utc,
        )
        self.assertEqual(len(self.hass.loop.timers), timer_count + 1)
        self.assertEqual(Store.retained["state"], "scheduled")
        self.now_utc = datetime(2026, 9, 11, 10, 6, tzinfo=timezone.utc)
        await self.module.async_setup_target_services(
            self.hass,
            SimpleNamespace(entry_id="TEST"),
            self.coordinator,
            now_utc=lambda: self.now_utc,
        )
        self.assertEqual(Store.retained["state"], "scheduled_missed")
        self.assertEqual(self.cp.call.await_count, 2)

    async def test_schedule_blocked_before_wire_can_be_explicitly_replanned(self):
        self.coordinator.charging_target_request = {
            "request_id": "blocked",
            "kind": "energy",
            "value": "1",
            "state": "blocked_before_target",
        }
        await self.schedule(value="2", replace_request_id="blocked")
        self.assertEqual(Store.retained["state"], "reservation_queued")
        self.assertEqual(Store.retained["value"], "2")
        self.assertEqual(Store.retained["previous_requests"][0]["request_id"], "blocked")

    async def test_daily_schedule_sends_nothing_until_due_and_rearms_next_day(self):
        await self.schedule(kind="duration", value="5", recurrence="daily")
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(Store.retained["recurrence"], "daily")
        self.assertEqual(Store.retained["activation"], "daily_remote_start")
        self.cp.call.assert_not_called()
        self.assertEqual(self.queue, [])
        self.assertEqual(self.hass.loop.timers[0].delay, 300)
        self.now_utc = datetime(2026, 9, 11, 10, 5, tzinfo=timezone.utc)
        task = self.hass.loop.timers[0].callback()
        await task
        await self.queue[0]()
        self.assertEqual(self.cp.call.await_count, 2)
        self.assertEqual(self.cp.call.call_args_list[0].args[0].message_id, "G_SetTime")
        self.assertEqual(type(self.cp.call.call_args_list[1].args[0]).__name__, "RemoteStartTransaction")
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(Store.retained["last_run_state"], "start_accepted")
        self.assertEqual(Store.retained["scheduled_for"], "2026-09-12T10:05:00Z")
        self.assertEqual(len(self.hass.loop.timers), 2)

    async def test_daily_plug_and_charge_requires_vehicle_at_due_time(self):
        self.plug_mode()
        await self.schedule(recurrence="daily")
        self.now_utc = datetime(2026, 9, 11, 10, 5, tzinfo=timezone.utc)
        task = self.hass.loop.timers[0].callback()
        await task
        await self.queue[0]()
        self.cp.call.assert_not_called()
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(Store.retained["last_run_state"], "blocked_before_target")

    async def test_daily_plug_and_charge_starts_when_vehicle_is_waiting(self):
        self.plug_mode()
        await self.schedule(kind="budget", value="1", recurrence="daily")
        self.coordinator.status = "Preparing"
        self.now_utc = datetime(2026, 9, 11, 10, 5, tzinfo=timezone.utc)
        task = self.hass.loop.timers[0].callback()
        await task
        await self.queue[0]()
        self.assertEqual(self.cp.call.call_args_list[0].args[0].message_id, "G_SetAmount")
        self.assertEqual(type(self.cp.call.call_args_list[1].args[0]).__name__, "RemoteStartTransaction")
        self.assertEqual(Store.retained["last_run_state"], "start_accepted")

    async def test_daily_cancel_is_local_and_restart_advances_a_missed_run(self):
        await self.schedule(recurrence="daily")
        request_id = Store.retained["request_id"]
        handle = self.hass.loop.timers[0]
        await self.hass.services.invoke(
            "cancel_scheduled_charging_target",
            request_id=request_id,
            confirm_cancel=True,
        )
        self.assertTrue(handle.cancelled)
        self.assertEqual(Store.retained["state"], "scheduled_cancelled")
        self.cp.call.assert_not_called()

        Store.retained = {
            **Store.retained,
            "state": "scheduled",
            "scheduled_for": "2026-09-10T10:05:00Z",
            "time_zone": "Europe/Berlin",
        }
        await self.module.async_setup_target_services(
            self.hass,
            SimpleNamespace(entry_id="TEST"),
            self.coordinator,
            now_utc=lambda: self.now_utc,
        )
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(Store.retained["last_run_state"], "missed_while_unavailable")
        self.assertEqual(Store.retained["scheduled_for"], "2026-09-11T10:05:00Z")

    async def test_transaction_callbacks_preserve_daily_schedule(self):
        await self.schedule(recurrence="daily")
        self.now_utc = datetime(2026, 9, 11, 10, 5, tzinfo=timezone.utc)
        task = self.hass.loop.timers[0].callback()
        await task
        await self.queue[0]()
        await self.coordinator._charging_target_transaction_started()
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(Store.retained["last_run_state"], "charging")
        await self.coordinator._charging_target_transaction_stopped()
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(Store.retained["last_run_state"], "completed")

    async def test_daily_start_reconciles_fast_transaction_callback_race(self):
        async def accepted_with_fast_start(payload, **_kwargs):
            if type(payload).__name__ == "RemoteStartTransaction":
                self.coordinator.transaction_is_active = True
            return SimpleNamespace(status="Accepted")

        self.cp.call.side_effect = accepted_with_fast_start
        await self.schedule(recurrence="daily")
        self.now_utc = datetime(2026, 9, 11, 10, 5, tzinfo=timezone.utc)
        task = self.hass.loop.timers[0].callback()
        await task
        await self.queue[0]()
        self.assertEqual(Store.retained["state"], "scheduled")
        self.assertEqual(Store.retained["last_run_state"], "charging")

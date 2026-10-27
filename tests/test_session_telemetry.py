"""Real lifecycle, checkpoint, delayed completion, CSV and presentation round trips."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_multi_entry import _build_coordinator
from custom_components.growatt_thor.configuration.values import configuration_value_from_item
from custom_components.growatt_thor.sessions.records import parse_growatt_session_record
from custom_components.growatt_thor.sessions.telemetry import CONTEXT_CURVES, SessionTelemetry, async_setup_session_history
from custom_components.growatt_thor.sessions.csv import append_session_row, session_detail_data, dashboard_session_data
from custom_components.growatt_thor.presentation.card_data import dashboard_active_session, dashboard_attributes, CARD_ATTRIBUTE_TARGET_BYTES
from custom_components.growatt_thor.sessions.series import downsample_curve

AT = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)


def coordinator(entry_id='entry_one'):
    c = _build_coordinator(entry_id=entry_id)
    c.at = AT
    c.now = lambda: c.at.isoformat().replace('+00:00', 'Z')
    c.hass.config = SimpleNamespace(time_zone='Europe/Berlin', currency='EUR')
    c.hass.async_create_task = lambda coro: coro.close()
    c._schedule_storage_save = lambda: None
    c.site_accounting_options = {'site_solar_power_entity': 'sensor.pv', 'site_house_power_entity': 'sensor.house'}
    c.battery_power_entity = 'sensor.battery'
    c.battery_power_sign = 'positive_discharge'
    c.hass.states = {key: SimpleNamespace(state=str(value), attributes={'unit_of_measurement':'W'}, last_reported=AT, last_updated=AT)
                     for key,value in [('sensor.pv',5000),('sensor.house',1200),('sensor.battery',-300)]}
    c.configuration_values = {key: configuration_value_from_item({'key':key,'value':value})
        for key,value in {'G_MaxCurrent':'16','G_TimeZone':'UTC+2','G_DaylightSavingTime':'00-00&00-00'}.items()}
    return c


def meter(c, **kwargs):
    c.process_meter_values([{'timestamp': c.now(), 'sampledValue':[
        *({'measurand':'Current.Import','phase':phase,'unit':'A','value':str(amps)} for phase,amps in [('L1',10),('L2',11),('L3',0)]),
        {'measurand':'Power.Active.Import','unit':'W','value':'4800'},
    ]}], transaction_id=c.transaction_id, **kwargs)


class SessionTelemetryTest(unittest.TestCase):
    def test_restart_delayed_completion_csv_and_detail_preserve_all_context(self):
        c = coordinator()
        c.start_transaction(100, connector_id=1, meter_start=0, timestamp='2026-10-28T12:00:00')
        identity = dashboard_active_session(c)['session_id']
        c.at += timedelta(seconds=5)
        meter(c)
        c.at += timedelta(seconds=25)
        c.update_configuration_value('G_MaxCurrent','8')
        c.at += timedelta(minutes=1)
        c.record_status_notification(1,'SuspendedEV','NoError')
        c.sessions.observe_context()
        active = dashboard_active_session(c)
        self.assertEqual(set(CONTEXT_CURVES) - active.keys(), set())
        self.assertEqual(active['site_pv_surplus_curve_w'][0][1],3800)
        self.assertEqual(active['site_house_load_curve_w'][0][1],1200)
        self.assertEqual(active['site_battery_curve_w'][0][1],-300)
        self.assertEqual(active['measured_current_sum_curve_a'], [['2026-10-28T10:00:05Z',21.0], [c.now(),None]])
        c.hass.states['sensor.house'].state = 'unavailable'
        c.at += timedelta(seconds=30)
        c.sessions.observe_context()
        state = c._active_session_state()
        restarted = coordinator()
        restarted.at = c.at + timedelta(minutes=2)
        restarted._restore_active_session_state(state)
        self.assertEqual(restarted.sessions.telemetry.snapshot()['site_battery_curve_w'][-1][1],None)
        restarted.record_status_notification(1,'SuspendedEV','NoError')
        restarted.stop_transaction(transaction_id=100,reason='Remote',meter_stop=1000,timestamp='2026-10-28T12:04:00')
        # Another restart before the final vendor report arrives.
        pending = json.loads(json.dumps(restarted.sessions.pending_completions))
        final = coordinator()
        final.at = restarted.at
        final.sessions.restore_completions(pending)
        final.runtime_data['append_session_to_csv'] = object()
        final.sessions.process_session_record(parse_growatt_session_record('currentrecord',
            'transactionId=100&starttime=2026-10-28 12:00:00&endtime=2026-10-28 12:04:00&costenergy=1000&costmoney=20'))
        row, = final.sessions.outbox.snapshot()
        self.assertEqual(row['session_id'],identity)
        for key in CONTEXT_CURVES:self.assertIn(key,row)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sessions.csv'
            append_session_row(path,row)
            detail=session_detail_data(path,identity,time_zone='Europe/Berlin')
            for key in CONTEXT_CURVES:
                self.assertEqual(detail[key],json.loads(row[key]))
            self.assertTrue(any(point[1] is None for point in detail['site_house_load_curve_w']))
            self.assertTrue(any(point[1]<0 for point in detail['site_battery_curve_w'] if point[1] is not None))
            self.assertEqual({point[1] for point in detail['configured_current_limit_curve_a'] if point[1] is not None},{16,8})
            self.assertEqual(dashboard_session_data(path)['items'][0]['session_id'],identity)

    def test_current_only_accepts_complete_current_samples_and_matching_active_transaction(self):
        c=coordinator();meter(c)
        self.assertEqual(c.sessions.telemetry.snapshot(),{})
        c.start_transaction(100,connector_id=1,timestamp=c.now())
        c.at+=timedelta(seconds=10);meter(c)
        before=c.sessions.telemetry.snapshot()['measured_current_sum_curve_a']
        c.process_meter_values([{'timestamp':c.now(),'sampledValue':[]}],transaction_id=101)
        self.assertEqual(c.sessions.telemetry.snapshot()['measured_current_sum_curve_a'],before)
        c.at+=timedelta(seconds=10)
        c.process_meter_values([{'timestamp':c.now(),'sampledValue':[{'measurand':'Current.Import','phase':'L1','unit':'A','value':'12'}]}],transaction_id=100)
        self.assertIsNone(c.sessions.telemetry.snapshot()['measured_current_sum_curve_a'][-1][1])
        c.process_meter_values([{'timestamp':'2026-10-28T10:10:00Z','sampledValue':[{'measurand':'Current.Import','phase':p,'value':'10'} for p in ('L1','L2','L3')]}],transaction_id=100)
        self.assertIsNone(c.sessions.telemetry.snapshot()['measured_current_sum_curve_a'][-1][1])

    def test_context_requires_actual_sources_and_tracks_pause_and_acknowledged_limits(self):
        c=coordinator();c.hass.states['sensor.house'].state='unknown'
        c.start_transaction(100,connector_id=1,timestamp=c.now())
        self.assertNotIn('site_pv_surplus_curve_w',c.sessions.telemetry.snapshot())
        c.at+=timedelta(seconds=30)
        c.hass.states['sensor.house'].state='1200'
        c.record_status_notification(1,'SuspendedEV','NoError')
        c.sessions.observe_context()
        self.assertEqual(c.sessions.telemetry.snapshot()['site_pv_surplus_curve_w'][-1][1],3800)
        c.begin_configuration_write('G_MaxCurrent','6')
        self.assertEqual(c.sessions.telemetry.snapshot()['configured_current_limit_curve_a'][-1][1],16)
        c.at+=timedelta(seconds=1);c.update_configuration_value('G_MaxCurrent','6')
        self.assertEqual(c.sessions.telemetry.snapshot()['configured_current_limit_curve_a'][-1][1],6)

    def test_missing_house_sensor_uses_signed_site_balance_only_with_complete_valid_inputs(self):
        c=coordinator();c.site_accounting_options.pop('site_house_power_entity')
        c.site_accounting_options.update(site_accounting_profile='pv_battery',site_grid_source='thor_external')
        c.grid_power=1200;c.external_meter_last_updated_at=c.now()
        c.hass.states['sensor.battery'].state='600'
        c.start_transaction(100,connector_id=1,timestamp=c.now())
        self.assertNotIn('site_house_load_curve_w',c.sessions.telemetry.snapshot())
        c.at+=timedelta(seconds=5);meter(c)
        active=dashboard_active_session(c)
        self.assertEqual(active['site_house_load_curve_w'][-1][1],2000)
        self.assertEqual(active['site_pv_surplus_curve_w'][-1][1],3000)
        self.assertEqual(active['site_house_load_source'],'site_balance')
        state=c._active_session_state()
        other=coordinator();other._restore_active_session_state(state)
        self.assertEqual(other.sessions.telemetry.metadata(),{'site_house_load_source':'site_balance'})
        c.hass.states['sensor.battery'].state='unavailable'
        c.at+=timedelta(seconds=30);c.sessions.observe_context()
        self.assertIsNone(c.sessions.telemetry.snapshot()['site_house_load_curve_w'][-1][1])
        c.hass.states['sensor.battery'].state='600'
        c.external_meter_last_updated_at=(c.at-timedelta(minutes=10)).isoformat()
        c.at+=timedelta(seconds=30);c.sessions.observe_context()
        self.assertIsNone(c.sessions.telemetry.snapshot()['site_house_load_curve_w'][-1][1])

    def test_bounded_signed_curves_retain_gap_boundaries_and_do_not_mutate_live_data(self):
        c=coordinator();c.start_transaction(100,connector_id=1,timestamp=c.now())
        for i in range(500):
            at=(AT+timedelta(seconds=i)).isoformat()
            for key in CONTEXT_CURVES:
                value=None if 200<=i<220 else (-500 if key=='site_battery_curve_w' and i<250 else 1200)
                c.sessions.telemetry.observe(key,at,value)
        snapshot=c.sessions.telemetry.snapshot()
        for key,curve in snapshot.items():
            self.assertLessEqual(len(curve),96)
            self.assertTrue(any(point[1] is None for point in curve))
        card=dashboard_attributes(c)
        self.assertLessEqual(len(json.dumps(card,separators=(',',':')).encode()),CARD_ATTRIBUTE_TARGET_BYTES)
        self.assertEqual(snapshot,c.sessions.telemetry.snapshot())


class HistorySubscriptionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_source_changes_are_entry_scoped_and_both_subscriptions_are_removed(self):
        c=coordinator();c.start_transaction(100,connector_id=1,timestamp=c.now())
        callbacks={};cancelled=[]
        c.hass.bus=SimpleNamespace(async_listen=lambda name,fn: (callbacks.update(state=fn) or (lambda:cancelled.append('state'))))
        def timer(hass,fn,interval):
            self.assertEqual(interval.total_seconds(),30)
            callbacks['timer']=fn
            return lambda:cancelled.append('timer')
        with patch.dict(sys.modules,{'homeassistant.helpers.event':SimpleNamespace(async_track_time_interval=timer)}):
            stop=async_setup_session_history(c.hass,c)
        original=c.sessions.telemetry.snapshot()
        c.at+=timedelta(seconds=30)
        await callbacks['state'](SimpleNamespace(data={'entity_id':'sensor.other_house'}))
        self.assertEqual(c.sessions.telemetry.snapshot(),original)
        await callbacks['state'](SimpleNamespace(data={'entity_id':'sensor.house'}))
        self.assertNotEqual(c.sessions.telemetry.snapshot(),original)
        c.at+=timedelta(seconds=30)
        await callbacks['timer'](c.at)
        stop();self.assertEqual(cancelled,['state','timer'])

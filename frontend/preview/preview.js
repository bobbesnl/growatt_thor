import './ha-icon.bundle.js';
import { documentationHistory } from './documentation-data.bundle.js';
import { exampleGoal } from './goal-panel.bundle.js';
await import(`../../custom_components/growatt_thor/frontend/thor-card.js?preview=${Date.now()}`);
const cards = ['light', 'dark'].map((theme) => {
  const column = document.createElement('div');
  column.className = 'column';
  column.innerHTML = `<div class="caption">${theme}</div>`;
  const card = document.createElement('growatt-thor-card');
  card.setConfig({
    type: 'custom:growatt-thor-card',
    entity: 'sensor.thor_status',
    name: 'Garage',
    theme,
  });
  const goal = document.createElement('thor-preview-goal');
  goal.slot = 'goal-preview';
  goal.dark = theme === 'dark';
  card.append(goal);
  column.append(card);
  document.querySelector('#cards').append(column);
  return card;
});
const sessionCards = ['light', 'dark'].map((theme) => {
  const column = document.createElement('div');
  column.className = 'session-column';
  column.innerHTML = `<div class="caption">${theme} · double width</div>`;
  const card = document.createElement('growatt-thor-session-card');
  card.setConfig({
    type: 'custom:growatt-thor-session-card',
    entity: 'sensor.thor_status',
    theme,
    rows: 6,
    show_identifier: true,
  });
  column.append(card);
  document.querySelector('#session-cards').append(column);
  return card;
});
const editor = document.querySelector('growatt-thor-card-editor');
editor.setConfig({
  type: 'custom:growatt-thor-card',
  entity: 'sensor.thor_status',
  name: 'Garage',
});
const sessionEditor = document.querySelector('growatt-thor-session-card-editor');
sessionEditor.setConfig({
  type: 'custom:growatt-thor-session-card',
  entity: 'sensor.thor_status',
  rows: 6,
});
let currentHass;
// One in-memory target drives both themes. It is independent of charger telemetry.
let simulatedGoal;
function publishGoal() {
  cards.forEach((card) => {
    const panel = card.querySelector('thor-preview-goal');
    panel.goal = simulatedGoal;
    panel.language = document.querySelector('#language').value;
  });
}
function selectGoalExample() {
  const state = document.querySelector('#goal-state').value;
  const kind = document.querySelector('#goal-kind').value;
  simulatedGoal = state === 'none' ? undefined : exampleGoal(kind, state);
  publishGoal();
}
document.addEventListener('preview-goal-changed', (event) => {
  simulatedGoal = event.detail;
  document.querySelector('#goal-state').value = simulatedGoal.state;
  document.querySelector('#goal-kind').value = simulatedGoal.kind;
  publishGoal();
});
const entity = (entity_id, state, attributes = {}) => ({ entity_id, state, attributes });
function update() {
  publishGoal();
  const scenario = document.querySelector('#scenario').value,
    now = Date.now();
  const chargingSources = {
    none: null,
    solar: { solar_w: 8300 },
    solar_battery: { solar_w: 5900, battery_w: 2400 },
    solar_grid: { solar_w: 6500, grid_w: 1800 },
    mixed: { solar_w: 5000, battery_w: 1800, grid_w: 1500 },
    incomplete: { solar_w: 5000, battery_w: 1000 },
  }[document.querySelector('#source-mix').value];
  const sessionProfileSelection = document.querySelector('#session-profile').value;
  const sessionHasBattery = sessionProfileSelection === 'cloudy_battery';
  const sessionMultiDay = sessionProfileSelection === 'multi_day_idle';
  const sessionProfile = (start, end, index = 0, completed = true) => {
    const from = new Date(start.replace(' ', 'T')).getTime();
    const to = new Date(end.replace(' ', 'T')).getTime();
    const timestamp = (point, count) =>
      new Date(from + (to - from) * (point / (count - 1))).toISOString();
    const curve = (values, scale = 1000) =>
      values.map((value, point) => [timestamp(point, values.length), value * scale]);
    const variation = 1 - (index % 3) * 0.04;
    const pvSurplus = [2, 4.5, 6.4, 8.5, 9.8, 6.6, 3.4, 1.8, 2.5, 4.7, 6.4, 8.4, 5.7, 4.3, 7.1, 9];
    const houseLoad = [0.8, 0.8, 0.9, 1, 1.1, 2.4, 1.2, 1.1, 1, 1, 1.2, 1.4, 2.7, 1.2, 1, 0.9];
    const withoutBattery = [0, 4.2, 6, 8, 9.3, 6.2, 0, 0, 0, 4.4, 6, 8, 5.2, 4.1, 6.6, 8.3];
    const withBattery = [0, 4.2, 6, 8, 9.3, 7, 4.3, 0, 4.2, 4.8, 6, 8, 5.5, 4.3, 6.6, 8.3];
    const batteryFlow = [0, 0, -0.4, -0.7, -0.5, 0.4, 0.9, 1.8, 1.7, 0.2, 0, -0.4, 0.6, 0.1, 0, 0];
    const charging = (sessionHasBattery ? withBattery : withoutBattery).map(
      (value) => value * variation,
    );
    if (completed) charging[charging.length - 1] = 0;
    return {
      power_curve: curve(charging),
      site_pv_surplus_curve_w: curve(pvSurplus.map((value) => value * variation)),
      site_house_load_curve_w: curve(houseLoad),
      ...(sessionHasBattery ? { site_battery_curve_w: curve(batteryFlow) } : {}),
      configured_current_limit_curve_a: curve(
        [6, 6, 10, 12, 16, 10, 6, 6, 6, 8, 10, 16, 10, 6, 10, 16],
        1,
      ),
    };
  };
  const sessionEvents = (start, end, effectiveEnd = end) => {
    const from = new Date(start.replace(' ', 'T')).getTime();
    const to = new Date(end.replace(' ', 'T')).getTime();
    const effectiveTo = new Date(effectiveEnd.replace(' ', 'T')).getTime();
    const at = (timestamp) => new Date(timestamp).toISOString();
    return [
      {
        type: 'plugged_in',
        at: at(from - 4 * 60000),
        source: 'growatt',
        certainty: 'observed',
      },
      {
        type: 'transaction_started',
        at: at(from),
        source: 'ocpp',
        certainty: 'observed',
      },
      {
        type: 'energy_flow_started',
        at: at(from + 6 * 60000),
        source: 'meter',
        certainty: 'derived',
      },
      {
        type: 'charging_paused',
        at: at(from + (effectiveTo - from) * (sessionHasBattery ? 7 / 15 : 6 / 15)),
        source: 'meter',
        certainty: 'derived',
        reason: 'PV surplus below charging threshold',
      },
      {
        type: 'energy_flow_started',
        at: at(from + (effectiveTo - from) * (sessionHasBattery ? 8 / 15 : 9 / 15)),
        source: 'meter',
        certainty: 'derived',
        reason: 'PV surplus recovered',
      },
      {
        type: 'energy_flow_stopped',
        at: at(effectiveTo - 12 * 60000),
        source: 'meter',
        certainty: 'derived',
      },
      {
        type: 'transaction_stopped',
        at: at(to - 15000),
        source: 'ocpp',
        certainty: 'observed',
        reason: 'EVDisconnected',
      },
      {
        type: 'unplugged',
        at: at(to),
        source: 'growatt',
        certainty: 'observed',
      },
    ];
  };
  const data = {
    schema: 1,
    entry_id: 'demo',
    entities: {
      start_charging: 'button.start',
      stop_charging: 'button.stop',
      max_current: 'number.current',
      authorization_mode_control: 'select.authorization',
      last_session_energy: 'sensor.last_energy',
      last_session_duration: 'sensor.last_duration',
      last_session_cost: 'sensor.last_cost',
      last_charger_fault: 'sensor.fault',
    },
    working_mode: document.querySelector('#working-mode').value,
    auth_mode: document.querySelector('#auth').value,
    transaction_active: ![
      'idle',
      'available',
      'preparing',
      'finishing',
      'reserved',
      'unavailable',
    ].includes(scenario),
    session_started_at: new Date(now - 5400000).toISOString(),
    session_energy_kwh: 12.4,
    meter_received_at: new Date(now - 5000).toISOString(),
    sample_at: new Date(now - 5000).toISOString(),
    meter_stale_after: 180,
    power_w: 8300,
    currents_a: [12, 11.8, 12.2],
    max_current_a: 16,
    rated_power_kw: 11,
    nominal_phases: 3,
    configured_current_a: 16,
    status_info: null,
    error_code: 'NoError',
    external_meter_health: 'healthy',
    pv_linkage: {
      working_mode: ['pv_linkage', 'pv_linkage_plus'].includes(
        document.querySelector('#working-mode').value,
      )
        ? document.querySelector('#working-mode').value
        : 'pv_linkage_plus',
      grid_import_limit_kw: 2,
      boost_mode: 'disabled',
      manual_start: '10:00',
      manual_end: '12:30',
      smart_finish: '17:30',
      smart_target_energy_kwh: 12,
      draft_dirty: false,
      blocked_reason: null,
      last_apply: null,
    },
    power_flow: {
      received_at: new Date(now - 3000).toISOString(),
      stale_after_s: 95,
      grid_w: { export: -1200, balanced: 15, import: 800, missing: null }[
        document.querySelector('#grid-balance').value
      ],
      grid_sign: 'positive_import',
      grid_import_limit_kw: 2,
    },
    sessions: {
      schema: 1,
      total_energy_kwh: 48.2,
      total_green_energy_kwh: null,
      total_cost: 11.07,
      total_count: 6,
      items: [
        sessionMultiDay
          ? [
              '2026-09-12 08:14:00',
              '2026-09-15 09:42:00',
              9.5,
              2.19,
              '04A1B2C3D4E580',
              '2026-09-12 09:42:00',
            ]
          : ['2026-09-12 08:14:00', '2026-09-12 09:42:00', 9.5, 2.19, '04A1B2C3D4E580'],
        ['2026-09-10 17:30:00', '2026-09-10 18:05:00', 4.1, 0.94, 'freevenID'],
        ['2026-09-09 06:12:00', '2026-09-09 07:31:00', 7.8, 1.79, '04A1B2C3D4E580'],
        ['2026-09-07 13:00:00', '2026-09-07 15:22:00', 12.3, 2.83, '0478ABCDEF1290'],
        ['2026-09-05 20:18:00', '2026-09-05 21:10:00', 5.4, 1.24, 'freevenID'],
        ['2026-09-02 07:44:00', '2026-09-02 09:15:00', 9.1, 2.08, '04A1B2C3D4E580'],
      ].map(([start, end, energy, cost, identifier, effectiveEnd], index) => ({
        session_id: `preview-${index}`,
        active: false,
        start_time: start,
        end_time: end,
        energy_kwh: energy,
        green_energy_kwh: null,
        cost,
        duration_minutes: null,
        authorized_identifier: identifier,
        ...sessionProfile(start, effectiveEnd || end, index),
        events: sessionEvents(start, end, effectiveEnd || end),
      })),
    },
  };
  if (data.transaction_active) {
    const start = data.session_started_at;
    const activeEnd = new Date(now).toISOString();
    const activeFrom = new Date(start).getTime();
    const activeDuration = now - activeFrom;
    const activeAt = (progress) => new Date(activeFrom + activeDuration * progress).toISOString();
    data.sessions.items.unshift({
      session_id: 'preview-active',
      active: true,
      start_time: start,
      end_time: null,
      energy_kwh: data.session_energy_kwh,
      green_energy_kwh: null,
      cost: null,
      duration_minutes: null,
      authorized_identifier: data.auth_mode === 'plug_and_charge' ? 'freevenID' : '04A1B2C3D4E580',
      ...sessionProfile(start, activeEnd, 0, false),
      events: [
        {
          type: 'transaction_started',
          at: start,
          source: 'ocpp',
          certainty: 'observed',
        },
        {
          type: 'energy_flow_started',
          at: new Date(activeFrom + 6 * 60000).toISOString(),
          source: 'meter',
          certainty: 'derived',
        },
        {
          type: 'charging_paused',
          at: activeAt(sessionHasBattery ? 7 / 15 : 6 / 15),
          source: 'meter',
          certainty: 'derived',
          reason: 'PV surplus below charging threshold',
        },
        {
          type: 'energy_flow_started',
          at: activeAt(sessionHasBattery ? 8 / 15 : 9 / 15),
          source: 'meter',
          certainty: 'derived',
          reason: 'PV surplus recovered',
        },
      ],
    });
  }
  // Simulated source amounts are independent of the charger's live power mix.
  const accountingMode = document.querySelector('#session-accounting').value;
  if (accountingMode !== 'none') {
    for (const item of data.sessions.items) {
      const total = item.energy_kwh;
      const solar =
        total * (accountingMode === 'solar' ? 1 : accountingMode === 'unknown' ? 0 : 0.65);
      const battery = total * (['mixed', 'partial'].includes(accountingMode) ? 0.2 : 0);
      const grid =
        total * (accountingMode === 'mixed' ? 0.15 : accountingMode === 'partial' ? 0.05 : 0);
      item.source_energy_kwh = {
        direct_solar: solar,
        battery_unknown: battery,
        direct_grid: grid,
        unknown: Math.max(0, total - solar - battery - grid),
      };
      item.effective_grid_cost = grid * 0.3;
      item.accounting_coverage = total ? (solar + battery + grid) / total : 0;
      item.accounting_quality = item.accounting_coverage < 1 ? 'unknown' : 'derived';
      item.accounting_policy = { id: 'grid_first', version: 1 };
      item.green_energy_kwh = item.accounting_coverage >= 0.999999 ? solar : null;
    }
    // Like the backend, the summary includes known values from completed sessions.
    const green = data.sessions.items
      .filter((item) => !item.active && item.green_energy_kwh !== null)
      .map((item) => item.green_energy_kwh);
    data.sessions.total_green_energy_kwh = green.length
      ? green.reduce((sum, value) => sum + value, 0)
      : null;
  }
  if (sessionProfileSelection === 'documentation') {
    data.sessions = documentationHistory();
    data.charging_target_pilot = true;
    data.power_w = data.power_w === null ? null : data.power_w > 0 ? 7400 : 0;
    data.currents_a = data.power_w > 0 ? [10.7, 10.8, 10.6] : data.currents_a;
    data.rated_power_kw = 22;
    data.configured_current_a = 32;
    data.max_current_a = 32;
    data.session_energy_kwh = 28.233;
    data.session_started_at = new Date(now - (4 * 60 + 3) * 60000).toISOString();
    if (chargingSources) {
      for (const key of Object.keys(chargingSources)) chargingSources[key] *= 7400 / 8300;
      if (chargingSources.grid_w) {
        data.power_flow.grid_w = chargingSources.grid_w;
        data.power_flow.grid_import_limit_kw = 2;
        data.pv_linkage.grid_import_limit_kw = 2;
      }
    }
  }
  cards.forEach((card) => {
    card.querySelector('thor-preview-goal').slot =
      sessionProfileSelection === 'documentation' ? 'unused-preview' : 'goal-preview';
  });
  const previewSessionDetails = new Map(
    data.sessions.items.map((item) => [item.session_id, structuredClone(item)]),
  );
  let completedSessions = 0;
  for (const item of data.sessions.items) {
    if (item.active) continue;
    completedSessions += 1;
    item.detail_available = true;
    if (completedSessions === 1) continue;
    delete item.power_curve;
    delete item.site_pv_surplus_curve_w;
    delete item.site_house_load_curve_w;
    delete item.site_battery_curve_w;
    delete item.configured_current_limit_curve_a;
    delete item.events;
  }
  const notice = document.querySelector('#target-notice').value;
  if (notice !== 'none') {
    data.charging_target = {
      request_id: 'preview-target',
      kind: 'energy',
      value: '1',
      activation: 'remote_start',
      state:
        notice === 'scheduled'
          ? 'scheduled'
          : notice === 'uncertain'
            ? 'outcome_unknown'
            : 'blocked_before_target',
      recurrence: notice === 'scheduled' ? 'daily' : undefined,
      scheduled_for: new Date(now + 3600000).toISOString(),
      updated_at: new Date(now - (notice === 'expired' ? 31 * 60000 : 5 * 60000)).toISOString(),
    };
  }
  if (chargingSources) data.power_flow.charging_sources = chargingSources;
  if (document.querySelector('#grid-balance').value === 'missing')
    data.external_meter_health = 'not_reported';
  let state = scenario;
  if (scenario.startsWith('pv_')) {
    state = 'suspended_evse';
    data.working_mode = 'pv_linkage_plus';
    data.status_info = scenario === 'pv_wait' ? 'Wait for surplus' : 'ChargeWait';
    data.power_w = 0;
    data.currents_a = [0, 0, 0];
  }
  if (scenario === 'offline') state = 'unavailable';
  if (scenario === 'faulted') {
    data.error_code = 'PowerMeterFailure';
    data.status_info = '485Fault';
    data.external_meter_health = 'faulted';
    data.working_mode = 'pv_linkage';
  }
  if (scenario === 'stale') {
    state = 'charging';
    data.meter_received_at = new Date(now - 900000).toISOString();
  }
  if (scenario === 'missing_phase') {
    state = 'charging';
    data.currents_a = [12, null, 12.2];
  }
  if (scenario === 'single_phase') {
    state = 'charging';
    data.power_w = 2760;
    data.currents_a = [12, 0, 0];
  }
  if (scenario === 'command_rejected') {
    state = 'preparing';
    data.transaction_active = false;
    data.command = { action: 'start', state: 'rejected', updated_at: new Date(now).toISOString() };
  }
  if (['suspended_ev', 'suspended_evse'].includes(scenario)) {
    data.power_w = 0;
    data.currents_a = [0, 0, 0];
  }
  if (scenario === 'suspended_ev_no_meter') {
    state = 'suspended_ev';
    data.sample_at = new Date(now - 900000).toISOString();
    data.meter_received_at = data.sample_at;
  }
  if (scenario === 'preparing') {
    data.power_w = null;
    data.currents_a = [null, null, null];
    data.meter_received_at = null;
    data.sample_at = null;
  }
  data.pv_linkage.blocked_reason =
    scenario === 'offline'
      ? 'charger_disconnected'
      : scenario === 'faulted'
        ? 'charger_faulted'
        : data.transaction_active
          ? 'active_transaction'
          : data.external_meter_health !== 'healthy'
            ? 'external_meter_not_ready'
            : null;
  const states = {
    'sensor.thor_status': entity('sensor.thor_status', state, {
      friendly_name: 'THOR Garage Status',
      connected: scenario !== 'offline',
      thor_card: data,
    }),
    'button.start': entity('button.start', 'unknown'),
    'button.stop': entity('button.stop', 'unknown'),
    'number.current': entity(
      'number.current',
      sessionProfileSelection === 'documentation' ? '32' : '16',
      { min: 6, max: sessionProfileSelection === 'documentation' ? 32 : 16 },
    ),
    'select.authorization': entity('select.authorization', data.auth_mode, {
      options: ['home_assistant_rfid', 'rfid_only', 'plug_and_charge'],
    }),
    'sensor.last_energy': entity('sensor.last_energy', '18.7'),
    'sensor.last_duration': entity('sensor.last_duration', '2.25', { unit_of_measurement: 'h' }),
    'sensor.last_cost': entity('sensor.last_cost', '5.24', { unit_of_measurement: 'EUR' }),
    'sensor.fault': entity(
      'sensor.fault',
      scenario === 'faulted' ? 'power_meter_failure' : 'unknown',
      { message: '485Fault' },
    ),
  };
  currentHass = {
    states,
    language: document.querySelector('#language').value,
    connected: true,
    callWS: async (message) => {
      if (message.type !== 'growatt_thor/session_detail') throw new Error('Unknown command');
      await new Promise((resolve) => setTimeout(resolve, 250));
      const item = previewSessionDetails.get(message.session_id);
      if (!item) throw new Error('Session not found');
      return { schema: 1, item };
    },
    callService: async (domain, service, args) => {
      document.querySelector('#events').textContent = JSON.stringify(
        { domain, service, args },
        null,
        2,
      );
      const result = document.querySelector('#result').value;
      if (result === 'network_error') throw new Error('Simulated network error');
      if (domain === 'growatt_thor' && service === 'apply_pv_linkage_profile') {
        await new Promise((resolve) => setTimeout(resolve, 700));
        data.working_mode = args.working_mode;
        data.pv_linkage = {
          ...data.pv_linkage,
          working_mode: args.working_mode,
          grid_import_limit_kw:
            args.working_mode === 'pv_linkage'
              ? args.grid_import_limit_kw
              : data.pv_linkage.grid_import_limit_kw,
          boost_mode: args.boost_mode,
          manual_start: args.manual_start || null,
          manual_end: args.manual_end || null,
          smart_finish: args.smart_finish || null,
          smart_target_energy_kwh: args.smart_target_energy_kwh || null,
          draft_dirty: false,
          last_apply: { status: 'success', completed_steps: 3, total_steps: 3 },
        };
        data.power_flow.grid_import_limit_kw =
          args.working_mode === 'pv_linkage' ? args.grid_import_limit_kw : 0;
        publish();
        return;
      }
      data.command = {
        action: args.entity_id === 'button.start' ? 'start' : 'stop',
        state: 'queued',
        updated_at: new Date().toISOString(),
      };
      publish();
      setTimeout(() => {
        data.command = { ...data.command, state: result, updated_at: new Date().toISOString() };
        publish();
        if (result === 'accepted')
          setTimeout(() => {
            document.querySelector('#scenario').value =
              data.command.action === 'start' ? 'charging' : 'idle';
            update();
          }, 1800);
      }, 900);
    },
  };
  function publish() {
    currentHass = {
      ...currentHass,
      states: {
        ...states,
        'sensor.thor_status': {
          ...states['sensor.thor_status'],
          attributes: { ...states['sensor.thor_status'].attributes, thor_card: { ...data } },
        },
      },
    };
    cards.forEach((c) => (c.hass = currentHass));
    sessionCards.forEach((c) => (c.hass = currentHass));
    editor.hass = currentHass;
    sessionEditor.hass = currentHass;
  }
  publish();
}
// Preview only: opening details is logged, never sent to a server.
document.addEventListener('hass-more-info', (e) => {
  document.querySelector('#events').textContent = `More info: ${e.detail.entityId}`;
});
editor.addEventListener('config-changed', (e) => {
  cards.forEach((c, i) => c.setConfig({ ...e.detail.config, theme: i ? 'dark' : 'light' }));
});
document.querySelector('#scenario').onchange = update;
document.querySelector('#language').onchange = update;
document.querySelector('#auth').onchange = update;
document.querySelector('#working-mode').onchange = update;
document.querySelector('#grid-balance').onchange = update;
document.querySelector('#source-mix').onchange = update;
document.querySelector('#session-profile').onchange = update;
document.querySelector('#session-accounting').onchange = update;
document.querySelector('#width').onchange = (e) => (
  document.querySelectorAll('.column').forEach((c) => (c.style.width = e.target.value + 'px')),
  document
    .querySelectorAll('.session-column')
    .forEach((c) => (c.style.width = `${Number(e.target.value) * 2 + 28}px`))
);
document.querySelector('#goal-state').onchange = selectGoalExample;
document.querySelector('#goal-kind').onchange = selectGoalExample;
document.querySelector('#target-notice').onchange = update;
update();

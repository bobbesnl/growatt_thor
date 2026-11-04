import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import test from 'node:test';
import { buildCardViewModel } from '../src/charger/card-view-model';
import { renderCard, type CardActions } from '../src/charger/card.template';
import type { CardConfig, CardData, Entity, Hass } from '../src/shared/types';
import { entity, hass, makeData } from './fixtures';

const FIXTURE = new URL('./fixtures/charger-card-markup.json', import.meta.url);
// Asset URLs resolve against the module file, so they carry the checkout path.
const REPOSITORY_URL = new URL('../../', import.meta.url).href;
const now = Date.parse('2026-09-09T12:00:00Z');
const idleCommand = { issuedAt: 0, sending: false };
const actions: CardActions = {
  command: async () => {},
  moreInfo: () => {},
  openGoalPreview: () => {},
  setGoal: async () => {},
  cancelGoal: async () => {},
  openAuth: () => {},
  openPv: () => {},
};

/** Flatten Lit templates, retaining attributes and content while ignoring directive identity. */
function markup(value: unknown): string {
  if (value == null || typeof value === 'symbol') return '';
  if (typeof value === 'function') return '__handler__';
  if (Array.isArray(value)) return value.map(markup).join('');
  if (typeof value === 'object') {
    if ('strings' in value && 'values' in value) {
      const template = value as { strings: string[]; values: unknown[] };
      return template.strings
        .map(
          (text, index) =>
            text + (index < template.values.length ? markup(template.values[index]) : ''),
        )
        .join('');
    }
    return '__directive__';
  }
  return String(value);
}

interface Scenario {
  state: string;
  data?: Partial<CardData>;
  connected?: boolean;
  states?: Hass['states'];
}

const pvLinkage: CardData['pv_linkage'] = {
  working_mode: 'pv_linkage',
  grid_import_limit_kw: 1.5,
  boost_mode: 'manual',
  manual_start: '10:00',
  manual_end: '12:00',
  smart_finish: null,
  smart_target_energy_kwh: null,
  draft_dirty: true,
  blocked_reason: null,
  last_apply: { status: 'partial', completed_steps: 1, total_steps: 2 },
};
const fault: Entity = {
  entity_id: 'sensor.last_fault',
  state: 'ground_failure',
  attributes: { message: 'Residual current' },
};

const scenarios: Record<string, Scenario> = {
  charging: { state: 'charging' },
  preparing: {
    state: 'preparing',
    data: { transaction_active: false, power_w: 0, currents_a: [0, 0, 0] },
  },
  available: {
    state: 'available',
    data: { transaction_active: false, session_started_at: null, session_energy_kwh: null },
  },
  suspended: { state: 'suspended_ev', data: { power_w: 0, currents_a: [0, 0, 0] } },
  faulted: {
    state: 'faulted',
    data: { transaction_active: false, status_info: 'Ground fault', error_code: 'GroundFailure' },
  },
  offline: { state: 'charging', connected: false },
  unavailable: { state: 'unavailable' },
  stale: {
    state: 'charging',
    data: { meter_received_at: '2026-09-09T11:00:00Z', sample_at: '2026-09-09T11:00:00Z' },
  },
  over_power: { state: 'charging', data: { power_w: 13500 } },
  meter_fault: {
    state: 'charging',
    data: { working_mode: 'pv_linkage_plus', external_meter_health: 'modbus_fault' },
  },
  pv_linkage: { state: 'charging', data: { working_mode: 'pv_linkage', pv_linkage: pvLinkage } },
  rebooting: {
    state: 'available',
    data: {
      transaction_active: false,
      charger_rebooting: true,
      working_mode: 'pv_linkage',
      pv_linkage: pvLinkage,
    },
  },
  target_and_command: {
    state: 'preparing',
    data: {
      transaction_active: false,
      charging_target_pilot: true,
      charging_target: {
        request_id: 'target-1',
        kind: 'energy',
        value: '10',
        state: 'scheduled',
        activation: 'remote',
        scheduled_for: '2026-09-09T22:00:00Z',
        updated_at: '2026-09-09T11:00:00Z',
      },
      command: { action: 'start', state: 'uncertain', updated_at: '2026-09-09T11:59:00Z' },
    },
  },
  energy_stop_and_past_fault: {
    state: 'available',
    data: {
      transaction_active: false,
      entities: { ...makeData().entities, last_charger_fault: fault.entity_id },
      energy_stop: {
        reason: 'battery',
        at: '2026-09-09T11:30:00Z',
        threshold_w: 500,
        hold_seconds: 60,
        observed_w: 800,
      },
    },
    states: { [fault.entity_id]: fault },
  },
};

function renderCases(): Map<string, string> {
  const rendered = new Map<string, string>();
  for (const language of ['en', 'de'])
    for (const theme of ['light', 'dark'] as const)
      for (const [scenario, { state, data: extra, connected, states }] of Object.entries(scenarios))
        for (const compact of [false, true])
          for (const feedback of [
            { error: '', sending: false },
            { error: 'Command failed', sending: true },
          ]) {
            const config: CardConfig = {
              type: 'custom:growatt-thor-card',
              name: 'THOR',
              theme,
              ...(compact
                ? { show_image: false, show_phases: false, show_session: false, max_power: 7.4 }
                : {}),
            };
            const data = makeData(extra);
            const view = buildCardViewModel(
              {
                ...hass,
                language,
                connected,
                states: { ...hass.states, ...states },
                config: { time_zone: 'Europe/Berlin', currency: 'EUR' },
              } as Hass,
              config,
              entity(state, data),
              data,
              now,
              idleCommand,
            );
            const text = markup(renderCard(view, actions, feedback))
              .replace(/\s+/g, ' ')
              .replace(/>\s+</g, '><')
              .replaceAll(REPOSITORY_URL, 'repository:/');
            const name = [language, theme, scenario, compact, !!feedback.error].join('-');
            rendered.set(name, createHash('sha256').update(text).digest('hex'));
          }
  return rendered;
}

test('charger card templates preserve their markup across themes, states and card options', () => {
  const rendered = renderCases();
  // Regenerate only on purpose: UPDATE_CARD_MARKUP=1 npm test
  if (process.env.UPDATE_CARD_MARKUP) {
    writeFileSync(FIXTURE, JSON.stringify(Object.fromEntries(rendered), null, 2) + '\n');
  }
  const contracts: Record<string, string> = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  assert.deepEqual([...rendered.keys()].sort(), Object.keys(contracts).sort());
  for (const [name, hash] of rendered) assert.equal(hash, contracts[name], name);
  // The scenarios must reach different markup, or the contract would prove little.
  assert.ok(new Set(rendered.values()).size > Object.keys(scenarios).length * 4);
});

test('a charger reboot blocks Start, the limit and both header pills and says why', () => {
  const data = makeData({
    transaction_active: false,
    charger_rebooting: true,
    working_mode: 'pv_linkage',
    pv_linkage: pvLinkage,
  });
  const view = buildCardViewModel(
    { ...hass, language: 'de' } as Hass,
    { type: 'custom:growatt-thor-card' },
    entity('available', data),
    data,
    now,
    idleCommand,
  );
  assert.equal(view.status.key, 'rebooting');
  assert.ok(view.inactive && view.rebooting);
  assert.equal(view.caps.start, false);
  assert.equal(view.caps.limit, false);

  const text = markup(renderCard(view, actions, { error: '', sending: false }));
  assert.ok(text.includes(view.t('rebootingNotice')));
  const pills = text.slice(text.indexOf('class="pills"'), text.indexOf('</header>'));
  assert.equal(pills.match(/\?disabled=true/g)?.length, 2);

  // Without the reboot the same card is usable again.
  const ready = makeData({ ...data, charger_rebooting: false });
  const after = buildCardViewModel(
    hass,
    { type: 'custom:growatt-thor-card' },
    entity('available', ready),
    ready,
    now,
    idleCommand,
  );
  assert.equal(after.rebooting, false);
  assert.equal(after.caps.start, true);
});

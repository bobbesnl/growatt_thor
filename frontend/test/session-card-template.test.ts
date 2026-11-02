import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createRef } from 'lit/directives/ref.js';
import { renderSessionCard } from '../src/sessions/card.template';
import { sessionPage, sessionRows } from '../src/sessions/model';
import { sessionTranslate } from '../src/sessions/locales';
import { sessionFixture, sessionHistory } from './session-card-fixtures';

type View = Parameters<typeof renderSessionCard>[0];
type Actions = Parameters<typeof renderSessionCard>[1];
const contracts: Record<string, string> = JSON.parse(
  readFileSync(new URL('./fixtures/session-card-markup.json', import.meta.url), 'utf8'),
);
const actions: Actions = {
  search: () => {},
  sort: () => {},
  selectSession: () => {},
  goToPage: () => {},
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

function renderCases(): { name: string; view: View }[] {
  const cases: { name: string; view: View }[] = [];
  for (const language of ['en', 'de'])
    for (const dark of [false, true])
      for (const kind of ['active', 'completed', 'empty'])
        for (const showCurve of [false, true])
          for (const showIdentifier of [false, true])
            for (const curveStatus of ['idle', 'loading', 'error'] as const) {
              const row = sessionFixture({
                active: kind === 'active',
                end_time: kind === 'active' ? null : '2026-10-30T23:10:00Z',
                power_curve: kind === 'active' ? [] : undefined,
              });
              const selected = kind === 'empty' ? undefined : row;
              const data = sessionHistory(
                selected
                  ? [
                      row,
                      sessionFixture({
                        session_id: 'older',
                        start_time: null,
                        authorized_identifier: null,
                        authorized_alias: null,
                        energy_kwh: null,
                        cost: null,
                        green_energy_kwh: null,
                      }),
                    ]
                  : [],
              );
              cases.push({
                name: [language, dark, kind, showCurve, showIdentifier, curveStatus].join('-'),
                view: {
                  name: sessionTranslate(language)('title'),
                  dark,
                  language,
                  timeZone: 'Europe/Berlin',
                  currency: 'EUR',
                  data,
                  page: sessionPage(sessionRows(data, '', 'start', false), 0, 1),
                  selected,
                  query: '',
                  sort: 'start',
                  ascending: false,
                  showCurve,
                  showIdentifier,
                  curveStatus,
                  chartRef: createRef(),
                  tableRef: createRef(),
                },
              });
            }
  return cases;
}

test('session templates preserve pre-extraction markup across themes, states and card options', () => {
  for (const { name, view } of renderCases()) {
    const text = markup(renderSessionCard(view, actions))
      .replace(/\s+/g, ' ')
      .replace(/>\s+</g, '><');
    const hash = createHash('sha256').update(text).digest('hex');
    assert.equal(hash, contracts[name], name);
  }
});

function handlers(value: unknown, name: string): ((event?: unknown) => void)[] {
  if (Array.isArray(value)) return value.flatMap((item) => handlers(item, name));
  if (value === null || typeof value !== 'object' || !('strings' in value) || !('values' in value))
    return [];
  const template = value as { strings: string[]; values: unknown[] };
  return template.values.flatMap((item, index) =>
    typeof item === 'function' && template.strings[index].trimEnd().endsWith(`@${name}=`)
      ? [item as (event?: unknown) => void]
      : handlers(item, name),
  );
}

test('templates retain search, sorting, keyboard selection and pagination callbacks', () => {
  const view = renderCases().find((item) => item.name === 'en-false-active-true-true-idle')!.view;
  const calls: unknown[] = [];
  const result = renderSessionCard(view, {
    search: (event) => calls.push(['search', event]),
    sort: (key) => calls.push(['sort', key]),
    selectSession: (id) => calls.push(['select', id]),
    goToPage: (index, scroll) => calls.push(['page', index, scroll]),
  });
  const search = { target: { value: 'car' } };
  handlers(result, 'input')[0](search);
  handlers(result, 'click')[0]();
  let prevented = 0;
  for (const key of ['Enter', ' ', 'Escape'])
    handlers(result, 'keydown')[0]({ key, preventDefault: () => prevented++ });
  handlers(result, 'click').at(-1)!();
  assert.equal(prevented, 2);
  assert.deepEqual(calls, [
    ['search', search],
    ['sort', 'start'],
    ['select', 'session-42'],
    ['select', 'session-42'],
    ['page', 1, true],
  ]);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { chargerEditorFields } from '../src/charger/editor.template';
import { sessionEditorFields } from '../src/sessions/editor-fields';
import { sessionTranslate } from '../src/sessions/locales';
import { applyEditorValue, editorFormData } from '../src/shared/editor-form';
import { translate } from '../src/shared/strings';
import type { CardConfig, SessionCardConfig } from '../src/shared/types';
import { entity } from './fixtures';

const chargers = [entity('charging')];
const t = translate('en');

test('charger editor shows card defaults and selects only THOR status entities', () => {
  const config: CardConfig = { type: 'custom:growatt-thor-card', entry_id: 'one' };
  const fields = chargerEditorFields(chargers, 'sensor.renamed', t);

  assert.deepEqual(
    fields.map((field) => [field.name, Object.keys(field.selector)[0]]),
    [
      ['entity', 'entity'],
      ['name', 'text'],
      ['max_power', 'number'],
      ['theme', 'select'],
      ['show_image', 'boolean'],
      ['show_phases', 'boolean'],
      ['show_session', 'boolean'],
    ],
  );
  assert.deepEqual(fields[0].selector, { entity: { include_entities: ['sensor.renamed'] } });
  assert.deepEqual(editorFormData(config, fields), {
    entity: 'sensor.renamed',
    name: undefined,
    max_power: undefined,
    theme: 'auto',
    show_image: true,
    show_phases: true,
    show_session: true,
  });
  assert.equal(fields[2].helper, t('maximumHint'));
  assert.deepEqual(
    (fields[3].selector.select as { options: { label: string }[] }).options.map((o) => o.label),
    [t('auto'), t('light'), t('dark')],
  );
});

test('editor writes only the options a change touched', () => {
  const config: CardConfig = { type: 'custom:growatt-thor-card', name: 'Garage', max_power: 7.4 };
  const fields = chargerEditorFields(chargers, '', t);
  const shown = editorFormData(config, fields);

  assert.equal(applyEditorValue(config, fields, shown), undefined);
  assert.deepEqual(applyEditorValue(config, fields, { ...shown, show_phases: false }), {
    config: { ...config, show_phases: false },
    changed: ['show_phases'],
  });
  // Emptied options return to the card default instead of storing a blank value.
  assert.deepEqual(applyEditorValue(config, fields, { ...shown, name: '', max_power: undefined }), {
    config: { type: 'custom:growatt-thor-card' },
    changed: ['name', 'max_power'],
  });
  assert.deepEqual(applyEditorValue(config, fields, { ...shown, theme: 'dark' })?.config, {
    ...config,
    theme: 'dark',
  });
});

test('out-of-range numbers keep the previous option', () => {
  const config: CardConfig = { type: 'custom:growatt-thor-card', max_power: 7.4 };
  const fields = chargerEditorFields(chargers, '', t);
  const shown = editorFormData(config, fields);
  for (const max_power of [0, 100.5, Number.NaN, '11'])
    assert.equal(
      applyEditorValue(config, fields, { ...shown, max_power }),
      undefined,
      `${max_power}`,
    );
  assert.equal(applyEditorValue(config, fields, { ...shown, max_power: 22 })?.config.max_power, 22);

  const session: SessionCardConfig = { type: 'custom:growatt-thor-session-card' };
  const sessionFields = sessionEditorFields(chargers, '', sessionTranslate('en'));
  const sessionShown = editorFormData(session, sessionFields);
  assert.equal(sessionShown.rows, 10);
  for (const rows of [0, 21, 2.5])
    assert.equal(applyEditorValue(session, sessionFields, { ...sessionShown, rows }), undefined);
  assert.deepEqual(applyEditorValue(session, sessionFields, { ...sessionShown, rows: 6 })?.config, {
    ...session,
    rows: 6,
  });
});

test('session editor shows its defaults with translated labels', () => {
  const de = sessionTranslate('de');
  const fields = sessionEditorFields(chargers, 'sensor.renamed', de);

  assert.deepEqual(
    fields.map((field) => [field.name, field.label]),
    [
      ['entity', de('charger')],
      ['rows', 'Zeilen'],
      ['show_curve', 'Diagramm anzeigen'],
      ['show_identifier', de('showIdentifier')],
    ],
  );
  assert.deepEqual(editorFormData({ type: 'x' } as SessionCardConfig, fields), {
    entity: 'sensor.renamed',
    rows: 10,
    show_curve: true,
    show_identifier: true,
  });
});

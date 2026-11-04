import { html } from 'lit';
import { numberWithin, renderEditorForm, type EditorField } from '../shared/editor-form';
import type { CardConfig, Entity } from '../shared/types';
import type { Translator } from '../shared/strings';

/** Card options in the order the editor shows them; defaults match the card. */
export function chargerEditorFields(
  entities: Entity[],
  entity: string,
  t: Translator,
): EditorField<CardConfig>[] {
  return [
    {
      name: 'entity',
      label: t('statusEntity'),
      selector: { entity: { include_entities: entities.map((item) => item.entity_id) } },
      fallback: entity || undefined,
    },
    { name: 'name', label: t('name'), selector: { text: {} } },
    {
      name: 'max_power',
      label: t('maximum'),
      helper: t('maximumHint'),
      selector: {
        number: { min: 0.1, max: 100, step: 0.1, mode: 'box', unit_of_measurement: 'kW' },
      },
      accept: numberWithin(0.1, 100),
    },
    {
      name: 'theme',
      label: t('theme'),
      selector: {
        select: {
          mode: 'dropdown',
          options: ['auto', 'light', 'dark'].map((value) => ({ value, label: t(value) })),
        },
      },
      fallback: 'auto',
    },
    { name: 'show_image', label: t('image'), selector: { boolean: {} }, fallback: true },
    { name: 'show_phases', label: t('phaseOption'), selector: { boolean: {} }, fallback: true },
    { name: 'show_session', label: t('sessionOption'), selector: { boolean: {} }, fallback: true },
  ];
}

export function renderEditor(
  hass: unknown,
  config: CardConfig,
  fields: EditorField<CardConfig>[],
  hasChargers: boolean,
  t: Translator,
  onValue: (value: Record<string, unknown>) => void,
) {
  return html`${renderEditorForm(hass, config, fields, onValue)}
  ${hasChargers ? '' : html`<small>${t('noChargers')}</small>`}`;
}

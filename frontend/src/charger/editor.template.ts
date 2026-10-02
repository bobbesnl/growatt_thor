import { html } from 'lit';
import type { CardConfig, Entity } from '../shared/types';
import type { Translator } from '../shared/strings';

export type EditorChange = (key: keyof CardConfig, value: unknown) => void;
export function renderEditor(
  config: CardConfig,
  entities: Entity[],
  entity: string,
  t: Translator,
  change: EditorChange,
) {
  return html`
    <label
      >${t('statusEntity')}<select
        .value=${entity}
        @change=${(e: Event) => change('entity', (e.target as HTMLSelectElement).value)}
      >
        <option value="">${t('selectCharger')}</option>
        ${entities.map(
          (e) =>
            html`<option value=${e.entity_id} ?selected=${e.entity_id === entity}>
              ${e.attributes.friendly_name || e.entity_id}
            </option>`,
        )}
      </select></label
    >
    ${entities.length ? '' : html`<small>${t('noChargers')}</small>`}
    <label
      >${t('name')}<input
        .value=${config.name || ''}
        placeholder="THOR"
        @change=${(e: Event) => change('name', (e.target as HTMLInputElement).value)}
    /></label>
    <label
      >${t('maximum')}<input
        type="number"
        min="0.1"
        max="100"
        step="0.1"
        placeholder="Auto"
        .value=${String(config.max_power || '')}
        @change=${(e: Event) => {
          const input = e.target as HTMLInputElement;
          if (input.checkValidity())
            change('max_power', input.value ? Number(input.value) : undefined);
        }} /></label
    ><small>${t('maximumHint')}</small>
    <label
      >${t('theme')}<select
        .value=${config.theme || 'auto'}
        @change=${(e: Event) => change('theme', (e.target as HTMLSelectElement).value)}
      >
        ${['auto', 'light', 'dark'].map(
          (v) =>
            html`<option value=${v} ?selected=${(config.theme || 'auto') === v}>${t(v)}</option>`,
        )}
      </select></label
    >
    ${(['show_image', 'show_phases', 'show_session'] as const).map(
      (key, i) =>
        html`<label
          ><input
            type="checkbox"
            .checked=${config[key] !== false}
            @change=${(e: Event) => change(key, (e.target as HTMLInputElement).checked)}
          />${t(['image', 'phaseOption', 'sessionOption'][i])}</label
        >`,
    )}
  `;
}

import { LitElement, html, unsafeCSS } from 'lit';
import { statusEntities } from '../shared/model';
import { sessionTranslate } from './locales';
import type { Hass, SessionCardConfig } from '../shared/types';

export class ThorSessionEditor extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true } };
  static styles = unsafeCSS(`
    div { display: grid; gap: 14px; padding: 8px; }
    label { display: grid; gap: 6px; }
    input, select { font: inherit; padding: 8px; }
  `);
  hass?: Hass;
  private _config: SessionCardConfig = { type: 'custom:growatt-thor-session-card' };

  setConfig(config: SessionCardConfig) {
    this._config = { ...config };
  }
  private change(key: keyof SessionCardConfig, value: unknown) {
    this._config = { ...this._config, [key]: value };
    this.dispatchEvent(
      new CustomEvent('config-changed', {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      }),
    );
  }
  render() {
    const t = sessionTranslate(this.hass?.language || this.hass?.locale?.language);
    const entities = this.hass ? statusEntities(this.hass) : [];
    return html`<div>
      <label
        >${t('charger')}<select
          @change=${(event: Event) => {
            const entity = (event.target as HTMLSelectElement).value;
            this._config = {
              ...this._config,
              entry_id: this.hass?.states[entity]?.attributes.thor_card?.entry_id,
            };
            this.change('entity', entity);
          }}
        >
          ${entities.map(
            (entity) =>
              html`<option
                value=${entity.entity_id}
                ?selected=${entity.entity_id === this._config.entity}
              >
                ${entity.entity_id}
              </option>`,
          )}
        </select></label
      >
      <label
        >${t('rows')}<input
          type="number"
          min="1"
          max="20"
          .value=${String(this._config.rows || 10)}
          @change=${(event: Event) =>
            this.change('rows', Number((event.target as HTMLInputElement).value))}
      /></label>
      <label
        ><input
          type="checkbox"
          .checked=${this._config.show_curve !== false}
          @change=${(event: Event) =>
            this.change('show_curve', (event.target as HTMLInputElement).checked)}
        />${t('showCurve')}</label
      >
      <label
        ><input
          type="checkbox"
          .checked=${this._config.show_identifier !== false}
          @change=${(event: Event) =>
            this.change('show_identifier', (event.target as HTMLInputElement).checked)}
        />${t('showIdentifier')}</label
      >
    </div>`;
  }
}

if (!customElements.get('growatt-thor-session-card-editor'))
  customElements.define('growatt-thor-session-card-editor', ThorSessionEditor);

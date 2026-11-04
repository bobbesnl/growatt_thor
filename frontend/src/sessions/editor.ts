import editorCss from './editor.css';
import { LitElement, unsafeCSS } from 'lit';
import { applyEditorValue, renderEditorForm } from '../shared/editor-form';
import { sessionEditorFields } from './editor-fields';
import { statusEntities } from '../shared/model';
import { sessionTranslate } from './locales';
import type { Hass, SessionCardConfig } from '../shared/types';

export class ThorSessionEditor extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true } };
  static styles = [unsafeCSS(editorCss)];
  hass?: Hass;
  private _config: SessionCardConfig = { type: 'custom:growatt-thor-session-card' };

  setConfig(config: SessionCardConfig) {
    this._config = { ...config };
  }
  private fields() {
    const t = sessionTranslate(this.hass?.language || this.hass?.locale?.language);
    const entities = this.hass ? statusEntities(this.hass) : [];
    const entity =
      entities.find((e) => e.attributes.thor_card.entry_id === this._config.entry_id)?.entity_id ||
      this._config.entity ||
      '';
    return sessionEditorFields(entities, entity, t);
  }
  private readonly onValue = (value: Record<string, unknown>) => {
    const result = applyEditorValue(this._config, this.fields(), value);
    if (!result) return;
    const { config, changed } = result;
    if (changed.includes('entity'))
      config.entry_id = this.hass?.states[String(config.entity)]?.attributes.thor_card?.entry_id;
    this._config = config;
    this.dispatchEvent(
      new CustomEvent('config-changed', {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      }),
    );
  };
  render() {
    return renderEditorForm(this.hass, this._config, this.fields(), this.onValue);
  }
}

if (!customElements.get('growatt-thor-session-card-editor'))
  customElements.define('growatt-thor-session-card-editor', ThorSessionEditor);

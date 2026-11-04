import { LitElement, unsafeCSS } from 'lit';
import editorCss from './editor.css';
import { chargerEditorFields, renderEditor } from './editor.template';
import { applyEditorValue } from '../shared/editor-form';
import { statusEntities } from '../shared/model';
import { translate } from '../shared/strings';
import type { CardConfig, Hass } from '../shared/types';

export class ThorCardEditor extends LitElement {
  static properties = { hass: { attribute: false }, config: { state: true } };
  static styles = [unsafeCSS(editorCss)];
  hass?: Hass;
  config: CardConfig = { type: 'custom:growatt-thor-card' };
  setConfig(config: CardConfig) {
    this.config = { ...config };
  }
  private fields() {
    const t = translate(this.hass?.language || this.hass?.locale?.language);
    const entities = this.hass ? statusEntities(this.hass) : [];
    const entity =
      entities.find((e) => e.attributes.thor_card.entry_id === this.config.entry_id)?.entity_id ||
      this.config.entity ||
      '';
    return { t, entities, fields: chargerEditorFields(entities, entity, t) };
  }
  private readonly onValue = (value: Record<string, unknown>) => {
    const result = applyEditorValue(this.config, this.fields().fields, value);
    if (!result) return;
    const { config, changed } = result;
    // The entry ID keeps the card bound to its charger when the entity is renamed.
    if (changed.includes('entity'))
      config.entry_id = this.hass?.states[String(config.entity)]?.attributes.thor_card?.entry_id;
    this.config = config;
    this.dispatchEvent(
      new CustomEvent('config-changed', { detail: { config }, bubbles: true, composed: true }),
    );
  };
  render() {
    const { t, entities, fields } = this.fields();
    return renderEditor(this.hass, this.config, fields, entities.length > 0, t, this.onValue);
  }
}
if (!customElements.get('growatt-thor-card-editor'))
  customElements.define('growatt-thor-card-editor', ThorCardEditor);

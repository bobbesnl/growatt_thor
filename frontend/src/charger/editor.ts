import { LitElement, unsafeCSS } from 'lit';
import editorCss from './editor.css';
import { renderEditor, type EditorChange } from './editor.template';
import { statusEntities } from '../shared/model';
import { translate } from '../shared/strings';
import type { CardConfig, Hass } from '../shared/types';

export class ThorCardEditor extends LitElement {
  static properties = { hass: { attribute: false }, config: { state: true } };
  static styles = unsafeCSS(editorCss);
  hass?: Hass;
  config: CardConfig = { type: 'custom:growatt-thor-card' };
  setConfig(config: CardConfig) {
    this.config = { ...config };
  }
  private readonly onChange: EditorChange = (key, value) => this.change(key, value);
  private change(key: keyof CardConfig, value: unknown) {
    const config = { ...this.config, [key]: value };
    if (value === '' || value === undefined) delete config[key];
    if (key === 'entity')
      config.entry_id = this.hass?.states[String(value)]?.attributes.thor_card?.entry_id;
    this.config = config;
    this.dispatchEvent(
      new CustomEvent('config-changed', { detail: { config }, bubbles: true, composed: true }),
    );
  }
  render() {
    const t = translate(this.hass?.language || this.hass?.locale?.language);
    const entities = this.hass ? statusEntities(this.hass) : [];
    const entity =
      entities.find((e) => e.attributes.thor_card.entry_id === this.config.entry_id)?.entity_id ||
      this.config.entity ||
      '';
    return renderEditor(this.config, entities, entity, t, this.onChange);
  }
}
if (!customElements.get('growatt-thor-card-editor'))
  customElements.define('growatt-thor-card-editor', ThorCardEditor);

import { LitElement, unsafeCSS } from 'lit';
import type { Hass } from '../shared/types';
import { translate } from '../shared/strings';
import { renderAuthDialog } from './dialog.template';
import cssText from './dialog.css';

export class ThorAuthDialog extends LitElement {
  static styles = unsafeCSS(cssText);
  static properties = {
    hass: { attribute: false },
    entityId: {},
    option: { state: true },
    busy: { state: true },
    error: { state: true },
  };
  hass?: Hass;
  entityId = '';
  option = '';
  busy = false;
  error = '';
  get available() {
    const state = this.hass?.states[this.entityId];
    return (
      this.hass?.connected !== false && !!state && !['unavailable', 'unknown'].includes(state.state)
    );
  }
  async open(entityId: string) {
    this.entityId = entityId;
    this.option = this.hass?.states[entityId]?.state || '';
    this.error = '';
    await this.updateComplete;
    this.renderRoot.querySelector('dialog')?.showModal();
  }
  close() {
    if (!this.busy) this.renderRoot.querySelector('dialog')?.close();
  }
  async apply() {
    if (!this.available || this.busy) return;
    const state = this.hass!.states[this.entityId];
    if (!state || !(state.attributes.options || []).includes(this.option)) return;
    if (state.state === this.option) {
      this.close();
      return;
    }
    this.busy = true;
    this.error = '';
    try {
      await this.hass!.callService('select', 'select_option', {
        entity_id: this.entityId,
        option: this.option,
      });
      // Service completion means queued, not confirmed by the charger.
      this.busy = false;
      this.close();
    } catch {
      this.error = 'callError';
    } finally {
      this.busy = false;
    }
  }
  render() {
    return renderAuthDialog(this, translate(this.hass?.language || this.hass?.locale?.language));
  }
}
if (!customElements.get('growatt-thor-auth-dialog'))
  customElements.define('growatt-thor-auth-dialog', ThorAuthDialog);

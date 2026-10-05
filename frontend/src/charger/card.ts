import { LitElement } from 'lit';
import { styles } from './styles';
import { capabilities, commandInfo, resolveEntity, statusEntities } from '../shared/model';
import { buildCardViewModel } from './card-view-model';
import { renderCard, type CardActions } from './card.template';
import { cardInitialization } from '../shared/card-initialization';
import { cardNoticeStyles, renderCardNotice } from '../shared/card-notice';
import {
  liveGoalAvailable,
  oneTimeGoalAvailable,
  scheduledGoalAvailable,
  canReplace,
  validLiveTarget,
} from '../targets/live';
import type { GoalKind, GoalRecurrence } from '../targets/model';
import type { CardConfig, Hass } from '../shared/types';
import './editor';
import '../targets/dialog';
import '../authorization/dialog';
import type { ThorAuthDialog } from '../authorization/dialog';
import '../pv/dialog';
import type { ThorPvLinkageDialog } from '../pv/dialog';
import type { ThorGoalDialog } from '../targets/dialog';
import '../sessions/card';

export class ThorCard extends LitElement {
  static styles = [styles, cardNoticeStyles];
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _now: { state: true },
    _sending: { state: true },
    _error: { state: true },
  };
  hass?: Hass;
  private _config: CardConfig = { type: 'custom:growatt-thor-card' };
  private _now = Date.now();
  private _sending = false;
  private _issuedAt = 0;
  private _error = '';
  private readonly viewActions: CardActions = {
    command: (action) => this.command(action),
    moreInfo: (entity) => this.moreInfo(entity),
    openGoalPreview: () => this.openGoalPreview(),
    setGoal: (kind, value, startAt, recurrence, replaceId) =>
      this.setGoal(kind, value, startAt, recurrence, replaceId),
    cancelGoal: (requestId) => this.cancelGoal(requestId),
    openAuth: (entity) => {
      if (entity)
        void this.renderRoot
          .querySelector<ThorAuthDialog>('growatt-thor-auth-dialog')
          ?.open(entity);
    },
    openPv: (entity, data) => {
      if (data)
        void this.renderRoot
          .querySelector<ThorPvLinkageDialog>('growatt-thor-pv-linkage-dialog')
          ?.open(entity, data);
    },
  };
  private _timer?: ReturnType<typeof setInterval>;

  setConfig(config: CardConfig) {
    if (!config || (config.entity && !config.entity.startsWith('sensor.')))
      throw new Error('Select the THOR status sensor.');
    if (
      config.max_power !== undefined &&
      (typeof config.max_power !== 'number' ||
        !Number.isFinite(config.max_power) ||
        config.max_power <= 0 ||
        config.max_power > 100)
    )
      throw new Error('max_power must be between 0 and 100 kW.');
    if (config.theme && !['auto', 'light', 'dark'].includes(config.theme))
      throw new Error('theme: auto, light or dark');
    this._config = { ...config };
    this._error = '';
  }
  static getConfigElement() {
    return document.createElement('growatt-thor-card-editor');
  }
  static getStubConfig(hass?: Hass) {
    const entity = hass && statusEntities(hass)[0];
    return { entity: entity?.entity_id, entry_id: entity?.attributes.thor_card.entry_id };
  }
  getCardSize() {
    return 13;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 7 };
  }
  connectedCallback() {
    super.connectedCallback();
    this._now = Date.now();
    this._timer = setInterval(() => {
      this._now = Date.now();
    }, 5000);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._timer);
  }
  private moreInfo(entity?: string) {
    if (entity)
      this.dispatchEvent(
        new CustomEvent('hass-more-info', {
          detail: { entityId: entity },
          bubbles: true,
          composed: true,
        }),
      );
  }
  private openGoalPreview() {
    void this.renderRoot.querySelector<ThorGoalDialog>('growatt-thor-goal-dialog')?.open();
  }
  private async setGoal(
    kind: GoalKind,
    value: number,
    startAt?: string,
    recurrence: GoalRecurrence = 'once',
    replaceId?: string,
  ) {
    const hass = this.hass;
    const entity = hass && resolveEntity(hass, this._config);
    const data = entity?.attributes.thor_card;
    if (
      !hass ||
      !entity ||
      !data ||
      !(startAt
        ? recurrence === 'daily'
          ? scheduledGoalAvailable(hass, entity, data)
          : oneTimeGoalAvailable(hass, entity, data)
        : liveGoalAvailable(hass, entity, data)) ||
      !validLiveTarget(kind, value)
    )
      throw new Error('goal_unavailable');
    if (data.charging_target) {
      const replaceable = canReplace(data.charging_target, kind, value);
      if (!replaceable || replaceId !== data.charging_target.request_id)
        throw new Error('target_conflict');
    }
    const service = startAt
      ? 'schedule_charging_target'
      : data.auth_mode === 'rfid_only'
        ? 'prepare_rfid_charging_target'
        : data.auth_mode === 'plug_and_charge' && entity.state === 'available'
          ? 'prepare_plug_charging_target'
          : 'start_charging_target';
    await hass.callService('growatt_thor', service, {
      entry_id: data.entry_id,
      kind,
      value: String(value),
      ...(startAt ? { start_at: startAt, recurrence } : {}),
      confirm_experimental: true,
      ...(replaceId ? { replace_request_id: replaceId } : {}),
    });
  }
  private async cancelGoal(requestId: string) {
    if (!this.hass) throw new Error('goal_unavailable');
    await this.hass.callService('growatt_thor', 'cancel_scheduled_charging_target', {
      request_id: requestId,
      confirm_cancel: true,
    });
  }
  private async command(action: 'start' | 'stop') {
    const hass = this.hass;
    if (!hass || this._sending) return;
    const entity = resolveEntity(hass, this._config);
    const data = entity?.attributes.thor_card;
    if (!entity || !data) return;
    const connected = hass.connected !== false && entity.attributes.connected === true;
    const pending = commandInfo(data, entity.state, Date.now()).pending;
    if (!capabilities(hass, data, entity, connected, pending)[action]) return;
    const target = data.entities[`${action}_charging`];
    this._sending = true;
    this._issuedAt = Date.now();
    this._error = '';
    try {
      await hass.callService('button', 'press', { entity_id: target });
      // Backend publishes queued/sending/accepted/rejected. A service reply alone is NOT confirmation.
    } catch {
      this._error = 'callError';
      this._issuedAt = 0;
    } finally {
      this._sending = false;
      this._now = Date.now();
    }
  }

  render() {
    const hass = this.hass;
    const config = this._config;
    const language = hass?.language || hass?.locale?.language || 'en';
    const dark = config.theme === 'dark' || (config.theme !== 'light' && !!hass?.themes?.darkMode);
    const entity = hass && resolveEntity(hass, config);
    const data = entity?.attributes.thor_card;
    const initialization = cardInitialization(hass, config);
    if (initialization !== 'ready' || !hass || !entity || !data)
      return renderCardNotice(initialization, language, dark, config.name || 'Growatt THOR');
    const view = buildCardViewModel(hass, config, entity, data, this._now, {
      issuedAt: this._issuedAt,
      sending: this._sending,
    });
    return renderCard(view, this.viewActions, { error: this._error, sending: this._sending });
  }
}

if (!customElements.get('growatt-thor-card')) customElements.define('growatt-thor-card', ThorCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === 'growatt-thor-card'))
  window.customCards.push({
    type: 'growatt-thor-card',
    name: 'Growatt THOR',
    preview: true,
    description:
      'Wallbox control, live charging power and phases. / Wallbox, Ladeleistung und Phasen.',
    documentationURL: 'https://github.com/bobbesnl/growatt_thor#growatt-thor-dashboard-card',
    getEntitySuggestion: (hass: Hass, id: string) =>
      hass.states[id]?.attributes.thor_card?.schema === 1
        ? {
            config: {
              type: 'custom:growatt-thor-card',
              entity: id,
              entry_id: hass.states[id]?.attributes.thor_card?.entry_id,
            },
          }
        : null,
  });

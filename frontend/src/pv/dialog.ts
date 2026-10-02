import { LitElement, unsafeCSS } from 'lit';
import type { CardData, Hass, PvLinkageData } from '../shared/types';
import {
  initialPvDraft,
  pvDraftErrors,
  pvServicePayload,
  type PvBoost,
  type PvLinkageDraft,
  type PvMode,
} from './model';
import { pvTranslate } from './locales';
import { renderPvLinkageDialog } from './dialog.template';
import cssText from './dialog.css';

export class ThorPvLinkageDialog extends LitElement {
  static styles = unsafeCSS(cssText);
  static properties = {
    hass: { attribute: false },
    entityId: {},
    step: { state: true },
    draft: { state: true },
    busy: { state: true },
    error: { state: true },
  };
  hass?: Hass;
  entityId = '';
  step = 0;
  draft: PvLinkageDraft = initialPvDraft({
    working_mode: 'pv_linkage_plus',
    grid_import_limit_kw: 0,
    boost_mode: 'disabled',
    manual_start: null,
    manual_end: null,
    smart_finish: null,
    smart_target_energy_kwh: null,
    draft_dirty: false,
    blocked_reason: null,
  });
  busy = false;
  error = '';

  get cardData(): CardData | undefined {
    return this.hass?.states[this.entityId]?.attributes.thor_card;
  }
  get pvData(): PvLinkageData | undefined {
    return this.cardData?.pv_linkage;
  }
  get blockedReason(): string | null {
    return this.pvData?.blocked_reason || null;
  }
  get errors(): string[] {
    return pvDraftErrors(this.draft);
  }

  async open(entityId: string, data: PvLinkageData) {
    this.entityId = entityId;
    this.draft = initialPvDraft(data);
    this.step = 0;
    this.error = '';
    await this.updateComplete;
    this.renderRoot.querySelector('dialog')?.showModal();
  }
  close() {
    if (!this.busy) this.renderRoot.querySelector('dialog')?.close();
  }
  next() {
    if (this.step < 2 && (this.step !== 0 || !this.blockedReason)) this.step += 1;
  }
  back() {
    if (this.step > 0 && !this.busy) this.step -= 1;
  }
  setMode(value: PvMode) {
    this.draft = { ...this.draft, workingMode: value };
  }
  setBoost(value: PvBoost) {
    this.draft = { ...this.draft, boostMode: value };
  }
  setField(field: keyof PvLinkageDraft, value: string) {
    this.draft = { ...this.draft, [field]: value };
  }
  async apply() {
    const data = this.cardData;
    if (!this.hass || !data || this.blockedReason || this.errors.length || this.busy) return;
    this.busy = true;
    this.error = '';
    try {
      await this.hass.callService(
        'growatt_thor',
        'apply_pv_linkage_profile',
        pvServicePayload(data.entry_id, this.draft),
      );
      this.busy = false;
      this.close();
    } catch {
      this.error = 'pvCallError';
    } finally {
      this.busy = false;
    }
  }
  render() {
    return renderPvLinkageDialog(
      this,
      pvTranslate(this.hass?.language || this.hass?.locale?.language),
    );
  }
}

if (!customElements.get('growatt-thor-pv-linkage-dialog'))
  customElements.define('growatt-thor-pv-linkage-dialog', ThorPvLinkageDialog);

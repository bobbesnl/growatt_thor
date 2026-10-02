import { LitElement } from 'lit';
import { renderGoalDialog, type GoalDialogActions } from './dialog.template';
import { styles } from '../charger/styles';
import { goalDialogStyles } from './dialog-styles';
import { translate } from '../shared/strings';
import { canReplace, validLiveTarget, type LiveGoal } from './live';
import {
  futureStart,
  nextMinuteDateTime,
  goalValue,
  createGoalExampleValues,
  type GoalKind,
  type GoalRecurrence,
  type GoalStart,
  type GoalSimulation,
} from './model';

// Live and simulated submissions are separate injected callbacks. The backend
// owns persisted one-shot schedules; the dialog only collects their start time.
export class ThorGoalDialog extends LitElement {
  static properties = {
    language: {},
    dark: { type: Boolean },
    currency: {},
    simulation: { attribute: false },
    live: { attribute: false },
    _busy: { state: true },
    _confirmed: { state: true },
    _feedback: { state: true },
    _kind: { state: true },
    _values: { state: true },
    _start: { state: true },
    _at: { state: true },
    _recurrence: { state: true },
    _now: { state: true },
  };
  static styles = [styles, goalDialogStyles];
  language = 'en';
  dark = false;
  currency = '';
  simulation?: GoalSimulation;
  live?: LiveGoal;
  private _busy = false;
  private _confirmed = false;
  private _feedback = '';
  private _kind: GoalKind = 'energy';
  private _values = createGoalExampleValues();
  private _start: GoalStart = 'now';
  private _at = '';
  private _recurrence: GoalRecurrence = 'once';
  private _now = Date.now();
  private _clock?: ReturnType<typeof setInterval>;
  private readonly viewActions: GoalDialogActions = {
    setKind: (kind) => {
      this._kind = kind;
    },
    setStart: (start) => {
      this._start = start;
      if (start === 'later' && !this._at) this._at = nextMinuteDateTime(new Date(this._now));
    },
    setAt: (value) => {
      this._at = value;
    },
    setRecurrence: (value) => {
      this._recurrence = value;
    },
    setValue: (value) => {
      this._values = { ...this._values, [this._kind]: value };
    },
    close: () => this.close(),
    closed: () => this.closed(),
    save: () => {
      if (this.live && !this.simulation) void this.saveLive();
      else this.saveSimulation();
    },
    confirm: (confirmed) => {
      this._confirmed = confirmed;
    },
    cancel: (requestId) => {
      void this.cancelSchedule(requestId);
    },
  };
  async open() {
    // Repeated open requests must not discard the draft of an already open dialog.
    if (this.renderRoot.querySelector('dialog')?.open) return;
    this._now = Date.now();
    this.reset();
    const initial = this.simulation?.initial;
    if (initial) {
      this._kind = initial.kind;
      this._values[initial.kind] = String(initial.value);
      this._start = initial.start;
      this._at = initial.at;
      this._recurrence = initial.recurrence;
    }
    await this.updateComplete;
    const dialog = this.renderRoot.querySelector('dialog');
    if (!this.isConnected || !dialog || dialog.open) return;
    dialog.showModal();
    this._clock = setInterval(() => {
      this._now = Date.now();
    }, 10000);
  }
  private reset() {
    this._kind = 'energy';
    this._values = createGoalExampleValues();
    this._start = 'now';
    this._at = nextMinuteDateTime(new Date(this._now));
    this._recurrence = 'once';
    this._confirmed = false;
    this._feedback = '';
    if (this.live && !this.simulation)
      this._values.energy = this.live.request?.kind === 'energy' ? this.live.request.value : '1';
  }
  private closed() {
    clearInterval(this._clock);
    this._clock = undefined;
    this.reset();
  }
  private close() {
    if (this._busy) return;
    this.renderRoot.querySelector('dialog')?.close();
  }
  private async saveLive() {
    const value = goalValue(this._values[this._kind], this._kind);
    const live = this.live;
    if (!live || this._busy || !this._confirmed || !validLiveTarget(this._kind, value)) return;
    const later = this._start === 'later';
    if (later && !futureStart(this._at, this._now)) return;
    if (
      later
        ? this._recurrence === 'daily'
          ? !live.scheduleDailyAvailable
          : !live.scheduleOnceAvailable
        : !live.available
    )
      return;
    if (live.request && !canReplace(live.request, this._kind, value!)) return;
    this._busy = true;
    this._feedback = '';
    try {
      await live.save(
        this._kind,
        value!,
        later ? new Date(this._at).toISOString() : undefined,
        this._recurrence,
        live.request?.request_id,
      );
      this._feedback = later
        ? this._recurrence === 'daily'
          ? 'goalScheduleDailySubmitted'
          : 'goalScheduleSubmitted'
        : 'goalLiveSubmitted';
      this._confirmed = false;
    } catch {
      this._feedback = 'goalLiveError';
    } finally {
      this._busy = false;
    }
  }
  private async cancelSchedule(requestId: string) {
    if (!this.live?.cancel || this._busy) return;
    this._busy = true;
    this._feedback = '';
    try {
      await this.live.cancel(requestId);
      this._feedback = 'goalScheduleCancelled';
    } catch {
      this._feedback = 'goalLiveError';
    } finally {
      this._busy = false;
    }
  }
  private saveSimulation() {
    const value = goalValue(this._values[this._kind], this._kind);
    if (!this.simulation || value === null) return;
    if (this._start === 'later' && !futureStart(this._at)) return;
    if (this._kind === 'budget' && !/^[A-Z]{3}$/.test(this.currency)) return;
    this.simulation.save({
      kind: this._kind,
      value,
      start: this._start,
      at: this._start === 'later' ? this._at : '',
      recurrence: this._recurrence,
      currency: this.currency,
    });
    this.close();
  }
  disconnectedCallback() {
    this.close();
    this.closed();
    super.disconnectedCallback();
  }

  render() {
    const t = translate(this.language);
    const value = goalValue(this._values[this._kind], this._kind);
    const validTime = this._start === 'now' || futureStart(this._at, this._now);
    const validCurrency = this._kind !== 'budget' || /^[A-Z]{3}$/.test(this.currency);
    const unit =
      this._kind === 'energy' ? 'kWh' : this._kind === 'duration' ? 'min' : this.currency || '—';
    const amount =
      value === null ? '—' : value.toLocaleString(this.language, { maximumFractionDigits: 3 });
    const summary = t(`goalSummary_${this._kind}`)
      .replace('{value}', amount)
      .replace('{currency}', this.currency);
    return renderGoalDialog(
      {
        kind: this._kind,
        values: this._values,
        start: this._start,
        at: this._at,
        recurrence: this._recurrence,
        now: this._now,
        language: this.language,
        dark: this.dark,
        t,
        value,
        validTime,
        validCurrency,
        unit,
        summary,
        simulation: !!this.simulation,
        live: this.simulation ? undefined : this.live,
        busy: this._busy,
        confirmed: this._confirmed,
        feedback: this._feedback,
      },
      this.viewActions,
    );
  }
}
if (!customElements.get('growatt-thor-goal-dialog'))
  customElements.define('growatt-thor-goal-dialog', ThorGoalDialog);

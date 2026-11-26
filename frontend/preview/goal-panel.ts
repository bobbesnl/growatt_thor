import { LitElement, unsafeCSS } from 'lit';
import { renderGoalPanel } from './goal-panel.template';
import cssText from './goal-panel.css';
import { applyGoal, cancelGoal, type SimulatedGoal } from './goal-state';
import type { ThorGoalDialog } from '../src/targets/dialog';
import type { GoalDefinition, GoalSimulation } from '../src/targets/model';
export { exampleGoal } from './goal-state';

/** Simulator-only, slotted into the real card. No hass/service/storage access. */
class PreviewGoalPanel extends LitElement {
  static styles = unsafeCSS(cssText);
  static properties = { goal: { attribute: false }, language: {}, dark: { type: Boolean } };
  goal?: SimulatedGoal;
  language = 'de';
  dark = false;
  private readonly save = (definition: GoalDefinition) =>
    this.publish(applyGoal(definition, this.goal));
  private readonly actions = {
    edit: async () => {
      const dialog = this.renderRoot.querySelector<ThorGoalDialog>('growatt-thor-goal-dialog');
      if (!dialog) return;
      dialog.simulation = this.simulation();
      await dialog.open();
    },
    cancel: () => {
      if (this.goal) this.publish(cancelGoal(this.goal));
    },
  };
  private simulation(): GoalSimulation {
    return {
      initial: this.goal && ['planned', 'active'].includes(this.goal.state) ? this.goal : undefined,
      save: this.save,
    };
  }
  private publish(goal: SimulatedGoal) {
    this.dispatchEvent(
      new CustomEvent('preview-goal-changed', { detail: goal, bubbles: true, composed: true }),
    );
  }
  render() {
    return renderGoalPanel(this.goal, this.language, this.dark, this.actions);
  }
}
customElements.define('thor-preview-goal', PreviewGoalPanel);

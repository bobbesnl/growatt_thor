import { html } from 'lit';
import type { ThorAuthDialog } from './dialog';
import type { Translator } from '../shared/strings';

export const renderAuthDialog = (dialog: ThorAuthDialog, t: Translator) =>
  html` <dialog
    aria-labelledby="auth-title"
    @cancel=${(event: Event) => {
      if (dialog.busy) event.preventDefault();
    }}
  >
    <h2 id="auth-title">${t('authorization')}</h2>
    <p>${t('authChangeWarning')}</p>
    <label for="auth-option">${t('authorization')}</label>
    <select
      id="auth-option"
      .value=${dialog.option}
      ?disabled=${dialog.busy || !dialog.available}
      @change=${(event: Event) => {
        dialog.option = (event.target as HTMLSelectElement).value;
      }}
    >
      ${(dialog.hass?.states[dialog.entityId]?.attributes.options || []).map(
        (option: string) =>
          html`<option value=${option} .selected=${option === dialog.option}>${t(option)}</option>`,
      )}
    </select>
    ${!dialog.available ? html`<p role="status">${t('authControlUnavailable')}</p>` : ''}
    ${dialog.error ? html`<p role="alert">${t(dialog.error)}</p>` : ''}
    <footer>
      <button ?disabled=${dialog.busy} @click=${() => dialog.close()}>${t('authCancel')}</button>
      <button
        class="confirm"
        ?disabled=${dialog.busy || !dialog.available}
        @click=${() => dialog.apply()}
      >
        ${t('authConfirm')}
      </button>
    </footer>
  </dialog>`;

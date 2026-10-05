import { css, html, nothing } from 'lit';
import type { CardInitialization } from './card-initialization';
import { translate } from './strings';

const messages = {
  en: [
    'Connecting to Home Assistant…',
    'Waiting for the THOR integration…',
    'Loading charging history…',
    'This may take a moment during startup or reload.',
  ],
  de: [
    'Verbindung zu Home Assistant wird hergestellt…',
    'Warte auf die THOR-Integration…',
    'Ladehistorie wird geladen…',
    'Beim Start oder Neuladen kann das einen Moment dauern.',
  ],
  nl: [
    'Verbinden met Home Assistant…',
    'Wachten op de THOR-integratie…',
    'Laadgeschiedenis wordt geladen…',
    'Dit kan even duren tijdens het opstarten of herladen.',
  ],
  fr: [
    'Connexion à Home Assistant…',
    'En attente de l’intégration THOR…',
    'Chargement de l’historique de recharge…',
    'Cela peut prendre un instant au démarrage ou au rechargement.',
  ],
  es: [
    'Conectando con Home Assistant…',
    'Esperando la integración THOR…',
    'Cargando el historial de carga…',
    'Esto puede tardar un momento al iniciar o recargar.',
  ],
  it: [
    'Connessione a Home Assistant…',
    'In attesa dell’integrazione THOR…',
    'Caricamento della cronologia di ricarica…',
    'Potrebbe richiedere un momento durante l’avvio o il ricaricamento.',
  ],
  hu: [
    'Csatlakozás a Home Assistanthoz…',
    'Várakozás a THOR-integrációra…',
    'Töltési előzmények betöltése…',
    'Indításkor vagy újratöltéskor ez eltarthat egy ideig.',
  ],
  sl: [
    'Povezovanje s Home Assistant…',
    'Čakanje na integracijo THOR…',
    'Nalaganje zgodovine polnjenja…',
    'Ob zagonu ali ponovnem nalaganju lahko to traja nekaj trenutkov.',
  ],
};

export function renderCardNotice(
  state: CardInitialization,
  language: string,
  dark: boolean,
  title: string,
  sessions = false,
) {
  const t = translate(language);
  const locale = language.toLowerCase().replaceAll('_', '-').split('-')[0];
  const text = messages[locale as keyof typeof messages] ?? messages.en;
  const pending = state === 'connecting' || state === 'waiting';
  const message =
    state === 'connecting'
      ? text[0]
      : state === 'waiting'
        ? text[sessions ? 2 : 1]
        : t(state === 'select' ? 'selectCharger' : 'oldIntegration');
  return html`<ha-card class="card ${dark ? 'dark' : ''}">
    <div class="card-notice" role="status" aria-live="polite" aria-atomic="true">
      <strong>${title}</strong>
      <p>
        ${pending ? html`<span class="loading-dot" aria-hidden="true"></span>` : nothing}${message}
      </p>
      ${pending ? html`<small>${text[3]}</small>` : nothing}
    </div>
  </ha-card>`;
}

export const cardNoticeStyles = css`
  .card-notice {
    min-height: 90px;
    padding: 4px 0;
  }
  .card-notice strong {
    color: var(--ink);
    font-size: 14px;
  }
  .card-notice p {
    display: flex;
    align-items: center;
    gap: 9px;
    margin: 16px 0 8px;
    color: var(--ink);
    font-size: 13px;
  }
  .card-notice small {
    color: var(--muted);
    font-size: 12px;
    line-height: 1.5;
  }
  .loading-dot {
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--lime);
    animation: notice-pulse 1.8s ease-in-out infinite;
  }
  @keyframes notice-pulse {
    50% {
      opacity: 0.3;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .loading-dot {
      animation: none;
    }
  }
`;

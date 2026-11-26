import { html, nothing } from 'lit';
import type { SessionItem } from '../shared/types';
import { sessionIdentifierView } from './model';

/** The desktop table and mobile tiles use the same compact card identity. */
export function renderSessionIdentifier(row: SessionItem) {
  const view = sessionIdentifierView(row);
  return html`<span class="session-card-identity">
    <span class="session-card-name" title=${view.primary}>${view.primary}</span>
    ${view.secondary ? html`<small class="session-card-id">${view.secondary}</small>` : nothing}
  </span>`;
}

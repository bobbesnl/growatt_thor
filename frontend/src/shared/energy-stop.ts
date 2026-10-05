import { html, nothing } from 'lit';
import type { CardData } from './types';

const messages = {
  en: [
    'Last protection stop',
    'Battery discharge',
    'Grid import',
    '{watts} W or more for {minutes} min. No automatic restart.',
  ],
  de: [
    'Letzter Schutzstopp',
    'Batterieentladung',
    'Netzbezug',
    'Mindestens {watts} W für {minutes} Min. Kein automatischer Neustart.',
  ],
  nl: [
    'Laatste beveiligingsstop',
    'Batterijontlading',
    'Netafname',
    'Minstens {watts} W gedurende {minutes} min. Geen automatische herstart.',
  ],
  fr: [
    'Dernier arrêt de protection',
    'Décharge de la batterie',
    'Prélèvement réseau',
    'Au moins {watts} W pendant {minutes} min. Pas de redémarrage automatique.',
  ],
  es: [
    'Última parada de protección',
    'Descarga de batería',
    'Consumo de red',
    'Al menos {watts} W durante {minutes} min. Sin reinicio automático.',
  ],
  it: [
    'Ultimo arresto di protezione',
    'Scarica della batteria',
    'Prelievo dalla rete',
    'Almeno {watts} W per {minutes} min. Nessun riavvio automatico.',
  ],
  hu: [
    'Utolsó védelmi leállítás',
    'Akkumulátor kisütése',
    'Hálózati vételezés',
    'Legalább {watts} W {minutes} percig. Nincs automatikus újraindítás.',
  ],
  sl: [
    'Zadnja zaščitna ustavitev',
    'Praznjenje baterije',
    'Odjem iz omrežja',
    'Vsaj {watts} W za {minutes} min. Brez samodejnega ponovnega zagona.',
  ],
};

function dictionary(language: string) {
  return messages[language.toLowerCase().split(/[-_]/)[0] as keyof typeof messages] ?? messages.en;
}

export function energyStopReason(reason: string, language: string): string {
  return dictionary(language)[reason === 'battery' ? 1 : 2];
}

export function renderEnergyStop(report: CardData['energy_stop'], language: string) {
  if (
    !report ||
    !['battery', 'grid'].includes(report.reason) ||
    !Number.isFinite(Date.parse(report.at))
  )
    return nothing;
  const text = dictionary(language);
  const hint = text[3]
    .replace('{watts}', report.threshold_w.toLocaleString(language))
    .replace(
      '{minutes}',
      (report.hold_seconds / 60).toLocaleString(language, { maximumFractionDigits: 1 }),
    );
  return html`<div class="notice energy-stop-notice" role="status">
    <ha-icon icon="mdi:shield-outline"></ha-icon>
    <div>
      <strong>${text[0]}: ${energyStopReason(report.reason, language)}</strong>
      <div>
        ${new Date(report.at).toLocaleString(language, { dateStyle: 'short', timeStyle: 'short' })}
      </div>
      <small>${hint}</small>
    </div>
  </div>`;
}

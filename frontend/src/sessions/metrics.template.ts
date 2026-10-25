import { html, nothing } from 'lit';
import type { SessionItem, SessionHistoryData } from '../shared/types';
import { accountingTranslate } from './accounting.locales';
import { sessionTranslate } from './locales';
import { formatSessionNumber, sessionRowMetrics } from './model';

/** Shared values and explanations keep the table and mobile tiles in sync. */
export function sessionMetricViews(row: SessionItem, language: string, currency: string) {
  const metrics = sessionRowMetrics(row);
  const t = accountingTranslate(language);
  const fmt = (value: number | null) => formatSessionNumber(value, language);
  const costLabel = metrics.costIsGrid
    ? t(metrics.costPartial ? 'knownGridCost' : 'gridCost')
    : sessionTranslate(language)('chargerCost');
  return {
    costLabel,
    green: html`<span
      title=${metrics.greenPartial ? t('partial').replace('{energy}', fmt(metrics.unknown)) : ''}
      >${metrics.greenPartial ? '≥ ' : ''}${fmt(metrics.green)} kWh</span
    >`,
    cost: html`<span
      title=${metrics.costIsGrid
        ? t(
            metrics.cost === null
              ? 'costUnknown'
              : metrics.costPartial
                ? 'partialCostHint'
                : 'costHint',
          )
        : ''}
      >${fmt(metrics.cost)} ${currency}</span
    >`,
    costBasis: costLabel ? html`<small class="metric-basis">${costLabel}</small>` : nothing,
  };
}

/** The summary uses the backend's all-history total, never just visible rows. */
export function sessionGreenTotalView(data: SessionHistoryData, language: string) {
  const value = data.total_green_energy_kwh;
  const known = value !== null && Number.isFinite(value) && value >= 0;
  const partial = known && data.total_green_partial === true;
  return {
    text: `${partial ? '≥ ' : ''}${formatSessionNumber(known ? value : null, language)} kWh`,
    title: partial ? sessionTranslate(language)('greenPartialHint') : '',
  };
}

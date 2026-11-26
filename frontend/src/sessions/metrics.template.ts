import { html, nothing } from 'lit';
import type { SessionItem, SessionHistoryData } from '../shared/types';
import { numeric } from '../shared/model';
import { translate } from '../shared/strings';
import { goalUnit } from '../targets/model';
import { formatNumber } from '../shared/format';
import { accountingTranslate } from './accounting.locales';
import { sessionTranslate } from './locales';
import { sessionRowMetrics } from './model';

export function sessionGoalView(row: SessionItem, language: string, currency: string) {
  const goal = row.charging_goal;
  if (!goal) return null;
  const target = numeric(goal.value);
  if (!target) return null;
  const actual = numeric(goal.actual);
  const t = translate(language);
  const amount = `${formatNumber(target, language)} ${goalUnit(goal.kind, currency)}`.trimEnd();
  const fraction = actual === null ? null : actual / target;
  const percent =
    fraction !== null && Number.isFinite(fraction)
      ? new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 }).format(
          fraction,
        )
      : null;
  return {
    label: t('goalTitle'),
    summary: percent === null ? amount : `${amount} · ${percent}`,
    title: actual === null ? '' : `${formatNumber(actual, language)} ${t('goalOf')} ${amount}`,
  };
}

/** Shared values and explanations keep the table and mobile tiles in sync. */
export function sessionMetricViews(row: SessionItem, language: string, currency: string) {
  const metrics = sessionRowMetrics(row);
  const t = accountingTranslate(language);
  const fmt = (value: number | null) => formatNumber(value, language);
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
    text: `${partial ? '≥ ' : ''}${formatNumber(known ? value : null, language)} kWh`,
    title: partial ? sessionTranslate(language)('greenPartialHint') : '',
  };
}

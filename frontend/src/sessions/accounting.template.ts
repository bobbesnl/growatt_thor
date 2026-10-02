import { html, nothing } from 'lit';
import type { SessionItem } from '../shared/types';
import { sessionEnergyBreakdown, formatSessionNumber } from './model';
import { accountingTranslate } from './accounting.locales';

/** Compact source strip. Measurements remain separate from inferred source shares. */
export function renderSessionAccounting(row: SessionItem, language: string, currency: string) {
  const t = accountingTranslate(language);
  const view = sessionEnergyBreakdown(row);
  const fmt = (value: number | null) => formatSessionNumber(value, language);
  const energy = (value: number) => (value > 0 && value < 0.005 ? `<${fmt(0.01)}` : fmt(value));
  const percent = (value: number) =>
    value > 0 && value < 1 ? '<1 %' : `${Math.round(value).toLocaleString(language)} %`;
  const explanation =
    row.energy_kwh === 0
      ? t('empty')
      : !view || view.fullyUnknown
        ? t('unavailable')
        : view.unknown > 0
          ? t('partial').replace('{energy}', energy(view.unknown))
          : null;
  return html`<section class="accounting" aria-label=${t('title')}>
    <div class="accounting-heading">
      <h3>${t('title')}</h3>
      ${row.energy_kwh !== null
        ? html`<span class="accounting-total"><strong>${fmt(row.energy_kwh)}</strong> kWh</span>`
        : nothing}
    </div>
    ${view?.parts.length
      ? html`<div
            class="accounting-strip"
            role="img"
            aria-label=${view.parts
              .map((p) => `${t(p.label)}: ${energy(p.kwh)} kWh (${percent(p.share)})`)
              .join('; ')}
          >
            ${view.parts.map(
              (p) =>
                html`<span
                  class="accounting-segment ${p.label}"
                  style=${`width:${p.share}%`}
                  title=${`${t(p.label)}: ${energy(p.kwh)} kWh (${percent(p.share)})`}
                ></span>`,
            )}
          </div>
          <ul class="accounting-values">
            ${view.parts.map(
              (p) =>
                html`<li>
                  <i class=${p.label} aria-hidden="true"></i
                  ><span class="accounting-source">${t(p.label)}</span>
                  <strong>${energy(p.kwh)} <small>kWh</small></strong
                  ><span class="accounting-share">${percent(p.share)}</span>
                </li>`,
            )}
          </ul>`
      : nothing}
    ${explanation ? html`<p class="accounting-explanation">${explanation}</p>` : nothing}
    <div class="accounting-footer">
      ${view?.cost !== null && view?.cost !== undefined
        ? html`<span class="accounting-cost"
            >${t(view.unknown > 0 ? 'knownGridCost' : 'gridCost')}: ${fmt(view.cost)}
            ${currency}</span
          >`
        : nothing}
      ${row.energy_kwh !== 0
        ? html`<details>
            <summary>${t('about')}</summary>
            <div class="accounting-details">
              <p>
                ${view && !view.fullyUnknown
                  ? t('coverage').replace('{percent}', percent(view.coverage))
                  : t('unavailable')}
              </p>
              ${view?.hasBattery ? html`<p>${t('batteryHint')}</p>` : nothing}
              <p>
                ${t(
                  view?.cost == null
                    ? 'costUnknown'
                    : view.unknown > 0
                      ? 'partialCostHint'
                      : 'costHint',
                )}
              </p>
              ${view?.policy === 'grid_first' || view?.policy === 'load_first'
                ? html`<p>${t(view.policy === 'grid_first' ? 'gridFirst' : 'loadFirst')}</p>`
                : nothing}
            </div>
          </details>`
        : nothing}
    </div>
  </section>`;
}

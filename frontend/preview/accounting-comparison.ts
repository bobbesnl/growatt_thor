/** Design comparison only. No Home Assistant connection or writes. */
import { html, render, nothing } from 'lit';

type Source = 'solar' | 'battery' | 'grid' | 'unknown';
interface Scenario {
  label: string;
  description: string;
  amounts: Record<Source, number>;
  gridCost: number | null;
}
const scenarios: Record<string, Scenario> = {
  mixed: {
    label: 'Solar + battery + grid',
    description: 'Example session · a complete source breakdown',
    amounts: { solar: 18.35, battery: 5.65, grid: 4.23, unknown: 0 },
    gridCost: 1.27,
  },
  actual: {
    label: 'Your last session · sources unavailable',
    description: 'Your last session · 28.233 kWh recorded, sources not identified',
    amounts: { solar: 0, battery: 0, grid: 0, unknown: 28.233 },
    gridCost: 0,
  },
  partial: {
    label: 'Partly identified',
    description: 'Example session · some intervals could not be assigned to a source',
    amounts: { solar: 16.2, battery: 3.1, grid: 2.73, unknown: 6.2 },
    gridCost: 0.82,
  },
  solar: {
    label: 'Solar only',
    description: 'Example session · all charging energy attributed to direct solar',
    amounts: { solar: 28.23, battery: 0, grid: 0, unknown: 0 },
    gridCost: 0,
  },
  small: {
    label: 'Small grid share',
    description: 'Example session · tiny shares keep their true proportions',
    amounts: { solar: 28.18, battery: 0, grid: 0.05, unknown: 0 },
    gridCost: 0.02,
  },
  empty: {
    label: 'Waiting for energy',
    description: 'Example session · no energy recorded yet',
    amounts: { solar: 0, battery: 0, grid: 0, unknown: 0 },
    gridCost: null,
  },
};
const names: Record<Source, string> = {
  solar: 'Solar',
  battery: 'Battery',
  grid: 'Grid',
  unknown: 'Not identified',
};
const order: Source[] = ['solar', 'battery', 'grid', 'unknown'];
let selected = 'mixed';
let theme = 'light';
let narrow = false;
const number = (value: number) => value.toLocaleString('en-GB', { maximumFractionDigits: 2 });
const money = (value: number) =>
  value.toLocaleString('en-GB', { style: 'currency', currency: 'EUR' });
const percent = (value: number) => (value > 0 && value < 1 ? '<1%' : `${Math.round(value)}%`);

function update() {
  const scenario = scenarios[selected];
  const total = order.reduce((sum, source) => sum + scenario.amounts[source], 0);
  // Zero categories are omitted; unassigned energy is still part of the total.
  const parts = order
    .filter((source) => scenario.amounts[source] > 0)
    .map((source) => ({
      source,
      label: names[source],
      kwh: scenario.amounts[source],
      share: (scenario.amounts[source] / total) * 100,
    }));
  const unknown = scenario.amounts.unknown;
  const fullyUnknown = total > 0 && unknown === total;
  const coverage = total ? ((total - unknown) / total) * 100 : 0;
  const explanation = !total
    ? 'No energy recorded yet.'
    : fullyUnknown
      ? 'Energy recorded. Its sources could not be identified.'
      : unknown > 0
        ? `${number(unknown)} kWh could not be assigned to a source.`
        : null;
  // A zero booked cost is not proof of free charging when sources are missing.
  const cost =
    !total || fullyUnknown || scenario.gridCost === null
      ? null
      : unknown > 0
        ? `${money(scenario.gridCost)} known grid cost`
        : `${money(scenario.gridCost)} grid cost`;
  const bar = (thin = false) =>
    parts.length
      ? html` <div
          class="split ${thin ? 'thin' : ''}"
          role="img"
          aria-label=${parts
            .map((p) => `${p.label}: ${number(p.kwh)} kWh, ${percent(p.share)}`)
            .join('; ')}
        >
          ${parts.map(
            (p) =>
              html`<span
                class="segment ${p.source}"
                style=${`flex-basis:${p.share}%`}
                title=${`${p.label} · ${number(p.kwh)} kWh · ${percent(p.share)}`}
              >
                ${!thin && p.share >= 12 ? html`<b>${percent(p.share)}</b>` : nothing}
              </span>`,
          )}
        </div>`
      : nothing;
  const details = () =>
    total
      ? html`<details>
          <summary>About this breakdown</summary>
          <div class="detail-copy">
            <p>
              ${fullyUnknown
                ? 'Source information is unavailable for this session.'
                : `Sources identified for ${percent(coverage)} of the recorded energy.`}
            </p>
            ${scenario.amounts.battery > 0
              ? html`<p>
                  Battery means energy from your home battery. Its earlier solar or grid origin is
                  not tracked.
                </p>`
              : nothing}
            ${fullyUnknown || scenario.gridCost === null
              ? html`<p>Grid cost is unavailable. This does not mean the session was free.</p>`
              : html`<p>
                  ${unknown > 0
                    ? 'The cost shown covers only the identified grid share.'
                    : 'The cost shown covers grid electricity only.'}
                  Battery storage costs are not included.
                </p>`}
            <p>
              The breakdown is estimated from site measurements. Grid draw is assigned to charging
              first; this rule does not control your charger.
            </p>
          </div>
        </details>`
      : nothing;
  const footer = () =>
    html`<div class="foot">
      ${explanation ? html`<p class="explanation">${explanation}</p>` : nothing}
      <div class="foot-row">
        ${cost ? html`<span class="cost">${cost}</span>` : nothing}${details()}
      </div>
    </div>`;
  const header = () =>
    html`<div class="energy-heading">
      <h2>Charging energy</h2>
      ${total ? html`<span class="total"><strong>${number(total)}</strong> kWh</span>` : nothing}
    </div>`;
  document.documentElement.dataset.theme = theme;
  render(
    html`
      <header class="page-heading">
        <a href="./">THOR / Design preview</a>
        <h1>Where did the energy come from?</h1>
        <p>Three compact alternatives for the session history.</p>
      </header>
      <section class="controls" aria-label="Preview controls">
        <label
          >Session<select
            aria-label="Session"
            .value=${selected}
            @change=${(e: Event) => {
              selected = (e.target as HTMLSelectElement).value;
              update();
            }}
          >
            ${Object.entries(scenarios).map(
              ([key, value]) => html`<option value=${key}>${value.label}</option>`,
            )}
          </select></label
        >
        <label
          >Theme<select
            aria-label="Theme"
            .value=${theme}
            @change=${(e: Event) => {
              theme = (e.target as HTMLSelectElement).value;
              update();
            }}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select></label
        >
        <label
          >Card width<select
            aria-label="Card width"
            .value=${narrow ? 'mobile' : 'wide'}
            @change=${(e: Event) => {
              narrow = (e.target as HTMLSelectElement).value === 'mobile';
              update();
            }}
          >
            <option value="wide">Responsive</option>
            <option value="mobile">Mobile · 360 px</option>
          </select></label
        >
      </section>
      <p class="scenario-description" aria-live="polite">${scenario.description}</p>
      <div class="variants ${narrow ? 'narrow' : ''}">
        <section class="variant">
          <div class="variant-heading">
            <span class="letter">A</span>
            <h3>Split bar + source values</h3>
            <span class="recommended">Recommended</span>
          </div>
          <article class="energy-card variant-a">
            ${header()}${bar()}
            ${parts.length
              ? html`<div class="source-values">
                  ${parts.map(
                    (p) =>
                      html`<div class="source-value">
                        <span class="source-label"><i class=${p.source}></i>${p.label}</span>
                        <strong>${number(p.kwh)} <small>kWh</small></strong>
                      </div>`,
                  )}
                </div>`
              : nothing}${footer()}
          </article>
          <p class="variant-note">The mix at a glance, with easy-to-read amounts below.</p>
        </section>
        <section class="variant">
          <div class="variant-heading">
            <span class="letter">B</span>
            <h3>Compact energy strip</h3>
          </div>
          <article class="energy-card variant-b">
            ${header()}${bar(true)}
            ${parts.length
              ? html`<div class="inline-values">
                  ${parts.map(
                    (p) =>
                      html`<div class="inline-value">
                        <i class=${p.source}></i><span>${p.label}</span
                        ><strong>${number(p.kwh)} <small>kWh</small></strong
                        ><span class="share">${percent(p.share)}</span>
                      </div>`,
                  )}
                </div>`
              : nothing}${footer()}
          </article>
          <p class="variant-note">The smallest footprint; the labels carry more of the detail.</p>
        </section>
        <section class="variant">
          <div class="variant-heading">
            <span class="letter">C</span>
            <h3>Source rows</h3>
          </div>
          <article class="energy-card variant-c">
            ${header()}
            <div class="source-rows">
              ${parts.map(
                (p) =>
                  html`<div class="source-row">
                    <div class="row-heading">
                      <span class="source-label"><i class=${p.source}></i>${p.label}</span
                      ><span
                        ><strong>${number(p.kwh)} <small>kWh</small></strong
                        ><span class="share">${percent(p.share)}</span></span
                      >
                    </div>
                    <div class="row-track">
                      <span class=${p.source} style=${`width:${p.share}%`}></span>
                    </div>
                  </div>`,
              )}
            </div>
            ${footer()}
          </article>
          <p class="variant-note">
            The clearest individual values, at the cost of a little more height.
          </p>
        </section>
      </div>
      <p class="preview-note">
        Comparison only · Example mixes are simulated · No changes to Home Assistant
      </p>
    `,
    document.querySelector<HTMLElement>('#comparison')!,
  );
}
update();

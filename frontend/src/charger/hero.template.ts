/** Hero section: power gauge with grid allowance, source mix, phase bars and device image. */
import { html, svg, nothing } from 'lit';
import { clamp } from '../shared/model';
import type { CardViewModel } from './card-view-model';

const VERSION = typeof __CARD_VERSION__ === 'undefined' ? 'dev' : __CARD_VERSION__;
const IMAGE = new URL(`thor-front.png?v=${VERSION}`, import.meta.url).href;

// Every gauge path has length 100. A longer gap prevents a repeated round cap
// at the far endpoint when a tiny dash is rounded to zero by the SVG renderer.
const GAUGE_DASH_GAP = 200;
const GAUGE_VIEW_BOX = '-12 -12 224 124';
const GAUGE_ARC_PATH = 'M 10 100 A 90 90 0 0 1 190 100';
const GAUGE_ALLOWANCE_PATH = 'M 0 100 A 100 100 0 0 1 200 100';
const GAUGE_OVERFLOW_PATH = 'M 4 100 A 96 96 0 0 1 196 100';
const GAUGE_PATH_LENGTH = 100;
const GAUGE_CENTER = 100;
const GAUGE_DEGREES_PER_PERCENT = 180 / GAUGE_PATH_LENGTH;
const TARGET_MARKER_POINTS = '-5,100 -11,95.5 -11,104.5';

const gaugePatternIds = new WeakMap<object, string>();
let gaugePatternSequence = 0;

function gaugePatternId(config: object): string {
  let id = gaugePatternIds.get(config);
  if (!id) {
    id = `thor-grid-allowance-${++gaugePatternSequence}`;
    gaugePatternIds.set(config, id);
  }
  return id;
}

function renderTargetMarker(powerFlow: CardViewModel['powerFlow']) {
  return powerFlow.target
    ? svg`<g
                  class="target-marker"
                  transform="rotate(${powerFlow.target.fraction * GAUGE_DEGREES_PER_PERCENT} ${GAUGE_CENTER} ${GAUGE_CENTER})"
                >
                  <polygon points=${TARGET_MARKER_POINTS} />
                </g>`
    : nothing;
}

function renderGaugeGraphic(view: CardViewModel) {
  const { config, powerFlow, fraction, animate, kw } = view;
  const hatchId = gaugePatternId(config);
  // Source segments cover the base arc. Paint the wave last, limited to the PV
  // share so battery/grid colours remain visible. Without a mix, animate all power.
  const animatedFraction = powerFlow.sources.length
    ? (powerFlow.sources.find((segment) => segment.source === 'solar')?.fraction ?? 0)
    : fraction;
  return html` <svg viewBox=${GAUGE_VIEW_BOX} aria-hidden="true">
    ${powerFlow.target && powerFlow.target.allowanceFraction > 0
      ? svg`<defs><pattern id=${hatchId} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <rect class="allowance-hatch-background" width="5" height="5" />
                  <path class="allowance-hatch-line" d="M 0 0 V 5" />
                </pattern></defs>`
      : nothing}
    ${animate
      ? svg`<defs><linearGradient class="charge-gradient" id="charge-gradient" gradientUnits="userSpaceOnUse" x1="10" y1="100" x2="190" y2="100">${[0, 20, 40, 60, 80, 100].map((offset) => svg`<stop offset="${offset}%" />`)}</linearGradient></defs>`
      : nothing}
    <path class="track" d=${GAUGE_ARC_PATH} pathLength=${GAUGE_PATH_LENGTH} />
    ${powerFlow.target && powerFlow.target.allowanceFraction > 0
      ? svg`<path class="target-allowance" d=${GAUGE_ALLOWANCE_PATH} pathLength=${GAUGE_PATH_LENGTH}
                  stroke="url(#${hatchId})"
                  stroke-dasharray="${powerFlow.target.allowanceFraction} ${GAUGE_DASH_GAP}"
                  stroke-dashoffset="${-powerFlow.target.zeroGridFraction}" />`
      : nothing}
    <path
      class="arc"
      d=${GAUGE_ARC_PATH}
      pathLength=${GAUGE_PATH_LENGTH}
      stroke-dasharray="${fraction} ${GAUGE_DASH_GAP}"
      opacity=${kw !== null && fraction > 0 ? 1 : 0}
    />
    ${[...powerFlow.sources].reverse().map(
      (segment) => svg`<path
                class="source-segment source-${segment.source}"
                d=${GAUGE_ARC_PATH}
                pathLength=${GAUGE_PATH_LENGTH}
                stroke-dasharray="${segment.startFraction + segment.fraction} ${GAUGE_DASH_GAP}"
              />`,
    )}
    ${animate && animatedFraction > 0
      ? svg`<path class="charge-wave" d=${GAUGE_ARC_PATH} pathLength=${GAUGE_PATH_LENGTH} stroke-dasharray="${animatedFraction} ${GAUGE_DASH_GAP}" />`
      : nothing}
    ${powerFlow.overflow
      ? svg`<path
                  class="over-target ${powerFlow.overflow.severity}"
                  d=${GAUGE_OVERFLOW_PATH}
                  pathLength=${GAUGE_PATH_LENGTH}
                  stroke-dasharray="${powerFlow.overflow.fraction} ${GAUGE_DASH_GAP}"
                  stroke-dashoffset="${-powerFlow.overflow.startFraction}"
                />`
      : nothing}
    ${renderTargetMarker(powerFlow)}
  </svg>`;
}

function renderPowerFlow({ powerFlow, t, format }: CardViewModel) {
  return html` ${powerFlow.target
    ? html`<div class="gauge-target" title=${t(powerFlow.target.hint)}>
        <span><span class="target-key"></span>${t(powerFlow.target.label)}</span
        ><strong>${format(powerFlow.target.kw)} kW</strong>
      </div>`
    : nothing}
  ${powerFlow.target && (powerFlow.gridImportLimitKw ?? 0) > 0
    ? html`<div class="target-breakdown">
        ${powerFlow.target.zeroGridKw > 0
          ? html`<span title=${t('zeroGridPointHint')}
              ><i class="target-key zero-grid"></i>${t('zeroGridPoint')}
              <strong>${format(powerFlow.target.zeroGridKw)} kW</strong></span
            >`
          : nothing}
        <span title=${t('gridImportAllowedHint')}
          ><i class="target-key grid-allowance"></i>${t('gridImportAllowed')}
          <strong>${format(powerFlow.gridImportLimitKw)} kW</strong></span
        >
      </div>`
    : nothing}
  ${powerFlow.sourcesUnassigned
    ? html`<div class="source-note">${t('sourcesUnassigned')}</div>`
    : nothing}
  ${powerFlow.sources.length
    ? html`<div class="source-mix" aria-label=${t('sourceMix')}>
        ${powerFlow.sources.map(
          (segment) =>
            html`<span class="source-item" title="${t(segment.label)}: ${format(segment.kw)} kW"
              ><i class="source-key source-${segment.source}"></i><span>${t(segment.label)}</span
              ><strong>${format(segment.kw)}</strong></span
            >`,
        )}
      </div>`
    : nothing}`;
}

function renderGauge(view: CardViewModel) {
  const { config, kw, maxPower, expectedTelemetryPause, status, resting, format, t } = view;
  const suspended = ['suspended_ev', 'suspended_evse'].includes(status.key);
  const pauseLabel = suspended
    ? 'paused'
    : status.key === 'pv_wait'
      ? status.key
      : 'waitingToCharge';
  const pauseHint =
    status.key === 'suspended_ev'
      ? 'vehiclePauseMeterHint'
      : status.key === 'suspended_evse'
        ? 'stationPauseMeterHint'
        : status.key === 'pv_wait'
          ? 'pvPauseMeterHint'
          : 'preparingHint';
  return html` <div
    class="gauge ${kw === null ? 'empty-gauge' : ''}"
    role=${kw !== null && maxPower ? 'meter' : 'img'}
    aria-label=${kw === null
      ? t(expectedTelemetryPause ? status.key : resting ? 'standby' : 'missing')
      : t('power')}
    aria-valuemin=${kw === null ? nothing : 0}
    aria-valuemax=${kw === null ? nothing : (maxPower ?? nothing)}
    aria-valuenow=${kw === null ? nothing : kw}
    aria-valuetext=${kw === null
      ? t(expectedTelemetryPause ? pauseHint : 'missing')
      : `${format(kw)} kW`}
  >
    <div class="gauge-face">
      ${renderGaugeGraphic(view)}
      <div class="reading">
        ${kw === null
          ? html`<ha-icon
                class="rest-icon"
                .icon=${expectedTelemetryPause
                  ? status.icon
                  : resting
                    ? 'mdi:power-sleep'
                    : 'mdi:cloud-question-outline'}
              ></ha-icon
              ><strong class="rest-label"
                >${t(expectedTelemetryPause ? pauseLabel : resting ? 'standby' : 'noData')}</strong
              ><small
                >${t(
                  expectedTelemetryPause ? pauseHint : resting ? 'noCharging' : 'missing',
                )}</small
              >`
          : html`<strong>${format(kw)}</strong><span class="unit">kW</span
              ><small>${t('power')}</small>`}
      </div>
    </div>
    <div class="gauge-scale" title=${t(config.max_power ? 'manualScaleHint' : 'autoScaleHint')}>
      <span>0</span
      ><span>${maxPower ? `${format(maxPower, maxPower % 1 ? 1 : 0)} kW` : t('scaleUnknown')}</span>
    </div>
    ${renderPowerFlow(view)}
  </div>`;
}

function renderPhases({
  config,
  complete,
  active,
  t,
  resting,
  data,
  currents,
  format,
}: CardViewModel) {
  return html` ${config.show_phases === false
    ? nothing
    : html`<div class="phases">
        <div class="phase-heading">
          <span
            >${complete
              ? `${active}/3 ${t('phases')} ${t('active')}`
              : t(resting ? 'phasesAtStart' : 'phaseUnknown')}</span
          ><span>max. ${data.max_current_a} A</span>
        </div>
        <div class="phase-columns">
          ${currents.map(
            (current, index) =>
              html`<div
                class="phase-row ${current === null ? 'missing' : ''} ${current !== null &&
                current > data.max_current_a
                  ? 'over'
                  : ''}"
                title=${current === null
                  ? t('missing')
                  : current <= 0.3
                    ? t('inactive')
                    : t('phaseScale')}
              >
                <span class="phase-label">L${index + 1}</span>
                <div
                  class="phase-track"
                  role="meter"
                  aria-label=${`L${index + 1}`}
                  aria-valuemin="0"
                  aria-valuemax=${data.max_current_a}
                  aria-valuenow=${current ?? nothing}
                  aria-valuetext=${current === null ? t('missing') : `${format(current)} A`}
                >
                  <div
                    class="phase-fill"
                    style="width:${clamp(((current || 0) / data.max_current_a) * 100)}%"
                  ></div>
                </div>
                <span class="phase-value">${format(current)}${current === null ? '' : ' A'}</span>
              </div>`,
          )}
        </div>
      </div>`}`;
}

function renderDevice({ config, connected, t }: CardViewModel) {
  return html` ${config.show_image === false
    ? nothing
    : html`<div class="device ${!connected ? 'offline' : ''}" title=${t('deviceIllustration')}>
        <svg class="device-art" viewBox="135 98 755 1314" role="img" aria-label="Growatt THOR">
          <defs>
            <clipPath id="thor-outline">
              <path
                d="M 511 107 C 335 107 230 115 195 139 C 165 158 160 181 156 223 C 145 335 145 534 146 970 C 146 1205 151 1304 174 1353 C 192 1388 230 1393 305 1398 C 440 1406 647 1405 747 1397 C 814 1393 842 1380 855 1344 C 875 1286 878 1160 878 923 L 878 510 C 878 330 872 213 859 172 C 850 144 832 132 794 124 C 724 110 608 107 511 107 Z"
              />
            </clipPath>
          </defs>
          <image href=${IMAGE} width="1024" height="1536" clip-path="url(#thor-outline)" />
        </svg>
      </div>`}`;
}

export function renderHero(view: CardViewModel) {
  return html`<div class="hero ${view.config.show_image === false ? 'no-image' : ''}">
    ${renderDevice(view)}
    <div class="instrument">${renderGauge(view)} ${renderPhases(view)}</div>
  </div>`;
}

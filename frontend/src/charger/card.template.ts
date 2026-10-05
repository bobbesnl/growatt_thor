import { renderEnergyStop } from '../shared/energy-stop';
import { html, svg, nothing } from 'lit';
import { clamp } from '../shared/model';
import type { CardViewModel } from './card-view-model';
import {
  liveGoalAvailable,
  liveTargetStatus,
  oneTimeGoalAvailable,
  scheduledGoalAvailable,
  targetNoticeVisible,
} from '../targets/live';
import type { GoalKind, GoalRecurrence } from '../targets/model';
import type { PvLinkageData } from '../shared/types';

export interface CardActions {
  command(action: 'start' | 'stop'): Promise<void>;
  moreInfo(entity?: string): void;
  openGoalPreview(): void;
  setGoal(
    kind: GoalKind,
    value: number,
    startAt?: string,
    recurrence?: GoalRecurrence,
    replaceId?: string,
  ): Promise<void>;
  cancelGoal(requestId: string): Promise<void>;
  openAuth(entity?: string): void;
  openPv(entity: string, data?: PvLinkageData): void;
}
export interface CardFeedback {
  error: string;
  sending: boolean;
}
const VERSION = typeof __CARD_VERSION__ === 'undefined' ? 'dev' : __CARD_VERSION__;
const IMAGE = new URL(`thor-front.png?v=${VERSION}`, import.meta.url).href;
// Every gauge path has length 100. A longer gap prevents a repeated round cap
// at the far endpoint when a tiny dash is rounded to zero by the SVG renderer.
const GAUGE_DASH_GAP = 200;

function renderHeader({ config, t, data, auth, entity }: CardViewModel, actions: CardActions) {
  return html`
    <header>
      <div class="eyebrow">GROWATT · THOR</div>
      <h2>${config.name || t('statusEntity')}</h2>
      <div class="pills">
        ${data.pv_linkage
          ? html`<button
              class="mode strategy"
              title=${t('chargeMode')}
              aria-haspopup="dialog"
              @click=${() => actions.openPv(entity.entity_id, data.pv_linkage)}
            >
              <ha-icon
                .icon=${data.working_mode?.startsWith('pv_')
                  ? 'mdi:white-balance-sunny'
                  : data.working_mode === 'off_peak'
                    ? 'mdi:clock-outline'
                    : 'mdi:lightning-bolt'}
              ></ha-icon
              >${t(data.working_mode || 'modeUnknown')}
            </button>`
          : html`<div class="mode" title=${t('chargeMode')}>
              <ha-icon
                .icon=${data.working_mode?.startsWith('pv_')
                  ? 'mdi:white-balance-sunny'
                  : data.working_mode === 'off_peak'
                    ? 'mdi:clock-outline'
                    : 'mdi:lightning-bolt'}
              ></ha-icon
              >${t(data.working_mode || 'modeUnknown')}
            </div>`}
        <button
          class="mode auth"
          title=${t(`${auth}Hint`)}
          aria-label=${t('authorization')}
          ?disabled=${!data.entities.authorization_mode_control}
          @click=${() => actions.openAuth(data.entities.authorization_mode_control)}
        >
          <ha-icon
            .icon=${auth === 'plug_and_charge'
              ? 'mdi:power-plug-outline'
              : 'mdi:card-account-details-outline'}
          ></ha-icon
          >${t(auth)}
        </button>
      </div>
    </header>
  `;
}

function renderStatus({ status, t, powerFlow, format }: CardViewModel) {
  return html`<div class="status-strip">
    <div class="status" role="status">
      <span class="dot"></span><ha-icon .icon=${status.icon}></ha-icon>${t(status.key)}
    </div>
    ${powerFlow.visible
      ? html`<div
          class="grid-balance"
          data-flow=${powerFlow.tone}
          title=${t('gridPower')}
          aria-label=${`${t(powerFlow.label)}: ${
            powerFlow.valueKw === null ? t('missing') : `${format(powerFlow.valueKw)} kW`
          }`}
        >
          <ha-icon .icon=${powerFlow.icon}></ha-icon><span>${t(powerFlow.label)}</span
          ><strong>${powerFlow.valueKw === null ? '—' : `${format(powerFlow.valueKw)} kW`}</strong>
        </div>`
      : nothing}
  </div>`;
}

function renderHero({
  config,
  connected,
  t,
  kw,
  maxPower,
  fraction,
  animate,
  format,
  resting,
  expectedTelemetryPause,
  status,
  complete,
  active,
  data,
  currents,
  powerFlow,
}: CardViewModel) {
  const suspended = ['suspended_ev', 'suspended_evse'].includes(status.key);
  // Source segments cover the base arc. Paint the wave last, limited to the PV
  // share so battery/grid colours remain visible. Without a mix, animate all power.
  const animatedFraction = powerFlow.sources.length
    ? (powerFlow.sources.find((segment) => segment.source === 'solar')?.fraction ?? 0)
    : fraction;
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
  return html`
    <div class="hero ${config.show_image === false ? 'no-image' : ''}">
      ${config.show_image === false
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
          </div>`}
      <div class="instrument">
        <div
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
          <svg viewBox="0 0 200 112" aria-hidden="true">
            ${animate
              ? svg`<defs><linearGradient class="charge-gradient" id="charge-gradient" gradientUnits="userSpaceOnUse" x1="10" y1="100" x2="190" y2="100">${[0, 20, 40, 60, 80, 100].map((offset) => svg`<stop offset="${offset}%" />`)}</linearGradient></defs>`
              : nothing}
            <path class="track" d="M 10 100 A 90 90 0 0 1 190 100" pathLength="100" />
            ${powerFlow.target && powerFlow.target.fraction > 0
              ? svg`<path
                  class="target-range"
                  d="M 10 100 A 90 90 0 0 1 190 100"
                  pathLength="100"
                  stroke-dasharray="${powerFlow.target.fraction} ${GAUGE_DASH_GAP}"
                />`
              : nothing}
            <path
              class="arc"
              d="M 10 100 A 90 90 0 0 1 190 100"
              pathLength="100"
              stroke-dasharray="${fraction} ${GAUGE_DASH_GAP}"
              opacity=${kw !== null && fraction > 0 ? 1 : 0}
            />
            ${[...powerFlow.sources].reverse().map(
              (segment) => svg`<path
                class="source-segment source-${segment.source}"
                d="M 10 100 A 90 90 0 0 1 190 100"
                pathLength="100"
                stroke-dasharray="${segment.startFraction + segment.fraction} ${GAUGE_DASH_GAP}"
              />`,
            )}
            ${animate && animatedFraction > 0
              ? svg`<path class="charge-wave" d="M 10 100 A 90 90 0 0 1 190 100" pathLength="100" stroke-dasharray="${animatedFraction} ${GAUGE_DASH_GAP}" />`
              : nothing}
            ${powerFlow.overflow
              ? svg`<path
                  class="over-target ${powerFlow.overflow.severity}"
                  d="M 4 100 A 96 96 0 0 1 196 100"
                  pathLength="100"
                  stroke-dasharray="${powerFlow.overflow.fraction} ${GAUGE_DASH_GAP}"
                  stroke-dashoffset="${-powerFlow.overflow.startFraction}"
                />`
              : nothing}
            ${powerFlow.target
              ? svg`<g
                  class="target-marker"
                  style="transform:rotate(${powerFlow.target.fraction * 1.8}deg)"
                >
                  <line x1="18" y1="100" x2="2" y2="100" />
                  <circle cx="2" cy="100" r="3" />
                </g>`
              : nothing}
          </svg>
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
                    >${t(
                      expectedTelemetryPause ? pauseLabel : resting ? 'standby' : 'noData',
                    )}</strong
                  ><small
                    >${t(
                      expectedTelemetryPause ? pauseHint : resting ? 'noCharging' : 'missing',
                    )}</small
                  >`
              : html`<strong>${format(kw)}</strong><span class="unit">kW</span
                  ><small>${t('power')}</small>`}
          </div>
          <div
            class="gauge-scale"
            title=${t(config.max_power ? 'manualScaleHint' : 'autoScaleHint')}
          >
            <span>0</span
            ><span
              >${maxPower
                ? `${format(maxPower, maxPower % 1 ? 1 : 0)} kW`
                : t('scaleUnknown')}</span
            >
          </div>
          ${powerFlow.target
            ? html`<div class="gauge-target" title=${t(powerFlow.target.hint)}>
                <span><span class="target-key"></span>${t(powerFlow.target.label)}</span
                ><strong>${format(powerFlow.target.kw)} kW</strong>
              </div>`
            : nothing}
          ${powerFlow.sourcesUnassigned
            ? html`<div class="source-note">${t('sourcesUnassigned')}</div>`
            : nothing}
          ${powerFlow.sources.length
            ? html`<div class="source-mix" aria-label=${t('sourceMix')}>
                ${powerFlow.sources.map(
                  (segment) =>
                    html`<span
                      class="source-item"
                      title="${t(segment.label)}: ${format(segment.kw)} kW"
                      ><i class="source-key source-${segment.source}"></i
                      ><span>${t(segment.label)}</span><strong>${format(segment.kw)}</strong></span
                    >`,
                )}
              </div>`
            : nothing}
        </div>
        ${config.show_phases === false
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
                      <span class="phase-value"
                        >${format(current)}${current === null ? '' : ' A'}</span
                      >
                    </div>`,
                )}
              </div>
            </div>`}
      </div>
    </div>
  `;
}

function renderSession({
  config,
  t,
  sessionActive,
  energy,
  duration,
  format,
  cost,
  currency,
}: CardViewModel) {
  return html`
    ${config.show_session === false
      ? nothing
      : html`<div class="session">
          <div class="session-title">
            <ha-icon icon="mdi:history"></ha-icon>${t(
              sessionActive ? 'currentSession' : 'lastSession',
            )}
          </div>
          <div class="metrics ${sessionActive ? '' : 'with-cost'}">
            <div class="metric">
              <strong>${format(energy)}</strong
              ><span class="metric-meta"
                ><span class="unit">kWh</span><small>${t('energy')}</small></span
              >
            </div>
            <div class="metric">
              <strong>${duration}</strong
              ><span class="metric-meta"
                ><span class="unit">h</span><small>${t('durationShort')}</small></span
              >
            </div>
            ${sessionActive
              ? nothing
              : html`<div class="metric cost">
                  <strong>${format(cost, 2)}</strong
                  ><span class="metric-meta"
                    ><span class="unit">${currency}</span><small>${t('cost')}</small></span
                  >
                </div>`}
          </div>
        </div>`}
  `;
}

function renderActions(
  { inactive, status, t, auth, caps, vehicle }: CardViewModel,
  actions: CardActions,
) {
  return html`
    <div class="actions">
      ${inactive
        ? html`<div class="activation">
            <ha-icon .icon=${status.icon}></ha-icon><span>${t(status.key)}</span>
          </div>`
        : auth === 'home_assistant_rfid' ||
            (auth === 'plug_and_charge' && vehicle === 'vehicleConnected')
          ? html`<button
              class="action start"
              ?disabled=${!caps.start}
              @click=${() => actions.command('start')}
            >
              <ha-icon icon="mdi:play"></ha-icon>${t('start')}
            </button>`
          : html`<div class="activation" title=${t(`${auth}Hint`)}>
              <ha-icon
                .icon=${auth === 'rfid_only'
                  ? 'mdi:contactless-payment-circle-outline'
                  : auth === 'plug_and_charge'
                    ? 'mdi:power-plug-outline'
                    : 'mdi:help-circle-outline'}
              ></ha-icon
              ><span
                >${t(
                  auth === 'rfid_only'
                    ? 'presentCard'
                    : auth === 'plug_and_charge'
                      ? 'automaticStart'
                      : 'authUnknown',
                )}</span
              >
            </div>`}<button
        class="action stop"
        ?disabled=${!caps.stop}
        @click=${() => actions.command('stop')}
      >
        <ha-icon icon="mdi:stop"></ha-icon>${t('stop')}
      </button>
    </div>
    ${!inactive && (auth === 'rfid_only' || auth === 'plug_and_charge')
      ? html`<p class="activation-hint">${t(`${auth}Hint`)}</p>`
      : nothing}
  `;
}

function renderWarnings({
  status,
  faultMessage,
  data,
  t,
  meterWarning,
  connected,
  inactive,
  idle,
  fresh,
  resting,
  kw,
  maxPower,
  format,
}: CardViewModel) {
  return html`
    ${status.key === 'faulted' && faultMessage
      ? html`<div class="notice error" role="alert">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <p>
            <strong>${t('faultDetails')}</strong>${String(faultMessage).slice(0, 500)}<br />${data.error_code &&
            data.error_code !== 'NoError'
              ? data.error_code
              : nothing}
          </p>
        </div>`
      : nothing}
    ${meterWarning
      ? html`<div class="notice warning">
          <ha-icon icon="mdi:meter-electric-outline"></ha-icon>${t('externalMeter')}
        </div>`
      : nothing}
    ${connected && !inactive && !idle && !fresh && !resting
      ? html`<div class="notice warning">
          <ha-icon icon="mdi:clock-alert-outline"></ha-icon>${t('stale')}
        </div>`
      : nothing}
    ${kw !== null && maxPower !== null && kw > maxPower
      ? html`<div class="notice warning">${t('over')}: ${format(kw)} kW</div>`
      : nothing}
  `;
}

function renderCommandFeedback({ info, t }: CardViewModel, feedback: CardFeedback) {
  // HA also rejects the service promise for a local policy denial. Keep the
  // specific explanation instead of masking it with the generic call error.
  const localDenial = info.key === 'localStartDenied';
  const messageKey = localDenial
    ? info.key
    : feedback.error || (feedback.sending ? 'localPending' : info.key);
  return html`
    ${feedback.error || feedback.sending || info.key
      ? html`<div
          class="notice ${feedback.error || localDenial || info.key === 'commandRejected'
            ? 'error'
            : 'warning'}"
          role="status"
        >
          <ha-icon
            class=${info.pending || feedback.sending ? 'spinner' : ''}
            icon="mdi:information-outline"
          ></ha-icon
          >${t(messageKey)}
        </div>`
      : nothing}
  `;
}

function renderFooter(
  { t, caps, data, format, currentLimit, entity, fault, status }: CardViewModel,
  actions: CardActions,
) {
  return html`
    <slot name="goal-preview"
      ><button class="goal-entry" aria-haspopup="dialog" @click=${() => actions.openGoalPreview()}>
        <ha-icon icon="mdi:target"></ha-icon
        ><span><strong>${t('goalTitle')}</strong><small>${t('goalEntry')}</small></span
        ><span class="preview-badge"
          >${t(data.charging_target_pilot ? 'goalLivePilot' : 'goalPreview')}</span
        ><ha-icon icon="mdi:chevron-right"></ha-icon></button
    ></slot>
    <footer>
      <button
        class="text-button"
        ?disabled=${!caps.limit}
        title=${t('settingHint')}
        @click=${() => actions.moreInfo(data.entities.max_current)}
      >
        ${t('limit')} <strong>${format(currentLimit, 0)} A</strong
        ><ha-icon icon="mdi:chevron-right"></ha-icon></button
      ><button class="text-button" @click=${() => actions.moreInfo(entity.entity_id)}>
        ${t('details')}<ha-icon icon="mdi:arrow-top-right"></ha-icon>
      </button>
    </footer>
    ${fault && !['unknown', 'unavailable'].includes(fault.state) && status.key !== 'faulted'
      ? html`<details>
          <summary>${t('pastFault')}</summary>
          <p>${fault.attributes.message || fault.state}</p>
          <button class="text-button" @click=${() => actions.moreInfo(fault.entity_id)}>
            ${t('viewEntity')}
          </button>
        </details>`
      : nothing}
  `;
}

function renderTargetNotice(view: CardViewModel) {
  const { charging_target: request } = view.data;
  if (!request || !targetNoticeVisible(request, view.now)) return nothing;

  const unit =
    request.kind === 'energy' ? 'kWh' : request.kind === 'duration' ? 'min' : view.currency;
  const scheduledAt = Date.parse(request.scheduled_for || '');
  const scheduledLabel = Number.isFinite(scheduledAt)
    ? new Date(scheduledAt).toLocaleString(
        view.hass.language || view.hass.locale?.language || 'en',
        { dateStyle: 'medium', timeStyle: 'short' },
      )
    : null;

  return html`<div class="notice target-notice" role="status">
    <div class="target-notice-heading">
      <ha-icon icon="mdi:target"></ha-icon>
      <strong>${view.t('goalTitle')}</strong>
      <span class="target-notice-value">${request.value} ${unit}</span>
    </div>
    <p>${view.t(liveTargetStatus(view.data))}</p>
    ${request.recurrence === 'daily' || scheduledLabel
      ? html`<div class="target-notice-meta">
          ${request.recurrence === 'daily'
            ? html`<span
                ><ha-icon icon="mdi:calendar-sync"></ha-icon>${view.t('goalEveryday')}</span
              >`
            : nothing}
          ${scheduledLabel
            ? html`<time datetime=${request.scheduled_for || ''}
                ><ha-icon icon="mdi:clock-outline"></ha-icon>${scheduledLabel}</time
              >`
            : nothing}
        </div>`
      : nothing}
  </div>`;
}

export function renderCard(view: CardViewModel, actions: CardActions, feedback: CardFeedback) {
  const { inactive, status, vehicle, currency, t, dark, hass } = view;
  return html` <ha-card
      class="card ${inactive ? 'is-inactive' : ''} ${dark ? 'dark' : ''}"
      data-tone=${status.tone}
    >
      ${renderHeader(view, actions)} ${renderStatus(view)} ${renderHero(view)}
      <div class="vehicle">
        <ha-icon
          .icon=${vehicle === 'vehicleConnected'
            ? 'mdi:ev-plug-type2'
            : vehicle === 'vehicleDisconnected'
              ? 'mdi:power-plug-off-outline'
              : 'mdi:help-circle-outline'}
        ></ha-icon
        >${t(vehicle)}
      </div>
      <p class="hint">${t(status.hint)}</p>
      ${renderEnergyStop(view.data.energy_stop, hass.language || hass.locale?.language || 'en')}
      ${renderWarnings(view)} ${renderSession(view)} ${renderActions(view, actions)}
      ${renderTargetNotice(view)} ${renderCommandFeedback(view, feedback)}
      ${renderFooter(view, actions)} </ha-card
    ><growatt-thor-goal-dialog
      .live=${view.data.charging_target_pilot
        ? {
            available: liveGoalAvailable(hass, view.entity, view.data),
            scheduleOnceAvailable: oneTimeGoalAvailable(hass, view.entity, view.data),
            scheduleDailyAvailable: scheduledGoalAvailable(hass, view.entity, view.data),
            request: view.data.charging_target,
            status: liveTargetStatus(view.data),
            save: actions.setGoal,
            cancel: actions.cancelGoal,
          }
        : undefined}
      .language=${hass.language || hass.locale?.language || 'en'}
      .dark=${dark}
      .currency=${currency}
    ></growatt-thor-goal-dialog
    ><growatt-thor-auth-dialog .hass=${hass}></growatt-thor-auth-dialog
    ><growatt-thor-pv-linkage-dialog .hass=${hass}></growatt-thor-pv-linkage-dialog>`;
}

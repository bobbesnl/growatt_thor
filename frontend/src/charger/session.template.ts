/** Vehicle session area: session metrics, warnings and the charging-target notice. */
import { html, nothing } from 'lit';
import { liveTargetStatus, targetNoticeVisible } from '../targets/live';
import type { CardViewModel } from './card-view-model';

export function renderSession({
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

export function renderWarnings({
  status,
  faultMessage,
  data,
  t,
  meterWarning,
  batteryDrain,
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
    ${status.key === 'rebooting'
      ? html`<div class="notice warning" role="status">
          <ha-icon icon="mdi:restart"></ha-icon>${t('rebootingNotice')}
        </div>`
      : nothing}
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
    ${batteryDrain !== null
      ? html`<div class="notice warning battery-drain-notice" role="status">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <p>
            <strong>${t('batteryDrainTitle')} · ${format(batteryDrain)} kW</strong>
            ${t('batteryDrainSite')}
            ${data.working_mode !== 'pv_linkage_plus'
              ? html`<br />${t('batteryDrainModeHint')}`
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

export function renderTargetNotice(view: CardViewModel) {
  const { charging_target: request } = view.data;
  if (!request || !targetNoticeVisible(request, view.now)) return nothing;

  const unit =
    request.kind === 'energy' ? 'kWh' : request.kind === 'duration' ? 'min' : view.currency;
  const scheduledAt = Date.parse(request.scheduled_for || '');
  const scheduledLabel = Number.isFinite(scheduledAt)
    ? new Date(scheduledAt).toLocaleString(
        view.hass.language || view.hass.locale?.language || 'en',
        { dateStyle: 'medium', timeStyle: 'short', timeZone: view.hass.config?.time_zone || 'UTC' },
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

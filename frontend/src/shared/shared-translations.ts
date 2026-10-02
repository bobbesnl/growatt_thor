// Select only reusable labels for the bundle; integration JSON remains the source.
export const sharedPaths: Record<string, string> = {
  ...Object.fromEntries(
    [
      'available',
      'preparing',
      'charging',
      'suspended_evse',
      'suspended_ev',
      'finishing',
      'reserved',
      'unavailable',
      'faulted',
      'idle',
    ].map((key) => [key, `entity.sensor.status.state.${key}`]),
  ),
  ...Object.fromEntries(
    ['fast', 'pv_linkage', 'off_peak'].map((key) => [
      key,
      `entity.sensor.working_mode.state.${key}`,
    ]),
  ),
  pv_linkage_plus: 'entity.sensor.solar_mode.state.pv_linkage_plus',
  ...Object.fromEntries(
    ['home_assistant_rfid', 'rfid_only', 'plug_and_charge'].map((key) => [
      key,
      `entity.sensor.charger_mode.state.${key}`,
    ]),
  ),
  chargeMode: 'entity.select.working_mode.name',
  authorization: 'entity.sensor.charger_mode.name',
  power: 'entity.sensor.charging_power.name',
  gridPower: 'entity.sensor.grid_power.name',
  start: 'entity.button.start_charging.name',
  stop: 'entity.button.stop_charging.name',
  limit: 'entity.number.max_current.name',
};

export function extractSharedTranslations(source: Record<string, unknown>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, path] of Object.entries(sharedPaths)) {
    let value: unknown = source;
    for (const segment of path.split('.'))
      value =
        value && typeof value === 'object'
          ? (value as Record<string, unknown>)[segment]
          : undefined;
    // Missing entries fall back to English; HA references/placeholders are not UI text.
    if (
      typeof value === 'string' &&
      value.trim() &&
      !value.includes('[%key:') &&
      !value.includes('{')
    )
      result[key] = value;
  }
  return result;
}

import { html } from 'lit';

/**
 * One card option shown by Home Assistant's `ha-form`.
 *
 * `fallback` is the value the card uses while the option is absent from the
 * configuration; it is shown in the form but never written back unchanged.
 * `accept` rejects a value the form passes through although it is outside the
 * selector's range, so an invalid entry keeps the previous option.
 */
export interface EditorField<Config> {
  name: keyof Config & string;
  selector: Record<string, unknown>;
  label: string;
  helper?: string;
  fallback?: unknown;
  accept?(value: unknown): boolean;
}

export function editorFormData<Config extends object>(
  config: Config,
  fields: readonly EditorField<Config>[],
): Record<string, unknown> {
  const options = config as Record<string, unknown>;
  return Object.fromEntries(
    fields.map((field) => [field.name, options[field.name] ?? field.fallback]),
  );
}

/**
 * Apply the options a form change touched; return `undefined` when nothing changed.
 *
 * An emptied option is removed, so the card returns to its default.
 */
export function applyEditorValue<Config extends object>(
  config: Config,
  fields: readonly EditorField<Config>[],
  value: Record<string, unknown>,
): { config: Config; changed: (keyof Config & string)[] } | undefined {
  const shown = editorFormData(config, fields);
  const next = { ...config } as Record<string, unknown>;
  const changed: (keyof Config & string)[] = [];
  for (const field of fields) {
    const option = value[field.name];
    if (option === shown[field.name]) continue;
    if (option === '' || option == null) delete next[field.name];
    else if (field.accept && !field.accept(option)) continue;
    else next[field.name] = option;
    changed.push(field.name);
  }
  return changed.length ? { config: next as Config, changed } : undefined;
}

export function numberWithin(min: number, max: number, integer = false) {
  return (value: unknown): boolean =>
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= min &&
    value <= max &&
    (!integer || Number.isInteger(value));
}

export function renderEditorForm<Config extends object>(
  hass: unknown,
  config: Config,
  fields: readonly EditorField<Config>[],
  onValue: (value: Record<string, unknown>) => void,
) {
  const byName = new Map(fields.map((field) => [field.name as string, field]));
  return html`<ha-form
    .hass=${hass}
    .data=${editorFormData(config, fields)}
    .schema=${fields.map(({ name, selector }) => ({ name, selector }))}
    .computeLabel=${(schema: { name: string }) => byName.get(schema.name)?.label ?? schema.name}
    .computeHelper=${(schema: { name: string }) => byName.get(schema.name)?.helper}
    @value-changed=${(event: CustomEvent<{ value: Record<string, unknown> }>) =>
      onValue(event.detail.value)}
  ></ha-form>`;
}

export function formatNumber(
  value: number | null,
  language?: string,
  maximumFractionDigits = 2,
): string {
  return value === null ? '—' : value.toLocaleString(language, { maximumFractionDigits });
}

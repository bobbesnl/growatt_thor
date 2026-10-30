export type Language = 'en' | 'de' | 'nl' | 'fr' | 'es' | 'it' | 'hu' | 'sl';
export type Translator = (key: string) => string;
type Dictionaries<K extends string> = Record<string, Partial<Record<K, string>>>;

/** Integration labels take precedence; feature dictionaries own their remaining labels. */
export function createTranslator<K extends string>(
  dictionaries: Dictionaries<K>,
  language = 'en',
  integration: Dictionaries<K> = {},
): Translator {
  const locale = language.toLowerCase().replaceAll('_', '-');
  const base = locale.split('-')[0];
  return (key) => {
    const label = key as K;
    return (
      integration[locale]?.[label] ||
      integration[base]?.[label] ||
      dictionaries[locale]?.[label] ||
      dictionaries[base]?.[label] ||
      integration.en?.[label] ||
      dictionaries.en?.[label] ||
      key
    );
  };
}

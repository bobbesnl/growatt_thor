import { en } from './locales/en';
import { de } from './locales/de';
import { cardLabelDictionaries, type CardLabelKey } from './locales/card-labels';
type Key = keyof typeof en;
export type Translator = (key: string) => string;

const shared = typeof __SHARED_TRANSLATIONS__ === 'undefined' ? {} : __SHARED_TRANSLATIONS__;
export function createTranslator(
  language = 'en',
  translations: Record<string, Record<string, string>> = shared,
) {
  const locale = language.toLowerCase().replaceAll('_', '-');
  const base = locale.split('-')[0];
  const local = base === 'de' ? de : base === 'en' ? en : undefined;
  const labels = cardLabelDictionaries[locale] || cardLabelDictionaries[base];
  return (key: string): string =>
    translations[locale]?.[key] ||
    translations[base]?.[key] ||
    local?.[key as Key] ||
    labels?.[key as CardLabelKey] ||
    translations.en?.[key] ||
    en[key as Key] ||
    key;
}
export const translate = (language = 'en') => createTranslator(language);

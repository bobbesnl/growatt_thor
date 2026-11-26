import { en } from './locales/en';
import { de } from './locales/de';
import { cardLabelDictionaries } from './locales/card-labels';
import { createTranslator } from './i18n';
export type { Translator } from './i18n';

export const cardDictionaries = { en, de, ...cardLabelDictionaries };
const shared = typeof __SHARED_TRANSLATIONS__ === 'undefined' ? {} : __SHARED_TRANSLATIONS__;
export const createCardTranslator = (
  language = 'en',
  integration: Record<string, Record<string, string>> = shared,
) => createTranslator(cardDictionaries, language, integration);
export const translate = createCardTranslator;

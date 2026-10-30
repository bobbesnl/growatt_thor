import type { Language } from '../i18n';
import { en } from './en';
import { nl } from './nl';
import { fr } from './fr';
import { es } from './es';
import { it } from './it';
import { hu } from './hu';
import { sl } from './sl';

export type CardLabelKey = keyof typeof en;
export const cardLabelKeys = Object.keys(en) as CardLabelKey[];
export const cardLabelDictionaries: Record<
  Exclude<Language, 'en' | 'de'>,
  Record<CardLabelKey, string>
> = {
  nl,
  fr,
  es,
  it,
  hu,
  sl,
};

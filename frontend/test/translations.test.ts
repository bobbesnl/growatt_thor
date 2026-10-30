import { createTranslator as featureTranslator } from '../src/shared/i18n';
import { accountingDictionaries, accountingTranslate } from '../src/sessions/accounting.locales';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { cardLabelDictionaries, cardLabelKeys } from '../src/shared/locales/card-labels';
import { extractSharedTranslations, sharedPaths } from '../src/shared/shared-translations';
import { sessionDictionaries, sessionTranslate } from '../src/sessions/locales';
import { createCardTranslator, cardDictionaries } from '../src/shared/strings';
import { pvDictionaries, pvTranslate } from '../src/pv/locales';

const directory = new URL('../../custom_components/growatt_thor/translations/', import.meta.url);
const dictionaries = Object.fromEntries(
  readdirSync(directory)
    .filter((file) => file.endsWith('.json'))
    .map((file) => [
      file.slice(0, -5),
      extractSharedTranslations(JSON.parse(readFileSync(new URL(file, directory), 'utf8'))),
    ]),
);

test('Every integration language supplies all mapped card labels', () => {
  assert.equal(Object.keys(dictionaries).length, 8);
  for (const [language, labels] of Object.entries(dictionaries)) {
    assert.deepEqual(Object.keys(labels).sort(), Object.keys(sharedPaths).sort(), language);
    for (const [key, value] of Object.entries(labels))
      assert.equal(createCardTranslator(language, dictionaries)(key), value);
  }
});
test('Regional languages, translated card labels and missing shared labels have fallbacks', () => {
  assert.equal(createCardTranslator('de-CH', dictionaries)('available'), 'Verfügbar');
  assert.equal(createCardTranslator('DE_ch', dictionaries)('start'), 'Laden starten');
  assert.equal(createCardTranslator('de', dictionaries)('noData'), 'Keine Daten');
  assert.equal(createCardTranslator('nl', dictionaries)('noData'), 'Geen gegevens');
  assert.equal(createCardTranslator('ja', dictionaries)('charging'), dictionaries.en.charging);
  assert.equal(
    createCardTranslator('fr', { ...dictionaries, fr: {} })('charging'),
    dictionaries.en.charging,
  );
  assert.equal(createCardTranslator('en', dictionaries)('future_key'), 'future_key');
});
test('Only mapped plain strings enter the bundle', () => {
  assert.deepEqual(
    extractSharedTranslations({
      entity: {
        sensor: {
          status: { state: { charging: '[%key:common::state::charging%]', available: '{value}' } },
        },
      },
    }),
    {},
  );
  assert.equal(dictionaries.de.energy, undefined); // Keep the separate compact metric label.
});

test('Session card supplies every label in every integration language', () => {
  assert.deepEqual(Object.keys(sessionDictionaries).sort(), Object.keys(dictionaries).sort());
  const englishKeys = Object.keys(sessionDictionaries.en).sort();
  for (const [language, labels] of Object.entries(sessionDictionaries)) {
    assert.deepEqual(Object.keys(labels).sort(), englishKeys, language);
    for (const key of englishKeys)
      assert.ok(
        sessionTranslate(language)(key as keyof typeof labels).trim(),
        `${language}.${key}`,
      );
  }
});

test('Session card normalizes regional languages and falls back to English', () => {
  assert.equal(sessionTranslate('de-CH')('title'), 'Ladehistorie');
  assert.equal(sessionTranslate('NL_be')('title'), 'Laadgeschiedenis');
  assert.equal(sessionTranslate('ja')('title'), 'Charging history');
});

test('Main card supplies every label for each additional integration language', () => {
  assert.deepEqual(
    Object.keys(cardLabelDictionaries).sort(),
    Object.keys(dictionaries)
      .filter((language) => !['de', 'en'].includes(language))
      .sort(),
  );
  for (const [language, labels] of Object.entries(cardLabelDictionaries)) {
    assert.deepEqual(Object.keys(labels).sort(), [...cardLabelKeys].sort(), language);
    for (const key of cardLabelKeys) assert.ok(labels[key].trim(), `${language}.${key}`);
  }
});

test('Main-card labels use regional translations before the English fallback', () => {
  assert.equal(
    createCardTranslator('nl-NL', dictionaries)('vehicleConnected'),
    'Voertuig aangesloten',
  );
  assert.equal(
    createCardTranslator('nl', dictionaries)('goalPvNote'),
    'Dit is een starttijd, geen uiterste eindtijd. Laaddoelen blijven gescheiden van PV Smart Boost.',
  );
  assert.equal(createCardTranslator('fr', dictionaries)('goalNew'), 'Nouvel objectif');
  assert.equal(createCardTranslator('es-MX', dictionaries)('currentSession'), 'Sesión actual');
  assert.equal(createCardTranslator('ja', dictionaries)('vehicleConnected'), 'Vehicle connected');
});

test('PV dialog supplies a complete dictionary for every integration language', () => {
  assert.deepEqual(Object.keys(pvDictionaries).sort(), Object.keys(dictionaries).sort());
  const keys = Object.keys(pvDictionaries.en).sort();
  for (const [language, labels] of Object.entries(pvDictionaries)) {
    assert.deepEqual(Object.keys(labels).sort(), keys, language);
    for (const key of keys) assert.ok(pvTranslate(language)(key).trim(), `${language}.${key}`);
  }
  assert.equal(pvTranslate('de-CH')('pvMeterCurrent'), 'Messdaten aktuell');
  assert.equal(pvTranslate('nl')('pvTitle'), 'PV-laden');
});

test('Energy breakdown supplies complete localized explanations in every integration language', () => {
  assert.deepEqual(Object.keys(accountingDictionaries).sort(), Object.keys(dictionaries).sort());
  for (const messages of Object.values(accountingDictionaries)) {
    assert.deepEqual(Object.keys(messages).sort(), Object.keys(accountingDictionaries.en).sort());
    assert.ok(messages.partial.includes('{energy}'));
    assert.ok(messages.coverage.includes('{percent}'));
  }
  assert.equal(accountingTranslate('de-CH')('title'), 'Ladeenergie');
  assert.equal(accountingTranslate('xx')('title'), 'Charging energy');
});

test('Every main-card key is present and placeholders match in all eight languages', () => {
  const keys = Object.keys(cardDictionaries.en).sort();
  const placeholders = (value: string) =>
    [...value.matchAll(/\{([a-zA-Z_][a-zA-Z_0-9]*)\}/g)].map((match) => match[1]).sort();
  assert.equal(Object.keys(cardDictionaries).length, 8);
  for (const [language, labels] of Object.entries(cardDictionaries)) {
    assert.deepEqual(Object.keys(labels).sort(), keys, language);
    for (const key of keys) {
      const value = labels[key as keyof typeof labels];
      assert.ok(value.trim(), `${language}.${key}`);
      assert.deepEqual(
        placeholders(value),
        placeholders(cardDictionaries.en[key as keyof typeof cardDictionaries.en]),
        `${language}.${key}`,
      );
    }
  }
});

test('Shared fallback order prefers regional integration, local language, English and finally the key', () => {
  const dictionary = {
    en: { label: 'English', englishOnly: 'Fallback' },
    fr: { label: 'Français' },
    'fr-ca': { label: 'Québécois' },
  };
  assert.equal(featureTranslator(dictionary, 'FR_ca')('label'), 'Québécois');
  assert.equal(featureTranslator(dictionary, 'fr-CH')('label'), 'Français');
  assert.equal(featureTranslator(dictionary, 'fr')('englishOnly'), 'Fallback');
  assert.equal(featureTranslator(dictionary, 'fr')('missing'), 'missing');
  assert.equal(
    featureTranslator(dictionary, 'fr', { en: { label: 'Integration English' } })('label'),
    'Français',
  );
  assert.equal(
    featureTranslator(dictionary, 'fr-CA', { 'fr-ca': { label: 'Integration regional' } })('label'),
    'Integration regional',
  );
});

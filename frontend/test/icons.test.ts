import { test } from 'node:test';
import assert from 'node:assert/strict';
import { previewIconCatalog } from '../preview/icon-catalog';
import { mdiPlay, mdiTimerSand, mdiEvPlugType2 } from '@mdi/js';

test('Simulator resolves every referenced icon to an official MDI path', async () => {
  const icons = await previewIconCatalog();
  assert.ok(Object.keys(icons).length > 20);
  assert.equal(icons['mdi:play'], mdiPlay);
  assert.equal(icons['mdi:timer-sand'], mdiTimerSand);
  assert.equal(icons['mdi:ev-plug-type2'], mdiEvPlugType2);
  for (const path of Object.values(icons)) assert.match(path, /^M/);
});

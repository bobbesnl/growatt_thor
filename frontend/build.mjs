import { build } from 'esbuild';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { extractSharedTranslations } from './src/shared/shared-translations.ts';
import { previewIconCatalog } from './preview/icon-catalog.ts';
const { version } = JSON.parse(
  await readFile(new URL('../custom_components/growatt_thor/manifest.json', import.meta.url)),
);
const translationDir = new URL('../custom_components/growatt_thor/translations/', import.meta.url);
const translations = Object.fromEntries(
  await Promise.all(
    (await readdir(translationDir))
      .filter((file) => file.endsWith('.json'))
      .sort()
      .map(async (file) => [
        file.slice(0, -5),
        extractSharedTranslations(JSON.parse(await readFile(new URL(file, translationDir)))),
      ]),
  ),
);
if (!Object.keys(translations.en || {}).length)
  throw new Error('Missing English integration translations');
await build({
  entryPoints: ['frontend/src/index.ts'],
  bundle: true,
  format: 'esm',
  target: 'es2022',
  outfile: 'custom_components/growatt_thor/frontend/thor-card.js',
  minify: true,
  loader: { '.css': 'text' },
  legalComments: 'eof',
  define: {
    __CARD_VERSION__: JSON.stringify(version),
    __SHARED_TRANSLATIONS__: JSON.stringify(translations),
  },
});
console.log(`Built THOR card ${version}`);

// Simulator assets never enter the integration's production bundle.
const icons = await previewIconCatalog();
await build({
  entryPoints: ['frontend/preview/ha-icon.ts'],
  outfile: 'frontend/preview/ha-icon.bundle.js',
  bundle: true,
  format: 'esm',
  target: 'es2022',
  minify: true,
  define: { __PREVIEW_ICON_PATHS__: JSON.stringify(icons) },
  banner: {
    js: '/*! Material Design Icons 7.4.47 — Pictogrammers — Apache-2.0; see LICENSE-MDI. Simulator only. */',
  },
});
await writeFile(
  new URL('./preview/LICENSE-MDI', import.meta.url),
  await readFile(new URL('../node_modules/@mdi/js/LICENSE', import.meta.url)),
);
console.log(`Built simulator with ${Object.keys(icons).length} MDI icons`);
await build({
  entryPoints: ['frontend/preview/goal-panel.ts'],
  outfile: 'frontend/preview/goal-panel.bundle.js',
  bundle: true,
  format: 'esm',
  target: 'es2022',
  minify: true,
  loader: { '.css': 'text' },
});

// Design comparison assets remain isolated from the HA integration.
await build({
  entryPoints: ['frontend/preview/accounting-comparison.ts'],
  outfile: 'frontend/preview/accounting-comparison.bundle.js',
  bundle: true,
  format: 'esm',
  target: 'es2022',
  minify: true,
});
await build({
  entryPoints: ['frontend/preview/documentation-data.ts'],
  outfile: 'frontend/preview/documentation-data.bundle.js',
  bundle: true,
  format: 'esm',
  target: 'es2022',
  minify: true,
});

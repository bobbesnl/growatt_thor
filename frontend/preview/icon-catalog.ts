import { readFile, readdir } from 'node:fs/promises';
import * as mdi from '@mdi/js';

/** Build-only: embed exactly the MDI icons referenced by the card and its dialogs. */
export async function previewIconCatalog() {
  const names = new Set<string>(['mdi:help-circle-outline']);
  for (const source of [new URL('../src/', import.meta.url), new URL('./', import.meta.url)]) {
    for (const file of await readdir(source, { recursive: true })) {
      if (!file.endsWith('.ts')) continue;
      const contents = await readFile(new URL(file, source), 'utf8');
      for (const match of contents.matchAll(/mdi:[a-z0-9-]+/g)) names.add(match[0]);
    }
  }
  return Object.fromEntries(
    [...names].sort().map((name) => {
      const exportName =
        'mdi' +
        name
          .slice(4)
          .split('-')
          .map((part) => part[0].toUpperCase() + part.slice(1))
          .join('');
      const path = (mdi as Record<string, unknown>)[exportName];
      if (typeof path !== 'string') throw new Error(`Missing MDI icon: ${name} (${exportName})`);
      return [name, path];
    }),
  );
}

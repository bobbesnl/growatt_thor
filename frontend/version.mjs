import { readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';

const version = process.argv[2];
if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version || '')) {
  throw new Error('Usage: npm run release:version -- <version>');
}
for (const filename of [
  'package.json',
  'package-lock.json',
  'custom_components/growatt_thor/manifest.json',
]) {
  const data = JSON.parse(await readFile(filename, 'utf8'));
  data.version = version;
  if (data.packages?.['']) data.packages[''].version = version;
  await writeFile(filename, JSON.stringify(data, null, 2) + '\n');
}
execFileSync(process.execPath, ['frontend/build.mjs'], { stdio: 'inherit' });

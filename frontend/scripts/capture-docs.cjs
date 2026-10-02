/**
 * Capture the real simulator UI for the handbook.
 *
 * From the repository root:
 *   npm run build
 *   python3 -m http.server 8362 --bind 127.0.0.1
 *   node frontend/scripts/capture-docs.cjs
 *
 * Requires Playwright and Chrome. This script opens drafts but never submits them.
 */
const { createRequire } = require('node:module');
const fs = require('node:fs/promises');
const path = require('node:path');

const repositoryRoot = path.resolve(__dirname, '../..');
const previewUrl = process.env.THOR_PREVIEW_URL || 'http://127.0.0.1:8362/frontend/preview/';
// Use a separate directory when checking script changes without replacing handbook images.
const outputDirectory = process.env.THOR_SCREENSHOT_DIR || path.join(repositoryRoot, 'docs/images');
const fixedTime = '2026-10-02T17:04:05+02:00';
const scheduledStart = '2026-10-03T22:00';

function loadPlaywright() {
  // Also support a shared Playwright installation outside this repository.
  if (process.env.THOR_PLAYWRIGHT_PACKAGE) {
    const requireFromPackage = createRequire(process.env.THOR_PLAYWRIGHT_PACKAGE);
    return requireFromPackage('playwright');
  }
  return require('playwright');
}

async function selectPreviewOption(page, id, value) {
  await page.locator(`#${id}`).selectOption(value);
  // Changing a simulator control schedules Lit updates in several nested components.
  await page.waitForTimeout(80);
}

async function captureScreenshot(session, element, slug, title) {
  const { page, captures } = session;
  await element.scrollIntoViewIfNeeded();
  await element.evaluate((node) => node.getRootNode().activeElement?.blur());
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(120);

  // omitBackground removes the browser's canvas, but not CSS backgrounds or dialog
  // backdrops. Hide everything except the selected element for a transparent cutout.
  const pageStyles = await page.evaluate(() => ({
    html: document.documentElement.style.cssText,
    body: document.body.style.cssText,
  }));
  const elementStyle = await element.evaluate((node) => node.style.cssText);

  try {
    await page.evaluate(() => {
      document.documentElement.style.background = 'transparent';
      document.body.style.background = 'transparent';
      document.body.style.visibility = 'hidden';
    });
    await element.evaluate((node) => {
      node.style.visibility = 'visible';
      // Dialogs live inside shadow roots, so a document-level rule cannot hide their backdrop.
      const style = document.createElement('style');
      style.dataset.capture = 'true';
      style.textContent = `
        dialog::backdrop { background: transparent !important; backdrop-filter: none !important; }
        * { caret-color: transparent !important; }
      `;
      node.getRootNode().append(style);
    });

    // The handbook links to these numbered filenames. Keep the group order in main stable.
    const number = captures.length + 1;
    const file = `${String(number).padStart(2, '0')}-${slug}.png`;
    await element.screenshot({
      path: path.join(outputDirectory, file),
      omitBackground: true,
      animations: 'disabled',
    });
    const bounds = await element.boundingBox();
    if (!bounds) throw new Error(`Screenshot element is no longer visible: ${file}`);
    captures.push({
      number,
      file,
      title,
      width: Math.round(bounds.width),
      height: Math.round(bounds.height),
    });
    console.log(`${String(number).padStart(2, '0')}: ${title}`);
  } finally {
    // Restore the preview even if a screenshot fails. Capture-only styling must not
    // affect the layout or background of the next image.
    await element.evaluate((node, originalStyle) => {
      node.style.cssText = originalStyle;
      node.getRootNode().querySelector('style[data-capture]')?.remove();
    }, elementStyle);
    await page.evaluate((originalStyles) => {
      document.documentElement.style.cssText = originalStyles.html;
      document.body.style.cssText = originalStyles.body;
    }, pageStyles);
  }
}

async function captureChargingCards(session) {
  const { page } = session;
  const cards = page.locator('growatt-thor-card');
  const lightCard = cards.first().locator('ha-card');
  const darkCard = cards.nth(1).locator('ha-card');

  await captureScreenshot(session, lightCard, 'charger-light', 'Charging card · light');
  await captureScreenshot(session, darkCard, 'charger-dark', 'Charging card · dark');

  // Explicit settings are easier to change than deriving charger behavior from a slug.
  const sourceExamples = [
    { mix: 'solar', slug: 'solar', title: 'Solar only', mode: 'pv_linkage_plus', grid: 'balanced' },
    {
      mix: 'solar_battery',
      slug: 'solar-battery',
      title: 'Solar + battery',
      mode: 'pv_linkage_plus',
      grid: 'balanced',
    },
    {
      mix: 'solar_grid',
      slug: 'solar-grid',
      title: 'Solar + grid',
      mode: 'pv_linkage',
      grid: 'import',
    },
    {
      mix: 'mixed',
      slug: 'mixed',
      title: 'Solar + battery + grid',
      mode: 'pv_linkage',
      grid: 'import',
    },
  ];
  for (const example of sourceExamples) {
    await selectPreviewOption(page, 'source-mix', example.mix);
    await selectPreviewOption(page, 'working-mode', example.mode);
    await selectPreviewOption(page, 'grid-balance', example.grid);
    await captureScreenshot(
      session,
      lightCard,
      `sources-${example.slug}`,
      `Charging sources · ${example.title}`,
    );
  }
}

async function captureTargetDialogs(session) {
  const { page } = session;
  await selectPreviewOption(page, 'source-mix', 'none');
  await selectPreviewOption(page, 'scenario', 'available');
  await selectPreviewOption(page, 'working-mode', 'fast');

  // Mark the card's own dialog so Playwright does not select a nested preview dialog.
  const card = page.locator('growatt-thor-card').first();
  await card.evaluate((node) => {
    node.shadowRoot
      .querySelector('growatt-thor-goal-dialog')
      .setAttribute('data-doc-target', 'true');
  });
  const targetDialog = card.locator('growatt-thor-goal-dialog[data-doc-target]');
  const targets = [
    { kind: 'energy', value: '20', title: 'Energy' },
    { kind: 'duration', value: '120', title: 'Duration' },
    { kind: 'budget', value: '8', title: 'Budget' },
  ];
  const schedules = [
    { key: 'now', title: 'now' },
    { key: 'once', title: 'scheduled once' },
    { key: 'daily', title: 'every day' },
  ];

  // Reopen for each combination to start with a fresh draft, then close without saving.
  for (const target of targets) {
    for (const schedule of schedules) {
      await targetDialog.evaluate((node) => node.open());
      const dialog = targetDialog.locator('dialog');
      await dialog
        .locator(`input[name="goal-kind"][value="${target.kind}"]`)
        .check({ force: true });
      await dialog.locator('#goal-value').fill(target.value);
      if (schedule.key !== 'now') {
        await dialog.locator('label.choice').filter({ hasText: 'At a set time' }).click();
        await dialog.locator('#goal-at').fill(scheduledStart);
        if (schedule.key === 'daily') {
          await dialog.locator('.recurrence input').check();
        }
      }
      await captureScreenshot(
        session,
        dialog,
        `goal-${target.kind}-${schedule.key}`,
        `${target.title} target · ${schedule.title}`,
      );
      await dialog.getByRole('button', { name: 'Close', exact: true }).first().click();
      await page.waitForTimeout(80);
    }
  }
}

async function captureAuthorizationDialogs(session) {
  const dialogHost = session.page
    .locator('growatt-thor-card')
    .first()
    .locator('growatt-thor-auth-dialog');
  const modes = [
    { value: 'home_assistant_rfid', slug: 'home-assistant-rfid', title: 'home assistant rfid' },
    { value: 'rfid_only', slug: 'rfid-only', title: 'rfid only' },
    { value: 'plug_and_charge', slug: 'plug-and-charge', title: 'plug and charge' },
  ];
  for (const mode of modes) {
    await dialogHost.evaluate((node) => node.open('select.authorization'));
    await dialogHost.locator('#auth-option').selectOption(mode.value);
    await captureScreenshot(
      session,
      dialogHost.locator('dialog'),
      `authorization-${mode.slug}`,
      `Authorization · ${mode.title}`,
    );
    await dialogHost.evaluate((node) => node.close());
  }
}

async function captureChargingModeDialogs(session) {
  const { page } = session;
  await selectPreviewOption(page, 'working-mode', 'pv_linkage_plus');
  const dialogHost = page
    .locator('growatt-thor-card')
    .first()
    .locator('growatt-thor-pv-linkage-dialog');
  const dialog = dialogHost.locator('dialog');
  await dialogHost.evaluate((node) => {
    const status = node.hass.states['sensor.thor_status'];
    node.open('sensor.thor_status', status.attributes.thor_card.pv_linkage);
  });
  await captureScreenshot(
    session,
    dialog,
    'charging-mode-prerequisites',
    'Charging mode · prerequisites',
  );
  await dialogHost.evaluate((node) => node.next());

  const modes = [
    { value: 'pv_linkage_plus', slug: 'solar-only', title: 'PV Linkage+' },
    { value: 'pv_linkage', slug: 'grid-allowed', title: 'PV Linkage' },
  ];
  const boosts = [
    { value: 'disabled', title: 'no boost' },
    { value: 'manual', title: 'time-window boost' },
    { value: 'smart', title: 'ready-by-time boost' },
  ];
  for (const mode of modes) {
    for (const boost of boosts) {
      // These setters update the local draft only; applying it is a separate action.
      await dialogHost.evaluate(
        (node, settings) => {
          node.setMode(settings.mode);
          node.setBoost(settings.boost);
          node.setField('gridImportLimitKw', '1.5');
          node.setField('manualStart', '18:00');
          node.setField('manualEnd', '20:00');
          node.setField('smartFinish', '07:00');
          node.setField('smartTargetEnergyKwh', '20');
        },
        { mode: mode.value, boost: boost.value },
      );
      await captureScreenshot(
        session,
        dialog,
        `charging-mode-${mode.slug}-${boost.value}`,
        `${mode.title} · ${boost.title}`,
      );
    }
  }
  await dialogHost.evaluate((node) => node.next());
  await captureScreenshot(
    session,
    dialog,
    'charging-mode-review',
    'Charging mode · review before applying',
  );
  await dialogHost.evaluate((node) => node.close());
}

async function captureSessionCards(session) {
  const { page } = session;
  const cards = page.locator('growatt-thor-session-card');
  // Use the same selected session and page size in both themes for comparable images.
  await cards.evaluateAll((nodes) => {
    for (const node of nodes) {
      node.setConfig({ ...node._config, rows: 4, show_identifier: true });
      node.selectSession('documentation-0');
      node.parentElement.style.width = '1000px';
    }
  });
  // ECharts needs time to load session details and react to the changed container width.
  await page.waitForTimeout(450);
  await captureScreenshot(
    session,
    cards.first().locator('ha-card'),
    'history-light',
    'Charging history · desktop light',
  );
  await captureScreenshot(
    session,
    cards.nth(1).locator('ha-card'),
    'history-dark',
    'Charging history · desktop dark',
  );

  await cards.first().evaluate((node) => {
    node.parentElement.style.width = '390px';
    node.setConfig({ ...node._config, rows: 2 });
  });
  await page.waitForTimeout(300);
  await captureScreenshot(
    session,
    cards.first().locator('ha-card'),
    'history-mobile',
    'Charging history · mobile',
  );
}

async function main() {
  const { chromium } = loadPlaywright();
  await fs.mkdir(outputDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1600, height: 1800 },
      deviceScaleFactor: 2,
      locale: 'en-GB',
      timezoneId: 'Europe/Berlin',
      reducedMotion: 'reduce',
    });
    await page.clock.setFixedTime(new Date(fixedTime));
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));

    // Keep all browser requests on the preview origin, including fonts and images.
    await page.route('**/*', (route) => {
      if (new URL(route.request().url()).origin === new URL(previewUrl).origin) {
        return route.continue();
      }
      return route.abort();
    });
    await page.goto(previewUrl);
    await page.locator('growatt-thor-card').first().locator('ha-card').waitFor();
    await selectPreviewOption(page, 'language', 'en');
    await selectPreviewOption(page, 'session-profile', 'documentation');
    await selectPreviewOption(page, 'width', '520');
    await selectPreviewOption(page, 'auth', 'plug_and_charge');
    await selectPreviewOption(page, 'scenario', 'charging');
    await selectPreviewOption(page, 'source-mix', 'none');

    // Capture order determines the existing handbook filenames (01–29).
    const session = { page, captures: [] };
    await captureChargingCards(session); // 01–06
    await captureTargetDialogs(session); // 07–15
    await captureAuthorizationDialogs(session); // 16–18
    await captureChargingModeDialogs(session); // 19–26
    await captureSessionCards(session); // 27–29

    if (pageErrors.length) throw new Error(pageErrors.join('\n'));
    const manifest = {
      locale: 'en-GB',
      scale: 2,
      source: 'Local simulator; illustrative data, not a Home Assistant export',
      captures: session.captures,
    };
    await fs.writeFile(
      path.join(outputDirectory, 'screenshots.json'),
      JSON.stringify(manifest, null, 2) + '\n',
    );
    console.log(`Captured ${session.captures.length} PNGs in ${outputDirectory}.`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

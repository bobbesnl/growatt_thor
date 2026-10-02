# Frontend development

The frontend uses TypeScript, Lit and ECharts to implement two Home Assistant
cards: `custom:growatt-thor-card` and `custom:growatt-thor-session-card`.
This guide covers the development workflow, source boundaries and generated
assets. For card configuration and end-user behavior, see the
[Charging](../docs/usage.md) and [Sessions](../docs/sessions.md) handbook chapters.

## Local workflow

Run commands from the repository root. Use Node **22.18+ or 24+**; CI runs on
Node 22. Python is needed only for the local HTTP server and image-processing
scripts. See the [contributor guide](../docs/CONTRIBUTING.md#local-checks) for
backend prerequisites and checks.

```sh
npm ci
npm run build
python3 -m http.server 8362 --bind 127.0.0.1
```

Open `http://127.0.0.1:8362/frontend/preview/`. Rebuild after source changes and
reload the preview; the HTTP server serves the generated files without rebuilding
them. The simulator runs locally with mock service calls and does not contact a
wallbox.

Before submitting a change:

```sh
npm run format
npm run check
```

`check` runs the formatting check, TypeScript check, unit tests and build in that
order. Review and include generated asset changes in the same commit as their
sources. For focused iteration, run `npm run typecheck`, `npm test` or
`npm run build` separately.

## Frontend structure

Paths in this table are relative to `frontend/`.

| Path | Responsibility |
| --- | --- |
| `src/index.ts` | Production entry point; imports the card registration code. |
| `src/charger/` | Charging card and editor, templates, styles and pure view-model calculations. |
| `src/targets/` | Charging-target dialog, draft validation and service eligibility. |
| `src/authorization/` | Authorization-mode dialog. |
| `src/pv/` | PV-mode dialog, draft model and translations. |
| `src/sessions/` | History card and editor, chart rendering, event timeline and accounting display. |
| `src/sessions/detail-store.ts` | On-demand detail loading, retries and an entry-scoped cache of up to 50 sessions. |
| `src/energy/model.ts` | Grid balance, freshness checks, PV gauge targets and source splits. |
| `src/shared/types.ts` | Typed Home Assistant boundary, card configuration and serialized view contracts. |
| `src/shared/model.ts` | Shared state, command eligibility and capability rules. |
| `src/shared/locales/` | Card-specific labels. See [Translations](#translations) for shared integration labels. |
| `test/` | Unit tests and reusable HA/device fixtures in `fixtures.ts`. |
| `preview/` | Simulator controls, mock state, documentation fixtures and preview-only bundles. |
| `scripts/` | Documentation capture, image composition and annotation tools. |
| `build.mjs` | Production and preview builds, translation extraction and icon generation. |

### Component and model boundaries

Use classes for stateful ownership, such as component lifecycles and pending
requests. Use typed functions for calculations and view-model transformations.
HA entities can be absent; narrow their values before reading attributes.
Unknown attributes stay `unknown` until validated, rather than being cast to a
card contract.

Keep transformations out of templates. A `.template.ts` file receives typed
view data and callbacks and renders with Lit's `html` or `svg` tags. It should
not receive the component instance or send service calls directly. Charger
commands belong in the component's guarded command path.

CSS is embedded at build time and passed through `unsafeCSS`. Only use trusted
source files with this adapter. Preserve the DOM structure required by container
queries and native-dialog focus handling when changing templates.

## Home Assistant integration and data contracts

The backend's `presentation/frontend.py` serves the production assets and
registers the JavaScript URL through `add_extra_js_url`. Card code registers its
custom elements and `window.customCards` entries. The URL includes the manifest
version; registration occurs once per HA process. Reload open clients after an
upgrade.

The status sensor's versioned `thor_card` attribute supplies bounded display data
and registry-resolved entity IDs. It excludes raw transactions and configured
authorization lists. A session may expose its observed identifier; this does not
expose the RFID allowlist.

The session card reads recent rows from that projection and loads historical
curves on demand. Its page-size setting applies within those bounded rows.
An active session is a transient row and is excluded from completed-history
totals. `detail-store.ts` discards responses invalidated by an entry change;
retain this behavior when modifying request handling.

Keep the following distinctions intact when changing models or rendering:

- Missing historical values stay unknown. They must not become zero energy or zero cost.
- An `≈` value is a live estimate from power readings, separate from counter-based accounting.
- The wallbox-reported session cost is separate from calculated grid cost.
- Source allocation uses an accounting rule. Validate the source balance before displaying it; see [the calculation reference](../docs/site-energy-accounting.md).
- Queued, accepted, active, blocked, cancelled, reached and uncertain target states have different meanings. Do not collapse them into a generic success state.

Target dialogs call the backend's guarded services. They do not implement stop
timers or silently retry uncertain writes. Budget targets remain experimental;
firmware evidence is recorded in the [reverse-engineering notes](../reverse_engineering/charging_targets.md).

## Responsive rendering

Use **container width**, rather than viewport width, when adapting cards to a
Home Assistant dashboard column. At widths up to 600 px, session rows become
cards and chart events move into a chronological list. Both layouts share
filtering, sorting, pagination and selection.

The chart's `ResizeObserver` updates time-label density; ECharts suppresses
remaining overlapping labels. Preserve zoom and legend state across redraws.
The event list covers the full selected session regardless of chart zoom and
shares event labels with the wide chart through `events.template.ts`.

For UI changes, exercise narrow and wide cards, both themes, multiple languages,
missing data and accepted/rejected/network-error scenarios in the simulator.
Unit tests cover model rules and request lifecycles; they do not verify layout
or firmware behavior.

## Translations

Edit labels at their source, then rebuild:

| Label type | Source |
| --- | --- |
| Shared status, mode and control names | Integration JSON in `custom_components/growatt_thor/translations/`, mapped by `src/shared/shared-translations.ts`. |
| Card-specific copy and compact metrics | `src/shared/locales/`. |
| PV, session and accounting labels | Locale dictionaries in the corresponding feature package. |
| Language selection and fallback | `src/shared/strings.ts`. |

The build embeds the mapped integration labels; no runtime translation download
is required. Do not duplicate those labels in `shared/strings.ts`. Regional
locales use their base language, with English as the fallback. Translation tests
check key parity across the eight supported integration languages.

## Build outputs and asset provenance

`npm run build` generates the following tracked files. Commit changed outputs
with their sources; do not edit generated bundles manually.

| Output | Used by |
| --- | --- |
| `custom_components/growatt_thor/frontend/thor-card.js` | Home Assistant; includes the cards, styles and selected ECharts modules. |
| `frontend/preview/ha-icon.bundle.js` | Simulator MDI icons. |
| `frontend/preview/goal-panel.bundle.js` | Simulator target controls. |
| `frontend/preview/accounting-comparison.bundle.js` | Accounting design comparison page. |
| `frontend/preview/documentation-data.bundle.js` | Documentation session fixtures. |
| `frontend/preview/LICENSE-MDI` | License copied from the pinned `@mdi/js` dependency. |

Home Assistant receives the production card bundle and `thor-front.png`; it does
not need Node or internet access to load them. Preview bundles stay outside the
integration package.

The icon build scans literal `mdi:` names in source and preview TypeScript and
fails on unknown names. Keep icon names literal so the catalog can discover
them. The simulator embeds SVG paths from pinned `@mdi/js`, with inherited colors
and sizing. It emulates icons, not HA's full frontend: real HA provides its own
icons, more-info dialogs and visual editor.

The charging card uses a device illustration, half-circle gauge, phase bars and
session controls. Growatt lime is the brand accent; operational states also use
text and icons. `thor-front.png` is an AI-generated front view based on the THOR
product image. An SVG contour clips the raster image and CSS supplies its shadow.
The illustration's screen is decorative and must never convey live readings.
This is an unofficial integration, not a Growatt-endorsed product.

## Documentation screenshots

Use the simulator's **Documentation · realistic example history** profile for
repeatable captures. It uses the real target dialogs with a mock backend and
contains illustrative curves and identifiers, not exported HA records.
The [screenshot index](../docs/screenshots.md) lists the captured variants.

With the preview server running after a build, run:

```sh
# Requires Playwright and Chrome, installed separately.
node frontend/scripts/capture-docs.cjs
```

The script groups captures into charging cards, target dialogs, authorization,
PV modes and session cards. Start with `main()` to see the capture order; edit
the example lists in the corresponding function to change a variant. Keep the
order stable because the handbook uses numbered filenames.

Set `THOR_SCREENSHOT_DIR` to a separate output directory when testing changes
without replacing handbook images. Set `THOR_PREVIEW_URL` to override the preview
URL. If Playwright is installed
outside the project, set `THOR_PLAYWRIGHT_PACKAGE` to the absolute path of a
`package.json` from which Node can resolve `playwright`.

The script fixes time, English locale, Europe/Berlin time zone and 2× resolution.
It blocks requests outside the preview origin and does not submit dialog actions.
It captures actual elements with `omitBackground: true`, hiding surrounding
content and modal backdrops. Output filenames and dimensions are recorded in
`docs/images/screenshots.json`. This script captures simulator views; it does
not recapture the separate Home Assistant settings screenshots.

After updating source captures, regenerate the derived images with Pillow:

```sh
python3 frontend/scripts/compose-theme-preview.py
python3 frontend/scripts/annotate-docs.py
```

The first script combines the light/dark captures for the README. The second
adds numbered annotations using `docs/images/annotations.json`. Both preserve
the source screenshots. Annotation geometry must be reviewed if image dimensions
change; the script rejects mismatched sizes. Set `THOR_ANNOTATION_FONT` to a
TrueType font if neither Chalkboard nor DejaVu Sans is available.

Keep annotation explanations beside the images in the relevant handbook chapter.
The annotation script writes PNGs only; it does not generate documentation prose.

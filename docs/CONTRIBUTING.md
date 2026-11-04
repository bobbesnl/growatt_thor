# Contributing to the THOR integration

[Project overview](../README.md) · [Documentation](../README.md#documentation)

## Start with one path through the code

The integration is the local OCPP server; the wallbox connects to it. Home
Assistant loads a **config entry** (one saved integration configuration), creates
one coordinator, starts the server and forwards setup to entity platforms.
An **entity** is HA's view/control of a value. The **coordinator** owns shared
observations and the command queue; it is not proof that a requested change
has happened on the device.

Read [architecture reference](architecture.md) for layers, glossary and package responsibilities,
[runtime flows](runtime-flows.md) for Start, Stop, configuration writes and session completion,
and [invariants](invariants.md) with their [decision records](adr/README.md) before changing behavior.
Then follow one of these paths rather than reading the whole coordinator first:

| To understand…                 | Read in this order                                                                                                                                                                                                                                                                                       | Relevant tests                                                                                                     |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Setup and reload               | [`__init__.py`](../custom_components/growatt_thor/__init__.py) → [`runtime/ownership.py`](../custom_components/growatt_thor/runtime/ownership.py)                                                                                                                                                              | [`test_runtime_ownership.py`](../tests/test_runtime_ownership.py)                                                     |
| A Stop request                 | [`charging/growatt_charger.py`](../custom_components/growatt_thor/charging/growatt_charger.py) → [`charging/commands.py`](../custom_components/growatt_thor/charging/commands.py) → `GrowattCoordinator.queue_write()` → [`runtime/charger_write_queue.py`](../custom_components/growatt_thor/runtime/charger_write_queue.py)                                                                                                   | [`test_charging_commands.py`](../tests/test_charging_commands.py), [`test_write_queue_coordinator.py`](../tests/test_write_queue_coordinator.py) |
| Native targets and schedules   | [`targets/model.py`](../custom_components/growatt_thor/targets/model.py) → [`targets/runtime.py`](../custom_components/growatt_thor/targets/runtime.py) → [`targets/runner.py`](../custom_components/growatt_thor/targets/runner.py)                                                                              | [`test_charging_target_services.py`](../tests/test_charging_target_services.py)                                       |
| Session completion and restart | [`sessions/runtime.py`](../custom_components/growatt_thor/sessions/runtime.py) → [`sessions/outbox.py`](../custom_components/growatt_thor/sessions/outbox.py) → [`sessions/csv.py`](../custom_components/growatt_thor/sessions/csv.py)                                                                            | [`test_session_outbox.py`](../tests/test_session_outbox.py), [`test_session_csv.py`](../tests/test_session_csv.py)       |
| Energy allocation              | [`energy/site_observations.py`](../custom_components/growatt_thor/energy/site_observations.py) → [`energy/session_accumulator.py`](../custom_components/growatt_thor/energy/session_accumulator.py) → [`energy/allocation.py`](../custom_components/growatt_thor/energy/allocation.py)                                        | [`test_site_accounting.py`](../tests/test_site_accounting.py)                                                         |
| Card data and rendering        | [`presentation/card_data.py`](../custom_components/growatt_thor/presentation/card_data.py) → [`frontend/src/shared/types.ts`](../frontend/src/shared/types.ts) → [`charger/card-view-model.ts`](../frontend/src/charger/card-view-model.ts) → [`charger/card.template.ts`](../frontend/src/charger/card.template.ts) | [`test_card_data.py`](../tests/test_card_data.py), [`card-view-model.test.ts`](../frontend/test/card-view-model.test.ts), [`charger-card-template.test.ts`](../frontend/test/charger-card-template.test.ts) |

### Example: a Stop is an intent, then a protocol result, then an observation

1. The button or optional stop guard calls `ChargerControl.async_stop()`;
   `GrowattOcppCharger` passes it to `StopChargingCommand.async_request()`.
   It first cancels an unsent Start if that is what the user is undoing.
2. The command captures the active transaction identity and enters the shared
   queue. The queue revalidates delayed work before sending it.
3. An `Accepted` response confirms the OCPP command. It does not itself establish
   that charging power is zero or that `StopTransaction` has arrived.
4. Incoming OCPP messages update the coordinator and session lifecycle. HA entities
   and the card then reflect those observations.

This explains why queue results, transaction state and measured power are kept
separate. Read [automation resilience](automation-resilience.md)
for timeout, replacement and reconnect examples before changing this path.

### Example: a displayed session is a bounded projection

OCPP and Growatt session records enter the coordinator/session lifecycle. Matching
records share an identity; unrelated late records keep their own. Completed rows
pass through the checkpointed outbox to CSV. The status sensor exposes a compact
projection, not the full archive or authorization configuration.

The main card derives display values through a pure view model. The session card
uses `SessionDetailStore` to load retained details only when needed. Lit's
`willUpdate()` resets the entry scope before rendering; `updated()` can then draw
the chart and request details. Returning from an older request must not overwrite
a newer entry's data. See [frontend development](../frontend/README.md) for the
simulator, rendering conventions and source map.

Target request records are built in [`targets/requests.py`](../custom_components/growatt_thor/targets/requests.py); guarded charger operations live in [`targets/charger_ops.py`](../custom_components/growatt_thor/targets/charger_ops.py), and the runtime reaches them only through the `NativeTargetControl` capability from [`charging/control.py`](../custom_components/growatt_thor/charging/control.py). The runtime retains its queue callbacks, execution lock, busy flag and schedule timer.

For retained history, start with [`sessions/csv.py`](../custom_components/growatt_thor/sessions/csv.py) for writes and retention, [`history_store.py`](../custom_components/growatt_thor/sessions/history_store.py) for the shared lock and recovery journal, and [`history_views.py`](../custom_components/growatt_thor/sessions/history_views.py) for card/detail reads. Row normalization, archive totals and exports live in their respective sibling modules. Tests patch the implementation owner rather than a former import path.

## Local checks

Run commands from the repository root. CI uses Python 3.12 and Node 22; the
frontend requires Node 22.18+ or Node 24+. These are development tools; the
installed integration ships its already-built card assets.

```sh
python3.12 -m venv .local/dev-venv
. .local/dev-venv/bin/activate
python -m pip install -r tests/requirements-auth.txt ruff==0.17.3
ruff check .
ruff format --check .
python -m mypy
python -m pytest
```

Despite its historical name, `requirements-auth.txt` supplies the OCPP and schema
dependencies used by several regression suites, the pinned mypy checker and the
pytest runner. Many tests load focused modules
with small HA fakes; they exercise contracts without launching Home Assistant. Shared fixtures live in `tests/support`: `install_ha_stubs`, `load_package_module`, `FakeHass`, `MemoryStore` and `build_coordinator`. The loader skips protocol-dependent cases when optional test dependencies are unavailable and avoids running integration setup for focused modules. Keep explicit test namespaces only where module-global patches require isolation; extend shared fixtures instead of copying bootstrap or storage code.
Install the dependencies so those cases are not silently skipped. Ruff checks Python style and import hygiene with a 100-character line length and Python 3.12 syntax; `ruff format custom_components tests` applies the formatter. Enum and type-alias modernizations remain excluded because their runtime representation can change. Tests import shared fixtures through `tests.support` rather than importing another test module. `python -m unittest tests.test_time_contract` is supported as an isolated run.

pytest is only the runner: the suites are written with `unittest` and still run
with `python -m unittest discover -s tests -q`. Add new tests in the same style.
[`tests/test_properties.py`](../tests/test_properties.py) uses Hypothesis to
check rules for generated inputs: site accounting books every kWh exactly once,
and the value and time parsers never raise on arbitrary input, never round and
never guess across daylight-saving changes. A failure prints the smallest
failing input; add it as an example-based regression test with the fix.
A targeted run can use `python -m pytest tests/test_session_outbox.py -v`. CI
measures line and branch coverage; run `python -m pytest --cov` for the same
report locally.

#### Tests against a real Home Assistant

[`tests_ha/`](../tests_ha) sets up the integration in a real Home Assistant core
with `pytest-homeassistant-custom-component`: the config and options flows,
setup, unload and reload with the OCPP server on a local port, entity platforms
and services. [`tests_ha/simulator.py`](../tests_ha/simulator.py) is an OCPP 1.6
charge point that connects over a real WebSocket; the end-to-end scenarios use it
for a full Start/MeterValues/Stop session, a rejected Remote Start, a reconnect
during a transaction and a second charger that must not take over the entry.
The simulator answers only the messages these scenarios need; it is no
substitute for testing with a THOR. The unit suites replace `homeassistant` with stand-ins, so this
suite needs its own environment. CI runs it twice:

| Stack | Python | Home Assistant | ocpp | websockets |
| --- | --- | --- | --- | --- |
| `min` | 3.12 | 2024.12.0, the declared minimum | 2.0.0 | 13.1 |
| `latest` | 3.14 | current release | newest 2.x | newest allowed |

```sh
python3.14 -m venv .local/ha-latest-venv
.local/ha-latest-venv/bin/pip install -r tests_ha/requirements-latest.txt
.local/ha-latest-venv/bin/python -m pytest -c tests_ha/pytest.ini --rootdir=. tests_ha
```

Use Python 3.12 and `requirements-min.txt` for the oldest stack. When a new Home
Assistant release is out, update the `pytest-homeassistant-custom-component` and
`home-assistant-frontend` pins in `requirements-latest.txt` together; the
frontend version is the one in Home Assistant's `components/frontend/manifest.json`.
The test harness does not install manifest requirements, so both files list
`ocpp` and `websockets` explicitly. Home Assistant core does not ship
`websockets` itself; the manifest declares it for that reason.

To run the same Python and formatting checks before every commit, install the
hooks once inside the development venv. They call the tools from the venv and
`node_modules`, so their versions match CI:

```sh
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### Layer boundaries and size budgets

[`tests/test_layer_boundaries.py`](../tests/test_layer_boundaries.py) enforces the
[layer direction](architecture.md#layers-at-a-glance) without importing the
integration. Its allowlists record which modules may import Home Assistant or the
`ocpp` library at runtime and which modules may import runtime owners. When code
moves, shrink the lists; an addition needs a reason in the commit message.

`python scripts/check_size_budgets.py` lists Python and TypeScript files above
600 lines and Python functions above 60 lines (limits in `pyproject.toml`). CI
reports them as warnings and in the job summary. New code should stay within the
budget; the existing overruns are candidates for later extraction, not a reason
to split code in an unrelated change.

```sh
npm ci
npm run check
```

This runs formatting, strict TypeScript checking, frontend tests and the build.
If a restricted environment blocks the `tsx` runner's IPC socket, the same tests
can run with `node --import tsx --test frontend/test/*.test.ts`.
See [frontend development](../frontend/README.md) for generated files to commit and
the local preview. Simulator and unit-test results do not establish real-device
compatibility; describe HA/firmware testing separately when reporting validation.

Options-form sensor discovery is in `source_discovery.py`. Live source allocation is in `energy/live_allocation.py`; dashboard battery and entity-map adapters are in `presentation/`.

Sensor metadata and simple value functions live in `custom_components/growatt_thor/sensor_descriptions.py`; the platform in `sensor.py` applies those descriptions. Extend the description table for ordinary fields and keep lifecycle-specific behavior in a dedicated class.

Translation checks cover all eight languages and preserve format placeholders. `python -m tests.test_translation_parity --report` lists values identical to English; review product names, model numbers and established terms separately from untranslated prose.

## Keep changes understandable

- Keep HA-discovered platform modules at the integration root and feature code
  inside its domain package. Use [the architecture map](architecture.md#responsibilities)
  when choosing a home for new code.
- Use a class when it owns state or a lifecycle. Use typed functions/data models
  for validation and transformations. TypeScript is strict; Python typing is
  incremental, with dynamic data narrowed at storage and protocol boundaries.
- Name methods by their role. OCPP handlers in the adapter are `on_<ocpp_action>`.
  Owners that record a fact are `observe_<fact>`, for example
  `coordinator.ingest.observe_meter_values()` or `coordinator.observe_connected()`.
  Use cases that may await I/O are `async_<verb>`, and side-effect-free queries
  are properties. Call the owner that does the work (`coordinator.ingest`,
  `coordinator.sessions`) instead of adding forwarding methods to the coordinator.
- Explain **why** a non-obvious rule exists: the race it prevents, the unit or
  clock involved, the source of truth, or the failure it preserves. Do not narrate
  obvious assignments. Put broad workflows in docs and the local invariant next
  to the relevant code; avoid copying whole design documents into comments.
- Test observable behavior at the changed boundary. Comment-only changes need
  no new behavior tests; verify syntax/formatting, links and unchanged artifacts.
- Use Conventional Commits with a blank line and short bullets describing the
  change. Version numbers change at installable milestones, not for explanations.
- Keep wire evidence and firmware scope with the existing
  [reverse-engineering notes](../reverse_engineering/README.md). Mark hypotheses as
  hypotheses and redact identifiers/credentials from examples.

## Refactoring contracts

- Preserve existing behavior in structural refactorings. Identify behavior changes separately instead of silently including them in a cleanup.
- Keep entity unique IDs and existing entity-ID schemes, service names, config-entry keys, storage keys, persisted strings and translation keys byte-identical. Use the existing contract fixtures to check these boundaries.
- Before changing the write queue, Start/Stop, targets or OCPP handlers, read the [safety and compatibility invariants](invariants.md) and [automation resilience guide](automation-resilience.md). Keep the queue as the sole owner of outgoing charger writes.
- Use the [architecture map](architecture.md#responsibilities) to choose module owners. Keep domain imports acyclic and import the coordinator only for type checking where a capability protocol suffices.
- When moving a module, migrate its real callers and tests. Retain a thin re-export only while callers still need the old path; do not add tests whose sole purpose is keeping an unused shim alive.
- Preserve comments explaining races, firmware limits, clocks, uncertainty and rollback. Keep error-response and cancellation boundaries intact, including payload-free logging for RFID-sensitive handlers.
- Make each refactoring task an independently revertible commit. Run the [local checks](#local-checks), including both test suites, mypy, Ruff and the frontend build, before committing it. Capture characterization fixtures before an extraction and check observable behavior rather than copying the new implementation into tests.
- For frontend changes, include changed generated assets in the same commit as their sources. See the [build output list](../frontend/README.md#build-outputs-and-asset-provenance); do not edit bundles manually.
- Update the architecture, contributor guide or frontend guide in the same commit when module names or responsibilities change. Keep local work plans and review reports out of commits unless explicitly requested.

### Supported versions and deprecations

- **Home Assistant 2024.12.0** is the minimum, declared in `hacs.json`. The
  options flow relies on `OptionsFlow.config_entry`, which Home Assistant sets
  itself from that release on. Raise the minimum only in a release that needs a
  newer API, and update `hacs.json` and the installation guide together.
- **`ocpp>=2.0.0,<3`** in `manifest.json` and `tests/requirements-auth.txt`. A new
  major version of the library is adopted deliberately, not by an unattended
  upgrade.
- **`websockets>=13.1`** in `manifest.json`, the lowest version Home Assistant
  2024.12 allows. It has no upper bound so it cannot conflict with Home
  Assistant's own constraint. The server still uses the deprecated
  `websockets.legacy` API, which the CI matrix exercises up to the newest
  release.
- **Deprecations.** Entities, services, service fields and options are removed
  at the earliest one minor release after they were deprecated. The release
  that deprecates them says so in `CHANGELOG.md` and, where users must act,
  raises a repair issue. Stable identifiers are never reused for a different
  meaning.
- [`quality_scale.yaml`](../custom_components/growatt_thor/quality_scale.yaml)
  tracks the Home Assistant Integration Quality Scale rules. Update a rule's
  status in the change that affects it.

### Reading diagnostic logs

Log wording and logger names can change during structural work. Inbound OCPP handler failures now use `Error in <action> handler`; authorization and transaction failures retain payload-free logging. Configuration debug messages use coordinator attribute names and parsed values, for example `Config: max_current = 16.0`. External-meter polling logs come from `custom_components.growatt_thor.runtime.polling`. The routine `Session appended to CSV` success message was removed; delivery failures still report that the checkpoint is retained for retry. Check the current implementation when matching logs rather than treating those messages as a stable API.

## Where documentation belongs

Keep `README.md` and `CHANGELOG.md` at the repository root. User guides,
architecture, contribution guidance and plans belong in `docs/`. Directory
READMEs may describe their own frontend or reverse-engineering material.
HACS 2 displays the root README; a separate `info.md` is no longer needed
([HACS 2 release notes](https://github.com/hacs/integration/releases/tag/2.0.0)).

The [documentation overview](../README.md#documentation) links to the main guide for each
topic. Update that source and link to it from other entrypoints. Preserve public card setup
anchors in `README.md`; the frontend links users there. Keep historical captures
as evidence rather than rewriting them to look like current feature promises.

The user handbook has four chapters: installation, everyday charging, energy,
and sessions. Keep numbered screenshot explanations beside the relevant task
in those chapters. `screenshots.md` is an index of original images, while
`entities.md` holds the entity table and automation examples. Avoid a second
visual manual. The annotation generator writes images only; its geometry
manifest links each image to the chapter that owns its explanation.

### Regenerate simulator screenshots

The screenshot tools require Chrome, Playwright and Pillow. Start the preview server in a separate terminal:

```sh
python3 -m http.server 8362 --bind 127.0.0.1
```

Then regenerate the current card, all 29 simulator captures, the combined theme preview and the numbered handbook images:

```sh
npm run build
node frontend/scripts/capture-docs.cjs
python3 frontend/scripts/compose-theme-preview.py
python3 frontend/scripts/annotate-docs.py
```

Use `THOR_PLAYWRIGHT_PACKAGE` to point to a shared Playwright `package.json`, `THOR_PREVIEW_URL` for a different preview address, and `THOR_SCREENSHOT_DIR` for a staging directory. The capture script writes the screenshot manifest and updates the corresponding annotation geometry from the rendered UI. Move staged captures and both manifests together before generating the annotated images. Review the results after layout changes; historical Home Assistant settings captures require a separate capture workflow.

Python typing is checked with `python -m mypy`. The strict scope in `pyproject.toml` covers the whole integration package; dependency signatures are analyzed without reporting unrelated errors outside that scope. Missing Home Assistant imports are allowed at the framework boundary. Keep unknown wire/storage values at those boundaries and use typed models or capability protocols for internal state. The initial scope includes card projection consumers and `tests/typing/owner_contracts.py`, which checks the concrete coordinator against its capabilities. `tests/typing_stubs/homeassistant/helpers/update_coordinator.pyi` and the other focused stubs under `tests/typing_stubs/` describe the inherited HA/OCPP interfaces needed for these checks; they are never loaded by the integration. Keep that bridge checked as owners move. Config flows, config-entry runtime and entity coordinator generics are checked without requiring a running HA installation.

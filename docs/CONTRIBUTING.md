# Contributing to the THOR integration

[Project overview](../README.md) · [Documentation](../README.md#documentation)

## Start with one path through the code

The integration is the local OCPP server; the wallbox connects to it. Home
Assistant loads a **config entry** (one saved integration configuration), creates
one coordinator, starts the server and forwards setup to entity platforms.
An **entity** is HA's view/control of a value. The **coordinator** owns shared
observations and the command queue; it is not proof that a requested change
has happened on the device.

Read [architecture reference](architecture.md) for package responsibilities and invariants,
then follow one of these paths rather than reading the whole coordinator first:

| To understand…                 | Read in this order                                                                                                                                                                                                                                                                                       | Relevant tests                                                                                                     |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Setup and reload               | [`__init__.py`](../custom_components/growatt_thor/__init__.py) → [`runtime/ownership.py`](../custom_components/growatt_thor/runtime/ownership.py)                                                                                                                                                              | [`test_runtime_ownership.py`](../tests/test_runtime_ownership.py)                                                     |
| A Stop request                 | [`charging/commands.py`](../custom_components/growatt_thor/charging/commands.py) → `GrowattCoordinator.queue_write()` → [`runtime/write_queue.py`](../custom_components/growatt_thor/runtime/write_queue.py)                                                                                                   | [`test_charging_commands.py`](../tests/test_charging_commands.py), [`test_write_queue.py`](../tests/test_write_queue.py) |
| Native targets and schedules   | [`targets/model.py`](../custom_components/growatt_thor/targets/model.py) → [`targets/runtime.py`](../custom_components/growatt_thor/targets/runtime.py) → [`targets/runner.py`](../custom_components/growatt_thor/targets/runner.py)                                                                              | [`test_charging_target_services.py`](../tests/test_charging_target_services.py)                                       |
| Session completion and restart | [`sessions/runtime.py`](../custom_components/growatt_thor/sessions/runtime.py) → [`sessions/outbox.py`](../custom_components/growatt_thor/sessions/outbox.py) → [`sessions/csv.py`](../custom_components/growatt_thor/sessions/csv.py)                                                                            | [`test_session_outbox.py`](../tests/test_session_outbox.py), [`test_session_csv.py`](../tests/test_session_csv.py)       |
| Energy allocation              | [`energy/observations.py`](../custom_components/growatt_thor/energy/observations.py) → [`energy/session_accounting.py`](../custom_components/growatt_thor/energy/session_accounting.py) → [`energy/accounting.py`](../custom_components/growatt_thor/energy/accounting.py)                                        | [`test_site_accounting.py`](../tests/test_site_accounting.py)                                                         |
| Card data and rendering        | [`presentation/card_data.py`](../custom_components/growatt_thor/presentation/card_data.py) → [`frontend/src/shared/types.ts`](../frontend/src/shared/types.ts) → [`charger/card-view-model.ts`](../frontend/src/charger/card-view-model.ts) → [`charger/card.template.ts`](../frontend/src/charger/card.template.ts) | [`test_card_data.py`](../tests/test_card_data.py), [`card-view-model.test.ts`](../frontend/test/card-view-model.test.ts) |

### Example: a Stop is an intent, then a protocol result, then an observation

1. The button or optional stop guard calls `StopChargingCommand.async_request()`.
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

## Local checks

Run commands from the repository root. CI uses Python 3.12 and Node 22; the
frontend requires Node 22.18+ or Node 24+. These are development tools; the
installed integration ships its already-built card assets.

```sh
python3.12 -m venv .local/dev-venv
. .local/dev-venv/bin/activate
python -m pip install -r tests/requirements-auth.txt
python -m unittest discover -s tests -q
```

Despite its historical name, `requirements-auth.txt` supplies the OCPP and schema
dependencies used by several regression suites. Many tests load focused modules
with small HA fakes; they exercise contracts without launching Home Assistant.
Install the dependencies so those cases are not silently skipped. A targeted
backend run can use `python -m unittest discover -s tests -p 'test_session_outbox.py' -v`.

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

## Keep changes understandable

- Keep HA-discovered platform modules at the integration root and feature code
  inside its domain package. Use [the architecture map](architecture.md#responsibilities)
  when choosing a home for new code.
- Use a class when it owns state or a lifecycle. Use typed functions/data models
  for validation and transformations. TypeScript is strict; Python typing is
  incremental, with dynamic data narrowed at storage and protocol boundaries.
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

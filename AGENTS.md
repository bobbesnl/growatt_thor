# Repository guidance

- Use [CONTRIBUTING.md](docs/CONTRIBUTING.md) for the code map, local checks and documentation conventions.
- Follow the [refactoring contracts](docs/CONTRIBUTING.md#refactoring-contracts) for structural changes, atomic commits and generated assets.
- Before changing the write queue, Start/Stop, charging targets or OCPP handlers, read the [safety and compatibility invariants](docs/invariants.md) and [automation resilience guide](docs/automation-resilience.md). Keep those rules intact; the reasons are recorded in the [decision records](docs/adr/README.md).
- Preserve comments explaining races, firmware behavior, timing and rollback semantics when moving code.
- Keep local work plans and review reports out of commits unless the user explicitly asks to include them.

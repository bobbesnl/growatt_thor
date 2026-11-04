"""Import boundaries between the integration layers.

The rules describe the dependency direction documented in
``docs/architecture.md#layers-at-a-glance``. They were recorded from the
current import graph, so every rule passes today. The allowlists name the modules
that may cross a boundary; shrink them when code moves, and justify any addition
in the commit that adds it.

The check is static: it parses the source with ``ast`` and never imports the
integration, so it needs neither Home Assistant nor the OCPP library.
"""

from __future__ import annotations

import ast
import unittest
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from tests.support import PACKAGE_PATH


@dataclass(frozen=True)
class ImportEdge:
    """One import statement found in an integration module."""

    source: str
    target: str
    external: bool
    type_only: bool
    line: int

    def describe(self) -> str:
        kind = "type-only " if self.type_only else ""
        return f"{self.source}:{self.line} {kind}imports {self.target}"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE_PATH).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "__init__"


@cache
def _module_paths() -> dict[str, Path]:
    return {_module_name(path): path for path in sorted(PACKAGE_PATH.rglob("*.py"))}


def _resolve_internal(name: str) -> str:
    """Map ``package.module.attribute`` to the module that defines it."""
    modules = _module_paths()
    while name and name not in modules:
        name = name.rpartition(".")[0]
    return name or "__init__"


def _is_type_checking_guard(node: ast.If) -> bool:
    return "TYPE_CHECKING" in ast.unparse(node.test)


def _edges_for(module: str, path: Path) -> Iterator[ImportEdge]:
    is_package = path.name == "__init__.py"
    package = [] if module == "__init__" else module.split(".")
    if not is_package:
        package = package[:-1]

    def visit(nodes: Sequence[ast.AST], type_only: bool) -> Iterator[ImportEdge]:
        for node in nodes:
            if isinstance(node, ast.If) and _is_type_checking_guard(node):
                yield from visit(node.body, True)
                yield from visit(node.orelse, type_only)
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield ImportEdge(module, alias.name, True, type_only, node.lineno)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    yield ImportEdge(module, node.module or "", True, type_only, node.lineno)
                    continue
                base = package[: len(package) - (node.level - 1)]
                names = [node.module] if node.module else [alias.name for alias in node.names]
                for name in names:
                    target = _resolve_internal(".".join([*base, name]))
                    yield ImportEdge(module, target, False, type_only, node.lineno)
                continue
            # Function-level imports run when the function is called, so they
            # count as runtime imports just like module-level ones.
            yield from visit(
                [
                    child
                    for child in ast.iter_child_nodes(node)
                    if isinstance(child, ast.stmt | ast.excepthandler | ast.match_case)
                ],
                type_only,
            )

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    yield from visit(tree.body, False)


@cache
def _edges() -> tuple[ImportEdge, ...]:
    return tuple(
        edge for module, path in _module_paths().items() for edge in _edges_for(module, path)
    )


def _in(module: str, prefixes: frozenset[str]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


# Modules Home Assistant loads directly: the entry point, entity platforms and the
# shared entity base. Nothing below the HA adapter layer may depend on them.
PLATFORM_MODULES = frozenset(
    {
        "__init__",
        "button",
        "config_flow",
        "diagnostics",
        "entity",
        "number",
        "select",
        "sensor",
        "sensor_descriptions",
        "switch",
        "time",
    }
)

# Card projections are an output adapter. Only the sensor platform and entry
# setup (frontend registration) consume them.
PRESENTATION_CONSUMERS = frozenset({"__init__", "sensor"})

# Modules that may import Home Assistant at runtime. Everything else is
# HA-free and imports HA types only under TYPE_CHECKING.
HOMEASSISTANT_RUNTIME_IMPORTERS = frozenset(
    {
        *PLATFORM_MODULES,
        "charging.pv_service",
        "coordinator",
        "presentation.entity_map",
        "presentation.frontend",
        "runtime.action_errors",
        "runtime.service_setup",
        "runtime.session_history",
        "sessions.websocket",
        "targets.runtime",
        "targets.services",
    }
)

# Modules outside the OCPP adapter that use the ocpp library directly: status
# enums for configuration results and request payload classes for targets.
OCPP_LIBRARY_IMPORTERS = frozenset(
    {
        "charging.pv_apply",
        "configuration.controls",
        "configuration.writer",
        "number",
        "switch",
        "targets.charger_ops",
        "targets.wire",
        "time",
    }
)

# Long-lived owners of mutable state. Domain modules receive capabilities from
# them instead of importing them.
OWNER_MODULES = frozenset(
    {
        "charging.commands",
        "coordinator",
        "energy.stop_guard",
        "runtime.charger_write_queue",
        "sessions.runtime",
        "targets.runtime",
    }
)
OWNER_IMPORTERS = frozenset(
    {
        "__init__",
        "button",
        "charging.growatt_charger",
        "coordinator",
        "targets.services",
    }
)


class LayerBoundaryTest(unittest.TestCase):
    """Keep the documented dependency direction between layers."""

    def assert_no_edges(self, edges: list[ImportEdge], reason: str) -> None:
        self.assertEqual([], [edge.describe() for edge in edges], reason)

    def test_platform_modules_are_imported_only_by_platform_modules(self) -> None:
        self.assert_no_edges(
            [
                edge
                for edge in _edges()
                if not edge.external
                and edge.target in PLATFORM_MODULES
                and edge.source not in PLATFORM_MODULES
            ],
            "Domain, runtime and OCPP code must not depend on HA entity platforms.",
        )

    def test_presentation_is_consumed_only_by_its_ha_adapters(self) -> None:
        self.assert_no_edges(
            [
                edge
                for edge in _edges()
                if not edge.external
                and _in(edge.target, frozenset({"presentation"}))
                and not _in(edge.source, frozenset({"presentation"}))
                and edge.source not in PRESENTATION_CONSUMERS
            ],
            "Card projections are output adapters; commands and domain rules must not read them.",
        )

    def test_coordinator_is_imported_at_runtime_only_by_entry_setup(self) -> None:
        self.assert_no_edges(
            [
                edge
                for edge in _edges()
                if not edge.external
                and edge.target == "coordinator"
                and not edge.type_only
                and edge.source != "__init__"
            ],
            "Import the coordinator under TYPE_CHECKING or depend on a capability protocol.",
        )

    def test_homeassistant_runtime_imports_stay_in_adapters(self) -> None:
        self.assert_no_edges(
            [
                edge
                for edge in _edges()
                if edge.external
                and edge.target.partition(".")[0] == "homeassistant"
                and not edge.type_only
                and edge.source not in HOMEASSISTANT_RUNTIME_IMPORTERS
            ],
            "Keep domain modules HA-free; import HA types under TYPE_CHECKING.",
        )

    def test_ocpp_library_imports_stay_in_the_adapter(self) -> None:
        self.assert_no_edges(
            [
                edge
                for edge in _edges()
                if edge.external
                and edge.target.partition(".")[0] in {"ocpp", "websockets"}
                and not edge.type_only
                and not _in(edge.source, frozenset({"ocpp"}))
                and edge.source not in OCPP_LIBRARY_IMPORTERS
            ],
            "Use the OCPP adapter instead of the ocpp/websockets libraries.",
        )

    def test_owner_modules_are_imported_only_by_composition_points(self) -> None:
        self.assert_no_edges(
            [
                edge
                for edge in _edges()
                if not edge.external
                and edge.target in OWNER_MODULES
                and not edge.type_only
                and edge.source != edge.target
                and edge.source not in OWNER_IMPORTERS
            ],
            "Pass owner capabilities in instead of importing runtime owners.",
        )

    def test_runtime_import_graph_is_acyclic(self) -> None:
        graph: dict[str, set[str]] = {module: set() for module in _module_paths()}
        for edge in _edges():
            if not edge.external and not edge.type_only and edge.source != edge.target:
                graph[edge.source].add(edge.target)

        cycles: list[list[str]] = []
        state: dict[str, int] = {}
        stack: list[str] = []

        def walk(module: str) -> None:
            state[module] = 1
            stack.append(module)
            for target in sorted(graph[module]):
                if state.get(target) == 1:
                    cycles.append([*stack[stack.index(target) :], target])
                elif target not in state:
                    walk(target)
            stack.pop()
            state[module] = 2

        for module in sorted(graph):
            if module not in state:
                walk(module)
        self.assertEqual([], [" -> ".join(cycle) for cycle in cycles])

    def test_stop_guard_does_not_load_projections_or_accounting(self) -> None:
        # Invariant: the automatic guard reads shared observations and calls
        # the Stop command; it imports neither the dashboard projection nor the
        # accounting runtime (docs/invariants.md#automatic-stop-and-targets).
        forbidden = frozenset(
            {
                "presentation",
                "sessions",
                "energy.allocation",
                "energy.live_allocation",
                "energy.session_accumulator",
            }
        )
        runtime_targets: dict[str, set[str]] = {}
        for edge in _edges():
            if not edge.external and not edge.type_only:
                runtime_targets.setdefault(edge.source, set()).add(edge.target)

        reached: set[str] = set()
        pending = ["energy.stop_guard"]
        while pending:
            for target in runtime_targets.get(pending.pop(), set()):
                if target not in reached:
                    reached.add(target)
                    pending.append(target)
        self.assertEqual([], sorted(module for module in reached if _in(module, forbidden)))

    def test_allowlists_name_existing_modules(self) -> None:
        modules = set(_module_paths())
        for allowlist in (
            PLATFORM_MODULES,
            PRESENTATION_CONSUMERS,
            HOMEASSISTANT_RUNTIME_IMPORTERS,
            OCPP_LIBRARY_IMPORTERS,
            OWNER_MODULES,
            OWNER_IMPORTERS,
        ):
            self.assertEqual(set(), allowlist - modules)

    def test_checker_sees_type_only_and_function_level_imports(self) -> None:
        # Guards the parser itself: these imports exist today and must be found.
        edges = _edges()
        self.assertIn(
            ("ocpp.growatt.server", "coordinator", True),
            {(edge.source, edge.target, edge.type_only) for edge in edges},
        )
        self.assertIn(
            ("runtime.coordinator_storage", "energy.stop_guard_policy", False),
            {(edge.source, edge.target, edge.type_only) for edge in edges},
        )


if __name__ == "__main__":
    unittest.main()

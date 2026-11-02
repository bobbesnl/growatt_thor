"""Report files and functions that exceed the size budgets in pyproject.toml.

Budgets are warnings by default: the script lists every overrun and exits 0.
Pass ``--strict`` to exit 1 when a budget is exceeded. On GitHub Actions the
overruns are also written as warning annotations and as a job summary table.

Python files are measured by lines and functions by their span including
decorators. TypeScript files are measured by lines only.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Overrun:
    path: str
    line: int
    name: str
    size: int
    budget: int

    @property
    def kind(self) -> str:
        return "file" if self.name == "" else "function"


def _load_budgets() -> dict[str, Any]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    budgets: dict[str, Any] = pyproject["tool"]["growatt_thor"]["size_budgets"]
    return budgets


def _files(directories: list[str], suffix: str) -> list[Path]:
    return sorted(path for directory in directories for path in (ROOT / directory).rglob(suffix))


def _file_overrun(path: Path, text: str, budget: int) -> list[Overrun]:
    lines = len(text.splitlines())
    if lines <= budget:
        return []
    return [Overrun(str(path.relative_to(ROOT)), 1, "", lines, budget)]


def _function_overruns(path: Path, text: str, budget: int) -> list[Overrun]:
    overruns = []
    for node in ast.walk(ast.parse(text, filename=str(path))):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
        lines = (node.end_lineno or node.lineno) - start + 1
        if lines > budget:
            overruns.append(
                Overrun(str(path.relative_to(ROOT)), node.lineno, node.name, lines, budget)
            )
    return overruns


def collect() -> list[Overrun]:
    budgets = _load_budgets()
    file_budget = int(budgets["max_file_lines"])
    function_budget = int(budgets["max_function_lines"])
    overruns: list[Overrun] = []
    for path in _files(budgets["python"], "*.py"):
        text = path.read_text(encoding="utf-8")
        overruns += _file_overrun(path, text, file_budget)
        overruns += _function_overruns(path, text, function_budget)
    for path in _files(budgets["typescript"], "*.ts"):
        overruns += _file_overrun(path, path.read_text(encoding="utf-8"), file_budget)
    return sorted(overruns, key=lambda item: (item.kind, -item.size, item.path, item.line))


def _describe(overrun: Overrun) -> str:
    subject = overrun.path if overrun.kind == "file" else f"{overrun.name}()"
    return f"{subject} has {overrun.size} lines (budget {overrun.budget})"


def _write_github_output(overruns: list[Overrun]) -> None:
    for overrun in overruns:
        print(
            f"::warning file={overrun.path},line={overrun.line},title=Size budget::"
            f"{_describe(overrun)}"
        )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    rows = [
        f"| {overrun.kind} | `{overrun.path}:{overrun.line}` | {overrun.name or '-'} "
        f"| {overrun.size} | {overrun.budget} |"
        for overrun in overruns
    ]
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write(f"### Size budgets: {len(overruns)} over budget\n\n")
        if rows:
            handle.write("| Kind | Location | Function | Lines | Budget |\n")
            handle.write("| --- | --- | --- | ---: | ---: |\n")
            handle.write("\n".join(rows) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report size budget overruns.")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a budget is exceeded")
    args = parser.parse_args()

    overruns = collect()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        _write_github_output(overruns)
    else:
        for overrun in overruns:
            print(f"{overrun.path}:{overrun.line}: {_describe(overrun)}")
    files = sum(overrun.kind == "file" for overrun in overruns)
    print(
        f"Size budgets: {files} files and {len(overruns) - files} functions over budget"
        + ("" if args.strict else " (warning only)")
    )
    return 1 if args.strict and overruns else 0


if __name__ == "__main__":
    sys.exit(main())

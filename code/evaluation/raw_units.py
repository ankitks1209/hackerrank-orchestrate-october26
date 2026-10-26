"""Text units of the raw evidence files for the label-free verifier (check P2).

A unit is the smallest piece of a file that can state something about a resource: one SQL
row, the innermost JSON object that holds a resource id, or the log lines that share a
trace token with the line naming the resource. Units are cut with the stdlib only
(`sqlite3`, `json`, `re`); nothing here imports `ghostaudit`, so the verifier shares no parser
code with the solver. Images and PDFs have no text and yield no units.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Tuple

from evaluation.raw_dataset import RESOURCE_ID_PATTERN, TIME_FORMAT

SQL_SUFFIX = ".sql"
JSON_SUFFIX = ".json"
TEXT_SUFFIXES = (".log", ".txt")
TRACE_TOKEN = re.compile(r"\b(?:tr|rb)-[A-Za-z0-9-]+")
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
ENCODING = "utf-8"
SCOPE_GROUP = "scope"


@dataclass(frozen=True)
class Unit:
    """One piece of a file: where it is, its lower-cased text, the ids it names and its first time."""

    locator: str
    group: str
    text: str
    ids: FrozenSet[str]
    time: Optional[int]


def _epoch(stamp: str) -> int:
    return int(datetime.strptime(stamp, TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp())


def _unit(locator: str, group: str, text: str) -> Unit:
    stamps = [_epoch(stamp) for stamp in TIMESTAMP.findall(text)]
    return Unit(locator, group, text.lower(), frozenset(RESOURCE_ID_PATTERN.findall(text)),
                min(stamps) if stamps else None)


def file_units(path: Path) -> Tuple[Unit, ...]:
    """Units of one evidence file, in file order; empty for binary media or unreadable text."""
    suffix = path.suffix.lower()
    try:
        if suffix == SQL_SUFFIX:
            return _sql_units(path.read_text(encoding=ENCODING))
        if suffix == JSON_SUFFIX:
            return _json_units(json.loads(path.read_text(encoding=ENCODING)))
        if suffix in TEXT_SUFFIXES:
            return _line_units(path.read_text(encoding=ENCODING))
    except (OSError, ValueError, sqlite3.Error):
        return ()
    return ()


def _sql_units(script: str) -> Tuple[Unit, ...]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(script)
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        units: List[Unit] = []
        for table in tables:
            units.append(_unit("table:" + table, table, table))
            for number, row in enumerate(connection.execute('SELECT * FROM "%s"' % table), start=1):
                units.append(_unit("%s#%d" % (table, number), table, " ".join(str(v) for v in row)))
        return tuple(units)
    finally:
        connection.close()


def _walk(node: Any, path: str) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Innermost dicts with a direct string value that is a resource id, with their JSON path."""
    if isinstance(node, dict):
        direct = [v for v in node.values() if isinstance(v, str) and RESOURCE_ID_PATTERN.fullmatch(v)]
        if direct:
            yield path, node
        for key, value in node.items():
            yield from _walk(value, "%s.%s" % (path, key) if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, "%s[%d]" % (path, index))


def _scopes(node: Any, path: str) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Snapshot headers: dicts that name a `data_store`, without their records."""
    if isinstance(node, dict):
        if "data_store" in node:
            yield path, {key: value for key, value in node.items() if key != "records"}
        for key, value in node.items():
            yield from _scopes(value, "%s.%s" % (path, key) if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _scopes(value, "%s[%d]" % (path, index))


def _json_units(document: Any) -> Tuple[Unit, ...]:
    units = []
    for path, node in _walk(document, ""):
        group = path.split("[", 1)[0].split(".")[-1] if "[" in path else path
        units.append(_unit(path, group, json.dumps(node, sort_keys=True)))
    units += [_unit(path, SCOPE_GROUP, json.dumps(node, sort_keys=True)) for path, node in _scopes(document, "")]
    return tuple(units)


def _line_units(text: str) -> Tuple[Unit, ...]:
    lines = [(number, line) for number, line in enumerate(text.splitlines(), start=1) if line.strip()]
    by_trace: Dict[str, List[str]] = {}
    for _number, line in lines:
        for trace in set(TRACE_TOKEN.findall(line)):
            by_trace.setdefault(trace, []).append(line)
    units = []
    for number, line in lines:
        traces = sorted(set(TRACE_TOKEN.findall(line)))
        joined = [line] + [other for trace in traces for other in by_trace[trace] if other is not line]
        unit = _unit("L%d" % number, "line", "\n".join(joined))
        units.append(Unit(unit.locator, unit.group, unit.text, frozenset(RESOURCE_ID_PATTERN.findall(line)),
                          min((_epoch(s) for s in TIMESTAMP.findall(line)), default=None)))
    return tuple(units)

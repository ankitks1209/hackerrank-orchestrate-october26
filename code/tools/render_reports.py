"""Fill and check report numbers from scorer and meter JSON (SPEC A5).

Numbers are never typed by hand. A metrics directory holds the JSON of one release run:

    scorer.json        `python3 -m evaluation score --json` output (SPEC A2)
    meter.json         `ghostaudit.llm.usage.snapshot` of the final full-dataset run
    custom_cases.json  list of {"id", "title", "rationale", "input", "expected", "actual"}
    strategies.md      `python3 -m evaluation score --strategies` output (S0, S1, S2 compared)
    ablation.md        `python3 -m evaluation score --ablate --agent-ablation` output (flag variants, ledger, agent off and on)

Fill:  python3 -m tools.render_reports --metrics-dir DIR           rewrites the marked blocks in place
Check: python3 -m tools.render_reports --metrics-dir DIR --check    exits 1 on any drift or failed check

Marked blocks read `<!-- BEGIN:name -->` ... `<!-- END -->`. The checks are: scorer normalization
and composite; usage totals and per-model tallies; cost = tokens x prices; per-request averages =
total / EVAL_REQUEST_COUNT; README test count = discovered unittest count; every custom case
reproduces its expected output and there are at least MIN_CUSTOM_CASES; and the required terms
of each report.
"""
from __future__ import annotations

import argparse
import difflib
import json
import logging
import re
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from evaluation.scoring import GRADERS, TAXONOMY
from ghostaudit.config import (
    COMPOSITE_WEIGHTS,
    COST_TOLERANCE_USD,
    EVAL_REQUEST_COUNT,
    LIVE_SDK_REQUIREMENT,
    LLM_PROVIDER,
    MIN_CUSTOM_CASES,
    RATIO_TOLERANCE,
    ModelPrice,
)
from ghostaudit.llm.usage import TALLY_FIELDS, TokenTally, tally_cost

LOG = logging.getLogger("ghostaudit.reports")
CODE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_DIR.parent
TESTS_DIR = CODE_DIR / "tests"
EVAL_DIR = CODE_DIR / "evaluation"
README = REPO_ROOT / "README.md"
EVAL_REPORT = EVAL_DIR / "evaluation_report.md"
USAGE_REPORT = EVAL_DIR / "usage_report.md"
SCORER_FILE = "scorer.json"
METER_FILE = "meter.json"
CUSTOM_FILE = "custom_cases.json"
TEXT_FILES = {"strategies": "strategies.md", "ablation": "ablation.md"}
TEST_COMMAND = "python3 -m unittest discover -s code/tests -t code"
EXIT_OK = 0
EXIT_CHECK = 1
EXIT_INPUT = 2
SCORE_FORMAT = "%.4f"
CEILING_FORMAT = "%.3f"
TOKENS_FORMAT = "%.1f"
USD_FORMAT = "$%.4f"
USD_PER_REQUEST_FORMAT = "$%.6f"  # per-request costs are often below a cent
FENCE_MIN = 3
BLOCK_PATTERN = re.compile(r"<!-- BEGIN:(?P<name>[a-z-]+) -->\n.*?<!-- END -->\n", re.DOTALL)
BACKTICK_RUN = re.compile(r"`+")
BUCKETS = (
    ("replayed", "Model usage behind the final output.csv (replayed from the response cache)"),
    ("live", "New API spend of the final run (live calls)"),
)
USAGE_HEADER = ("Model", "Calls", "Input tokens", "Cache write", "Cache read", "Output tokens",
                "Total tokens", "Cost (sync)", "Cost (batch)")
CUSTOM_FIELDS = (("Input", "input"), ("Expected output", "expected"), ("Actual output", "actual"))
EVAL_TERMS = ("case-level", "row-level", "step-level", "field-level", "sequence accuracy",
              "strategies", "failures", "improvements")
USAGE_TERMS = ("provider", "calls", "input", "output", "per request", "overall")


class ReportError(ValueError):
    """A report file does not have the marked-block structure the metrics need."""


@dataclass(frozen=True)
class Sources:
    """The JSON inputs of one release run plus the discovered unittest count."""

    scorer: Mapping[str, Any]
    meter: Mapping[str, Any]
    custom_cases: Sequence[Mapping[str, str]]
    test_count: int
    texts: Mapping[str, str] = field(default_factory=dict)  # Markdown produced by the scorer CLI


@dataclass(frozen=True)
class Target:
    """A report file, the marked blocks it carries and the terms it must contain."""

    path: Path
    blocks: Tuple[str, ...]
    terms: Tuple[str, ...] = ()


TARGETS: Tuple[Target, ...] = (
    Target(README, ("results", "tests")),
    Target(EVAL_REPORT, ("metrics", "strategies", "ablation", "custom-cases"), EVAL_TERMS),
    Target(USAGE_REPORT, ("usage",), USAGE_TERMS),
)


def _block(lines: Sequence[str]) -> str:
    return "\n".join(lines) + "\n"


def _usd(value: Optional[float], fmt: str = USD_FORMAT) -> str:
    return "unpriced" if value is None else fmt % value


def _score(value: float) -> str:
    return SCORE_FORMAT % value


def _listed(ids: Sequence[str]) -> str:
    return ", ".join(ids) or "none"


def _tally(fields: Mapping[str, int]) -> TokenTally:
    return TokenTally(**{name: fields[name] for name in TALLY_FIELDS})


def _close(stored: Optional[float], expected: Optional[float], tolerance: float) -> bool:
    if stored is None or expected is None:
        return stored is expected
    return abs(stored - expected) <= tolerance


def _divided(value: Optional[float], divisor: int) -> Optional[float]:
    return None if value is None else value / divisor


def metrics_block(sources: Sources) -> str:
    """Grader table, details and error taxonomy of the scorer run."""
    scorer = sources.scorer
    lines = ["### Grader emulation (%d cases)" % scorer["cases"], "",
             "| Grader | Name | Score | Ceiling | Normalized |", "|---|---|---|---|---|"]
    for grader, name in GRADERS:
        lines.append("| %s | %s | %s | %s | %s |" % (
            grader, name, _score(scorer["raw"][grader]),
            CEILING_FORMAT % scorer["ceilings"][grader], _score(scorer["normalized"][grader])))
    lines += ["", "### Details", "", "| Metric | Value |", "|---|---|"]
    lines += ["| %s | %s |" % (name, _score(value))
              for name, value in sorted(scorer["details"].items())]
    lines += ["", "### Error taxonomy", "", "| Category | Count |", "|---|---|"]
    lines += ["| %s | %d |" % (name, scorer["taxonomy"][name]) for name in TAXONOMY]
    lines += ["", "- Status mismatches: %s" % _listed(scorer["status_mismatches"]),
              "- Not row-exact: %s" % _listed(scorer["inexact_cases"])]
    return _block(lines)


def strategies_block(sources: Sources) -> str:
    """The S0, S1, S2 comparison exactly as the scorer CLI printed it."""
    return _block([sources.texts["strategies"].strip("\n")])


def ablation_block(sources: Sources) -> str:
    """The flag and window variants and the assumption ledger exactly as the scorer CLI printed them."""
    return _block([sources.texts["ablation"].strip("\n")])


def results_block(sources: Sources) -> str:
    """README results table: sample scores and the cost of the final full-dataset run."""
    scorer, meter = sources.scorer, sources.meter
    overall = meter["overall"]
    lines = ["| Measure | Value |", "|---|---|",
             "| Sample status accuracy, G1 (%d cases) | %s |" % (
                 scorer["cases"], _score(scorer["raw"]["G1"])),
             "| Sample step F1, G3 | %s |" % _score(scorer["raw"]["G3"]),
             "| Sample sequence LCS ratio, G6 | %s |" % _score(scorer["raw"]["G6"]),
             "| Sample exact sequence order | %s |" % _score(scorer["details"]["exact_order"]),
             "| Final run: requests | %d |" % meter["requests"],
             "| Final run: model tokens behind the output (replayed) | %d |" % overall["replayed"]["total_tokens"],
             "| Final run: cost of those tokens, sync | %s |" % _usd(overall["replayed"]["cost_sync"]),
             "| Final run: new API spend (live) | %s |" % _usd(overall["live"]["cost_sync"])]
    return _block(lines)


def tests_block(sources: Sources) -> str:
    """The README test count, from the discovered unittest suite."""
    return _block(["Unit tests: %d (`%s`)." % (sources.test_count, TEST_COMMAND)])


def _longest_backtick_run(text: str) -> int:
    return max((len(run) for run in BACKTICK_RUN.findall(text)), default=0)


def _fenced(text: str) -> str:
    """A fenced code block whose fence is longer than any backtick run inside `text`."""
    fence = "`" * max(FENCE_MIN, _longest_backtick_run(text) + 1)
    return "%stext\n%s\n%s" % (fence, text.rstrip("\n"), fence)


def _custom_section(case: Mapping[str, str]) -> str:
    parts = ["### %s: %s\n\n%s" % (case["id"], case["title"], case["rationale"])]
    parts += ["**%s**\n\n%s" % (label, _fenced(case[key])) for label, key in CUSTOM_FIELDS]
    return "\n\n".join(parts)


def custom_block(sources: Sources) -> str:
    """Each custom case as rationale, input, expected output and actual output."""
    cases = sorted(sources.custom_cases, key=lambda item: item["id"])
    return "\n\n".join(_custom_section(case) for case in cases) + "\n"


def _usage_row(label: str, bucket: Mapping[str, Any]) -> str:
    cells = [label, str(bucket["calls"]), str(bucket["input_tokens"]), str(bucket["cache_creation_tokens"]),
             str(bucket["cache_read_tokens"]), str(bucket["output_tokens"]), str(bucket["total_tokens"]),
             _usd(bucket["cost_sync"]), _usd(bucket["cost_batch"])]
    return "| " + " | ".join(cells) + " |"


def _summary_lines(meter: Mapping[str, Any]) -> List[str]:
    """The two facts a reader looks for first: what the final run spent, and what the cache fill billed."""
    overall, requests = meter["overall"], meter["requests"]
    live, replayed = overall["live"], overall["replayed"]
    final = ("The final run made %d live API call(s) and used %d live tokens (%s)."
             % (live["calls"], live["total_tokens"], _usd(live["cost_sync"])))
    fill = ("The live run that filled the cache billed %d calls and %d tokens (%d input, %d cache write, "
            "%d cache read, %d output), %s at synchronous prices or %s at batch prices; that is %s tokens and "
            "%s per request over %d requests."
            % (replayed["calls"], replayed["total_tokens"], replayed["input_tokens"],
               replayed["cache_creation_tokens"], replayed["cache_read_tokens"], replayed["output_tokens"],
               _usd(replayed["cost_sync"]), _usd(replayed["cost_batch"]),
               TOKENS_FORMAT % replayed["tokens_per_request"],
               _usd(replayed["cost_per_request"], USD_PER_REQUEST_FORMAT), requests))
    return ["- %s" % final, "- %s" % fill, ""]


def usage_block(sources: Sources) -> str:
    """Per-model and overall tables of replayed and live usage, plus the per-request averages."""
    meter = sources.meter
    overall = meter["overall"]
    lines = ["Provider: %s Messages API, Python SDK `%s` for live calls. Models: %s." % (
        LLM_PROVIDER, LIVE_SDK_REQUIREMENT, ", ".join(sorted(meter["models"]))), "",
        "The final run (`--llm cache`, the default) replays model responses stored in "
        "`code/ghostaudit/cache/`. Replayed usage is the usage recorded when those responses were "
        "produced, so it is what a run from an empty cache spends again. Live usage is what the "
        "final run itself spent on the API: it is zero while every response is cached. The stored media "
        "replies are redacted copies of the original model output (emails and phones as sha256 digests, "
        "names removed, original text not retained; DECISIONS D25); the token counts are those of the "
        "original calls.", ""]
    lines += _summary_lines(meter)
    for kind, title in BUCKETS:
        lines += ["### %s" % title, "", "| " + " | ".join(USAGE_HEADER) + " |",
                  "|" + "---|" * len(USAGE_HEADER)]
        lines += [_usage_row(model, meter["models"][model][kind]) for model in sorted(meter["models"])]
        lines += [_usage_row("**overall**", overall[kind]), ""]
    lines += ["### Per request", "",
              "| Basis | Requests | Tokens per request | Cost per request (sync) |", "|---|---|---|---|"]
    lines += ["| %s | %d | %s | %s |" % (kind, meter["requests"],
                                         TOKENS_FORMAT % overall[kind]["tokens_per_request"],
                                         _usd(overall[kind]["cost_per_request"], USD_PER_REQUEST_FORMAT))
              for kind, _title in BUCKETS]
    return _block(lines)


BLOCKS: Mapping[str, Callable[[Sources], str]] = {
    "results": results_block,
    "tests": tests_block,
    "metrics": metrics_block,
    "strategies": strategies_block,
    "ablation": ablation_block,
    "custom-cases": custom_block,
    "usage": usage_block,
}


def fill_blocks(text: str, blocks: Mapping[str, str], path: Path) -> str:
    """Replace the body of every marked block; the document's markers must match `blocks`."""
    found: List[str] = []

    def replace(match: re.Match) -> str:
        name = match.group("name")
        if name not in blocks:
            raise ReportError("%s: unexpected marked block %r" % (path, name))
        found.append(name)
        return "<!-- BEGIN:%s -->\n%s<!-- END -->\n" % (name, blocks[name])

    filled = BLOCK_PATTERN.sub(replace, text)
    absent = sorted(set(blocks) - set(found))
    if absent:
        raise ReportError("%s: no marked block for %s" % (path, ", ".join(absent)))
    return filled


def scorer_problems(scorer: Mapping[str, Any]) -> List[str]:
    """Scores lie in [0, 1], normalized = raw / ceiling and G7 is the weighted composite."""
    raw, normalized, ceilings = scorer["raw"], scorer["normalized"], scorer["ceilings"]
    problems: List[str] = []
    for grader, _ in GRADERS:
        if not 0.0 <= raw[grader] <= 1.0:
            problems.append("%s: score %s is outside [0, 1]" % (grader, raw[grader]))
        if not _close(normalized[grader], raw[grader] / ceilings[grader], RATIO_TOLERANCE):
            problems.append("%s: normalized score is not raw / ceiling" % grader)
    composite = sum(weight * raw[grader] for grader, weight in COMPOSITE_WEIGHTS.items())
    if not _close(raw["G7"], composite, RATIO_TOLERANCE):
        problems.append("G7: composite differs from the weighted sum of its graders")
    return problems


def _bucket_problems(label: str, bucket: Mapping[str, Any], requests: int) -> List[str]:
    """One bucket: total tokens sum its tally and the per-request averages divide by `requests`."""
    tally = _tally(bucket)
    problems: List[str] = []
    if bucket["total_tokens"] != tally.total_tokens:
        problems.append("%s: total tokens %s differ from the tallies (%d)"
                        % (label, bucket["total_tokens"], tally.total_tokens))
    if not _close(bucket["tokens_per_request"], tally.total_tokens / requests, RATIO_TOLERANCE):
        problems.append("%s: tokens per request is not total / %d" % (label, requests))
    if not _close(bucket["cost_per_request"], _divided(bucket["cost_sync"], requests), COST_TOLERANCE_USD):
        problems.append("%s: cost per request is not sync cost / %d" % (label, requests))
    return problems


def _cost_problems(label: str, bucket: Mapping[str, Any], price: Optional[Mapping[str, Any]]) -> List[str]:
    """A model's stored costs equal its tokens x prices; an unpriced model has no cost."""
    tally = _tally(bucket)
    expected_sync: Optional[float] = None
    expected_batch: Optional[float] = None
    if price is not None:
        expected_sync = tally_cost(tally, ModelPrice(**price))
        expected_batch = tally_cost(tally, ModelPrice(**price), batch=True)
    return ["%s: stored %s %s differs from tokens x prices %s" % (label, key, bucket[key], expected)
            for key, expected in (("cost_sync", expected_sync), ("cost_batch", expected_batch))
            if not _close(bucket[key], expected, COST_TOLERANCE_USD)]


def _overall_problems(meter: Mapping[str, Any], kind: str) -> List[str]:
    """The overall bucket of `kind` equals the sum of the models' buckets (tallies and costs)."""
    overall = meter["overall"][kind]
    entries = [meter["models"][model][kind] for model in sorted(meter["models"])]
    total = TokenTally()
    for entry in entries:
        total.merge(_tally(entry))
    problems: List[str] = []
    if _tally(overall) != total:
        problems.append("overall %s tallies differ from the sum of the models" % kind)
    for key in ("cost_sync", "cost_batch"):
        costs = [entry[key] for entry in entries]
        expected = None if None in costs else sum(costs)
        if not _close(overall[key], expected, COST_TOLERANCE_USD):
            problems.append("overall %s %s differs from the sum of the models" % (kind, key))
    return problems


def meter_problems(meter: Mapping[str, Any], requests: int) -> List[str]:
    """Usage covers `requests` cases, records model calls, sums per bucket and equals tokens x prices."""
    problems: List[str] = []
    if meter["requests"] != requests:
        problems.append("usage run covers %d requests, expected %d" % (meter["requests"], requests))
    if sum(meter["overall"][kind]["calls"] for kind, _title in BUCKETS) == 0:
        problems.append("the meter records no model call, so the usage report would show zero usage")
    for kind, _title in BUCKETS:
        for model in sorted(meter["models"]):
            entry = meter["models"][model]
            label = "%s %s" % (model, kind)
            problems += _bucket_problems(label, entry[kind], meter["requests"])
            problems += _cost_problems(label, entry[kind], entry["price"])
        problems += _bucket_problems("overall %s" % kind, meter["overall"][kind], meter["requests"])
        problems += _overall_problems(meter, kind)
    return problems


def custom_problems(cases: Sequence[Mapping[str, str]]) -> List[str]:
    """At least MIN_CUSTOM_CASES custom cases, each reproducing its expected output."""
    problems: List[str] = []
    if len(cases) < MIN_CUSTOM_CASES:
        problems.append("%d custom cases, at least %d required" % (len(cases), MIN_CUSTOM_CASES))
    for case in cases:
        if case["actual"] != case["expected"]:
            problems.append("custom case %s: actual output differs from expected" % case["id"])
    return problems


def arithmetic_problems(sources: Sources, requests: int) -> List[str]:
    """Every consistency check that does not depend on the report text."""
    return (scorer_problems(sources.scorer) + meter_problems(sources.meter, requests)
            + custom_problems(sources.custom_cases))


def term_problems(text: str, target: Target) -> List[str]:
    """Required terms missing from a filled report (case-insensitive)."""
    lowered = text.lower()
    return ["%s: required term missing: %s" % (target.path.name, term)
            for term in target.terms if term.lower() not in lowered]


def build(sources: Sources, targets: Sequence[Target], requests: int
          ) -> Tuple[List[str], Dict[Path, Tuple[str, str]]]:
    """Problems found, and {path: (current text, filled text)} for every target."""
    problems = arithmetic_problems(sources, requests)
    texts: Dict[Path, Tuple[str, str]] = {}
    for target in targets:
        current = _read(target.path)
        blocks = {name: BLOCKS[name](sources) for name in target.blocks}
        filled = fill_blocks(current, blocks, target.path)
        problems += term_problems(filled, target)
        texts[target.path] = (current, filled)
    return problems, texts


def count_tests(tests_dir: Path = TESTS_DIR) -> int:
    """Number of unittest cases discovered under `tests_dir` (the README test count)."""
    suite = unittest.defaultTestLoader.discover(str(tests_dir), top_level_dir=str(CODE_DIR))
    return suite.countTestCases()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _load_json(path: Path) -> Any:
    return json.loads(_read(path))


def load_sources(metrics_dir: Path, test_count: int) -> Sources:
    """Read the JSON and Markdown inputs from `metrics_dir`."""
    return Sources(
        scorer=_load_json(metrics_dir / SCORER_FILE),
        meter=_load_json(metrics_dir / METER_FILE),
        custom_cases=_load_json(metrics_dir / CUSTOM_FILE),
        test_count=test_count,
        texts={name: _read(metrics_dir / file) for name, file in TEXT_FILES.items()},
    )


def _report_drift(texts: Mapping[Path, Tuple[str, str]], drifted: Sequence[Path]) -> int:
    for path in drifted:
        current, filled = texts[path]
        sys.stdout.write("".join(difflib.unified_diff(
            current.splitlines(True), filled.splitlines(True),
            fromfile=str(path), tofile=str(path) + " (from metrics)")))
        LOG.error("%s: marked blocks differ from the metrics; run without --check to fill", path)
    if drifted:
        return EXIT_CHECK
    sys.stdout.write("reports match the metrics and every check passes\n")
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--metrics-dir", type=Path, required=True,
                        help="directory holding %s, %s, %s and %s"
                        % (SCORER_FILE, METER_FILE, CUSTOM_FILE, ", ".join(sorted(TEXT_FILES.values()))))
    parser.add_argument("--check", action="store_true",
                        help="verify only: exit 1 on drift or a failed check, write nothing")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        sources = load_sources(args.metrics_dir, count_tests())
        problems, texts = build(sources, TARGETS, EVAL_REQUEST_COUNT)
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError) as error:
        LOG.error("cannot render reports: %s", error)
        return EXIT_INPUT
    if problems:
        for problem in problems:
            LOG.error(problem)
        return EXIT_CHECK
    drifted = [path for path, (current, filled) in texts.items() if current != filled]
    if args.check:
        return _report_drift(texts, drifted)
    for path in drifted:
        _write(path, texts[path][1])
    LOG.info("filled %d report(s)", len(drifted))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

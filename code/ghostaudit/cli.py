"""Command line entry point: audit every deletion request and write output.csv.

    python3 code/main.py [--llm {off,cache,live}] [--agent {on,off}] [--out PATH] [--diag DIR] ...
    ghostaudit [...]        # after `pip install -e code`

Exit codes: 0 success; 1 the written output violates the contract (SPEC 8.4, N8);
2 the dataset or the arguments are unusable (SPEC N7: a clear message, no traceback).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

from ghostaudit.config import AGENT_MODES, Config, Flags
from ghostaudit.dataset import DatasetError, DatasetReader
from ghostaudit.diagnostics import DIAGNOSTICS_NAME, write_diagnostics
from ghostaudit.emit import write_output
from ghostaudit.llm.client import LLMError
from ghostaudit.llm.usage import UsageMeter, snapshot
from ghostaudit.pipeline import RunResult, build_services, run
from ghostaudit.policy import PolicyError

EXIT_OK = 0
EXIT_CONTRACT = 1
EXIT_INPUT = 2
LLM_CHOICES = ("off", "cache", "live")
SWITCH_VALUES = {"on": True, "true": True, "1": True, "off": False, "false": False, "0": False}
SAMPLE_PREDICTIONS_NAME = "sample_predictions.csv"
METER_NAME = "meter.json"  # usage snapshot read by tools/render_reports.py
LOG = logging.getLogger("ghostaudit.cli")


class UsageError(Exception):
    """A command line value is unusable."""


def build_parser() -> argparse.ArgumentParser:
    defaults = Config()
    parser = argparse.ArgumentParser(
        prog="ghostaudit", description="Ghost Data Still Exists: deletion-audit solver."
    )
    parser.add_argument("--dataset", type=Path, default=defaults.dataset_dir,
                        help="dataset directory (default: <repo>/dataset)")
    parser.add_argument("--out", type=Path, default=defaults.out_path,
                        help="output CSV for the evaluation requests (default: <repo>/output.csv)")
    parser.add_argument("--llm", choices=LLM_CHOICES, default=defaults.llm_mode,
                        help="off: no model; cache: replay stored responses; live: call the API "
                             "(default: %(default)s)")
    parser.add_argument("--agent", choices=AGENT_MODES, default=defaults.agent,
                        help="on: the router, tool-calling agent and verifier resolve contested links "
                             "(needs --llm cache or live); off: deterministic fallback everywhere "
                             "(default: %(default)s)")
    parser.add_argument("--agent-max-usd", type=float, default=defaults.agent_max_usd, metavar="USD",
                        help="cap on live agent spend for one run; past it units fall back "
                             "(default: %(default)s)")
    parser.add_argument("--agent-model", default=defaults.agent_model, metavar="ID",
                        help="model for the investigation loop (default: %(default)s)")
    parser.add_argument("--router-model", default=defaults.router_model, metavar="ID",
                        help="model for the routing call (default: %(default)s)")
    parser.add_argument("--verifier-model", default=defaults.verifier_model, metavar="ID",
                        help="model for the verifier (default: %(default)s)")
    parser.add_argument("--intent-model", default=defaults.intent_model, metavar="ID",
                        help="model for intent classification (default: %(default)s)")
    parser.add_argument("--media-model", default=defaults.media_model, metavar="ID",
                        help="model for image and PDF extraction (default: %(default)s)")
    parser.add_argument("--flags", default="", metavar="K=V,...",
                        help="override inference flags, e.g. fifo_pairing=off,never_mix=on")
    parser.add_argument("--diag", type=Path, default=defaults.diag_dir,
                        help="diagnostics directory (default: <repo>/diagnostics)")
    parser.add_argument("--include-samples", action="store_true",
                        help="also write predictions for the public samples")
    parser.add_argument("--samples-out", type=Path, default=None,
                        help="sample predictions CSV (default: <diag>/%s)" % SAMPLE_PREDICTIONS_NAME)
    parser.add_argument("--verbose", action="store_true", help="log progress at INFO level")
    return parser


def parse_flags(text: str, base: Flags) -> Flags:
    """`base` with the `name=value` overrides of `text` applied; UsageError on a bad entry."""
    names = {field.name for field in dataclasses.fields(Flags)}
    changes: Dict[str, bool] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        name, separator, value = item.partition("=")
        if not separator or name not in names or value.lower() not in SWITCH_VALUES:
            raise UsageError("bad --flags entry %r (flags: %s)" % (item, ", ".join(sorted(names))))
        changes[name] = SWITCH_VALUES[value.lower()]
    return dataclasses.replace(base, **changes)


def build_config(args: argparse.Namespace) -> Config:
    """The run configuration; the environment is read only by `Config.from_env` (SPEC N4)."""
    return dataclasses.replace(
        Config.from_env(),
        dataset_dir=args.dataset,
        out_path=args.out,
        llm_mode=args.llm,
        diag_dir=args.diag,
        intent_model=args.intent_model,
        media_model=args.media_model,
        agent=args.agent,
        agent_max_usd=args.agent_max_usd,
        agent_model=args.agent_model,
        router_model=args.router_model,
        verifier_model=args.verifier_model,
        flags=parse_flags(args.flags, Flags()),
    )


def _report(result: RunResult, args: argparse.Namespace) -> int:
    """Log the validation outcome; the exit code is non-zero on any contract violation."""
    failures = list(result.eval_validation.violations)
    if args.include_samples:
        failures += result.sample_validation.violations
    for violation in failures:
        LOG.error("contract violation %s %s: %s", violation.case_id, violation.rule, violation.message)
    return EXIT_CONTRACT if failures else EXIT_OK


def _summary(result: RunResult, args: argparse.Namespace) -> str:
    counts: Dict[str, int] = {}
    for case in result.eval_results:
        counts[case.deletion_status] = counts.get(case.deletion_status, 0) + 1
    shown = ", ".join("%s=%d" % item for item in sorted(counts.items()))
    return "wrote %d rows to %s (%s)\n" % (len(result.eval_results), args.out, shown)


def write_meter(meter: UsageMeter, requests: int, path: Path) -> None:
    """The run's LLM usage snapshot as sorted JSON; per-request averages divide by `requests`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot(meter, requests), sort_keys=True, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def prepare_outputs(args: argparse.Namespace) -> None:
    """Create the output directories before the pipeline runs, so a bad path fails at once (SPEC N7)."""
    targets = [args.out.parent, args.diag]
    if args.include_samples and args.samples_out is not None:
        targets.append(args.samples_out.parent)
    for directory in targets:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise UsageError("cannot create output directory %s: %s" % (directory, error.strerror or error))
        if not os.access(str(directory), os.W_OK):
            raise UsageError("output directory %s is not writable" % directory)


def write_results(result: RunResult, config: Config, services, args: argparse.Namespace) -> None:
    """Write output.csv, the optional sample predictions, the diagnostics and the meter."""
    write_output(result.eval_results, args.out)
    if args.include_samples:
        write_output(result.sample_results, args.samples_out or args.diag / SAMPLE_PREDICTIONS_NAME)
    write_diagnostics(result, config, args.diag)
    write_meter(services.meter, len(result.eval_results), args.diag / METER_NAME)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        prepare_outputs(args)
        config = build_config(args)
        reader = DatasetReader(config.dataset_dir)
        reader.check_complete()
        services = build_services(config)
        result = run(config, reader, services)
    except (UsageError, DatasetError, PolicyError, LLMError) as error:
        LOG.error("cannot run: %s", error)
        return EXIT_INPUT
    try:
        write_results(result, config, services, args)
    except OSError as error:
        LOG.error("cannot write results: %s", error)
        return EXIT_INPUT
    sys.stdout.write(_summary(result, args))
    LOG.info("diagnostics: %s", args.diag / DIAGNOSTICS_NAME)
    return _report(result, args)


if __name__ == "__main__":
    sys.exit(main())

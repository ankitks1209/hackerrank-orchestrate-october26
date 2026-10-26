"""One entry point for every shipped quality check: `python3 -m evaluation <command>` (from `code/`).

Commands (also available as `ghostaudit-eval <command>` after `pip install -e code`):

    check    run the solver offline and verify format, contract, determinism, invariants and the sample score
    score    score predictions against the public gold; `--ablate`, `--strategies`, `--agent-ablation` compare variants
    verify   label-free verification report (locator, recall, coverage, redundancy, invariants)
    custom   run the custom evaluation cases C1-C7
"""
from __future__ import annotations

import sys
from typing import Callable, Dict, Optional, Sequence

from evaluation import check, custom_cases, verify_report
from evaluation import main as score

COMMANDS: Dict[str, Callable[[Optional[Sequence[str]]], int]] = {
    "check": check.main,
    "score": score.main,
    "verify": verify_report.main,
    "custom": custom_cases.main,
}
EXIT_USAGE = 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in COMMANDS:
        sys.stderr.write("usage: python3 -m evaluation {%s} [options]\n" % ",".join(COMMANDS))
        return EXIT_USAGE
    return COMMANDS[arguments[0]](arguments[1:])


if __name__ == "__main__":
    sys.exit(main())

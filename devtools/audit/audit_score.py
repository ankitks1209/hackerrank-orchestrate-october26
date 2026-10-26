"""Score an audit against the output without ever feeding labels back (T39; LOCAL_EVALUATION_STRATEGY P3).

Audit labels are Markdown written by auditors who saw only raw data (R2) and never the solver.
This module reads them, compares each audited case with the output, and reports:

* status errors (the gate allows none);
* the visible step error: steps that differ among the steps both sides could state, as a share of
  the steps either side states, with its Clopper-Pearson one-sided upper bound (the gate is
  `MAX_VISIBLE_UPPER`, 1.3 %);
* the structural misses: label steps marked `EXPECTED_UNKNOWN` (ids no participant file contains,
  such as audit ids) always count as false negatives of the output and are reported apart, so the
  audit is not biased upward;
* a weighted point estimate when the sample carries inverse-probability weights.

Label format, one block per case; fields are `phase | system | resource | operation | state | evidence`:

    ### case_12
    status: INCOMPLETE
    - FINDING | search_service | search_7 | REPORT_REMAINING_RECORD | PRESENT | evidence_01
    - REMEDIATION | search_service | search_7 | DELETE_RECORD | ABSENT |
    - VERIFICATION | security_service | EXPECTED_UNKNOWN | VERIFY_RECORD_PRESENT | PRESENT |

Calibration scores the same labels against the public answers instead of the output. The
pipeline never reads this package (a test enforces it).

    python3 devtools/audit/audit_score.py --labels audit.md --pred output.csv [--weights draws.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

CODE_DIR = Path(__file__).resolve().parents[2] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from evaluation.verify_steps import Case, read_output  # noqa: E402

UNKNOWN = "EXPECTED_UNKNOWN"
ALPHA = 0.05  # one-sided 95 % bound
MAX_VISIBLE_UPPER = 0.013  # LOCAL_EVALUATION_STRATEGY P3b gate
BISECTION_STEPS = 80
FENCE = "```"
CASE_HEADING = "### "
STATUS_PREFIX = "status:"
STEP_PREFIX = "- "
STEP_FIELDS = 6
Step6 = Tuple[str, str, str, str, str, str]


class LabelError(ValueError):
    """A label file that does not follow the format."""


@dataclass(frozen=True)
class Label:
    case_id: str
    status: str
    steps: Tuple[Step6, ...]


def parse_labels(text: str) -> Dict[str, Label]:
    """Labels by case id; a malformed line raises LabelError naming its line number."""
    labels: Dict[str, Label] = {}
    current: Optional[str] = None
    status = ""
    steps: List[Step6] = []

    def close() -> None:
        if current is not None:
            if not status:
                raise LabelError("%s has no status line" % current)
            labels[current] = Label(current, status, tuple(steps))

    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(FENCE):
            fenced = not fenced
        elif fenced:
            continue
        elif line.startswith(CASE_HEADING):
            close()
            current, status, steps = line[len(CASE_HEADING):].strip(), "", []
            if current in labels:
                raise LabelError("line %d: %s is labeled twice" % (number, current))
        elif line.startswith(STATUS_PREFIX) and current is not None:
            status = line[len(STATUS_PREFIX):].strip()
        elif line.startswith(STEP_PREFIX) and current is not None:
            fields = [part.strip() for part in line[len(STEP_PREFIX):].split("|")]
            if len(fields) != STEP_FIELDS:
                raise LabelError("line %d: %d fields, expected %d" % (number, len(fields), STEP_FIELDS))
            steps.append((fields[0], fields[1], fields[2], fields[3], fields[4], fields[5]))
    close()
    return labels


def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), summed in log space."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    total = sum(math.exp(_log_choose(n, i) + i * math.log(p) + (n - i) * math.log1p(-p)) for i in range(k + 1))
    return min(1.0, total)


def upper_bound(errors: int, trials: int, alpha: float = ALPHA) -> float:
    """Clopper-Pearson one-sided upper bound on an error rate: P(X <= errors | p) = alpha."""
    if trials <= 0:
        return 1.0
    if errors >= trials:
        return 1.0
    low, high = errors / trials, 1.0
    for _ in range(BISECTION_STEPS):
        middle = (low + high) / 2
        if binomial_cdf(errors, trials, middle) > alpha:
            low = middle
        else:
            high = middle
    return high


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    status_ok: bool
    errors: int
    trials: int
    structural: int
    weight: float = 1.0


def _tuple(case: Case) -> List[Step6]:
    return [(s.phase, s.system_id, s.resource_id, s.operation, s.state, s.evidence_id) for s in case.steps]


def score_case(label: Label, predicted: Case, weight: float = 1.0) -> CaseScore:
    """Compare one label with the output. Unknown-id label steps are structural, never visible errors."""
    unknown = [step for step in label.steps if UNKNOWN in (step[2], step[5])]
    known = Counter(step for step in label.steps if UNKNOWN not in (step[2], step[5]))
    predicted_steps = Counter(_tuple(predicted))
    matched = sum((known & predicted_steps).values())
    missed = known - predicted_steps
    extra = predicted_steps - known
    for step in unknown:  # a prediction of the same kind is the output's guess at an unknowable id
        kind = (step[0], step[1], step[3], step[4])
        for guess in sorted(extra):
            if (guess[0], guess[1], guess[3], guess[4]) == kind and extra[guess] > 0:
                extra[guess] -= 1
                break
    errors = sum(missed.values()) + sum(extra.values())
    return CaseScore(label.case_id, label.status == predicted.status, errors, matched + errors,
                     len(unknown), weight)


@dataclass(frozen=True)
class AuditReport:
    cases: int
    status_errors: int
    errors: int
    trials: int
    structural: int
    upper: float
    weighted_rate: float

    @property
    def rate(self) -> float:
        return self.errors / self.trials if self.trials else 0.0

    @property
    def passes(self) -> bool:
        return self.status_errors == 0 and self.upper <= MAX_VISIBLE_UPPER


def audit(
    labels: Mapping[str, Label], predictions: Mapping[str, Case], weights: Optional[Mapping[str, float]] = None
) -> AuditReport:
    """Aggregate the scores of every labeled case; a label without a prediction is an error."""
    scores = []
    for case_id in sorted(labels):
        if case_id not in predictions:
            raise LabelError("%s has a label but no prediction" % case_id)
        scores.append(score_case(labels[case_id], predictions[case_id], (weights or {}).get(case_id, 1.0)))
    errors, trials = sum(s.errors for s in scores), sum(s.trials for s in scores)
    weighted_trials = sum(s.weight * s.trials for s in scores)
    weighted = sum(s.weight * s.errors for s in scores) / weighted_trials if weighted_trials else 0.0
    return AuditReport(len(scores), sum(1 for s in scores if not s.status_ok), errors, trials,
                       sum(s.structural for s in scores), upper_bound(errors, trials), weighted)


def render(report: AuditReport, title: str) -> str:
    lines = ["## %s" % title, "", "| Metric | Value |", "|---|---|",
             "| Audited cases | %d |" % report.cases,
             "| Status errors | %d |" % report.status_errors,
             "| Visible step errors / steps | %d / %d |" % (report.errors, report.trials),
             "| Visible step error rate | %.4f |" % report.rate,
             "| One-sided 95%% upper bound | %.4f (gate %.3f) |" % (report.upper, MAX_VISIBLE_UPPER),
             "| Weighted error rate | %.4f |" % report.weighted_rate,
             "| Structural misses (%s) | %d |" % (UNKNOWN, report.structural),
             "| Gate | %s |" % ("pass" if report.passes else "FAIL"), ""]
    return "\n".join(lines)


def load_weights(path: Optional[Path]) -> Dict[str, float]:
    """{case_id: weight} from the sampler's JSON (`estimation` list); empty without a file."""
    if path is None:
        return {}
    return {draw["case_id"]: float(draw["weight"]) for draw in json.loads(path.read_text(encoding="utf-8"))["estimation"]}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--pred", type=Path, required=True, help="output.csv (or the public answers for calibration)")
    parser.add_argument("--weights", type=Path, help="sampler JSON with inverse-probability weights")
    parser.add_argument("--title", default="Blind audit")
    args = parser.parse_args(argv)
    try:
        labels = parse_labels(args.labels.read_text(encoding="utf-8"))
        report = audit(labels, read_output(args.pred), load_weights(args.weights))
    except (OSError, ValueError, KeyError) as error:
        sys.stderr.write("cannot score: %s\n" % error)
        return 2
    sys.stdout.write(render(report, args.title))
    return 0 if report.passes else 1


if __name__ == "__main__":
    sys.exit(main())

"""Golden-set evaluation harness for link quality.

Pure scoring: no database, no network, no LLM calls. Given a golden set of
(title, body, expected_tickers) cases and a set of predicted tickers per
case, compute precision and recall over the linking decisions, and name the
individual false positives and false negatives so a regression can be
diagnosed rather than just detected.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GoldenCase:
    id: str
    title: str
    body: str
    expected_tickers: list[str]


@dataclass
class EvalResult:
    precision: float
    recall: float
    true_positives: list[tuple[str, str]] = field(default_factory=list)
    false_positives: list[tuple[str, str]] = field(default_factory=list)
    false_negatives: list[tuple[str, str]] = field(default_factory=list)


def load_golden_set(path: Path) -> list[GoldenCase]:
    """Parse the golden set, naming the offending case when one is malformed.

    `GoldenCase(**case)` on its own raises a bare TypeError about a missing
    or unexpected keyword argument, with nothing to say *which* of forty
    hand-written cases it came from.
    """
    raw = json.loads(Path(path).read_text())
    cases: list[GoldenCase] = []
    for index, case in enumerate(raw):
        label = case.get("id") if isinstance(case, dict) else None
        label = label if label is not None else f"<no id, at index {index}>"
        try:
            cases.append(GoldenCase(**case))
        except TypeError as exc:
            raise ValueError(f"golden case {label!r} is malformed: {exc}") from exc
    return cases


def score(predictions: dict[str, set[str]], cases: list[GoldenCase]) -> EvalResult:
    result = EvalResult(precision=1.0, recall=1.0)

    for case in cases:
        predicted = set(predictions.get(case.id, set()))
        expected = set(case.expected_tickers)
        result.true_positives += [(case.id, t) for t in sorted(predicted & expected)]
        result.false_positives += [(case.id, t) for t in sorted(predicted - expected)]
        result.false_negatives += [(case.id, t) for t in sorted(expected - predicted)]

    tp, fp, fn = (
        len(result.true_positives),
        len(result.false_positives),
        len(result.false_negatives),
    )
    result.precision = tp / (tp + fp) if (tp + fp) else 1.0
    result.recall = tp / (tp + fn) if (tp + fn) else 1.0
    return result

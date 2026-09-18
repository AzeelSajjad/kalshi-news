from pathlib import Path

from app.eval.golden import load_golden_set, score

GOLDEN = Path(__file__).parent / "golden" / "golden_set.json"


def test_load_golden_set_parses_cases():
    cases = load_golden_set(GOLDEN)
    assert len(cases) >= 6
    assert any(case.expected_tickers == [] for case in cases)  # a negative case exists
    negatives = [case for case in cases if case.expected_tickers == []]
    assert len(negatives) >= 2


def test_perfect_predictions_score_one():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}

    result = score(predictions, cases)

    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.false_positives == []
    assert result.false_negatives == []


def test_a_spurious_tag_lowers_precision_and_is_reported():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}
    predictions["celebrity-divorce"] = {"FED-26SEP"}

    result = score(predictions, cases)

    assert result.precision < 1.0
    assert ("celebrity-divorce", "FED-26SEP") in result.false_positives


def test_a_missed_market_lowers_recall():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}
    predictions["fed-cut-signal"] = set()

    result = score(predictions, cases)

    assert result.recall < 1.0
    assert ("fed-cut-signal", "FED-26SEP") in result.false_negatives


def test_no_predictions_and_no_expectations_does_not_crash():
    cases = [
        c
        for c in load_golden_set(GOLDEN)
        if c.expected_tickers == []
    ]
    predictions = {case.id: set() for case in cases}

    result = score(predictions, cases)

    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.true_positives == []
    assert result.false_positives == []
    assert result.false_negatives == []


def test_false_positives_are_reported_with_case_id_not_bare_ticker():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}
    predictions["celebrity-divorce"] = {"FED-26SEP"}

    result = score(predictions, cases)

    for entry in result.false_positives:
        assert isinstance(entry, tuple)
        assert len(entry) == 2
    assert "FED-26SEP" not in result.false_positives


def test_predictions_on_negative_only_cases_score_zero_precision_not_a_crash():
    cases = [c for c in load_golden_set(GOLDEN) if c.expected_tickers == []]
    predictions = {case.id: {"FED-26SEP"} for case in cases}

    result = score(predictions, cases)

    assert result.precision == 0.0
    assert result.recall == 1.0
    assert len(result.false_positives) == len(cases)


def test_precision_and_recall_are_not_swapped_on_precision_regression():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}
    predictions["celebrity-divorce"] = {"FED-26SEP"}

    result = score(predictions, cases)

    # A spurious tag hurts precision but every expected ticker was still found,
    # so recall must remain perfect.
    assert result.precision < 1.0
    assert result.recall == 1.0

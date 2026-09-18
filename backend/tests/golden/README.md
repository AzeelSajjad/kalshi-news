# Golden set

`golden_set.json` is **hand-written seed data**, not recorded production
output. The eight cases here were authored to exercise the scorer
(`app.eval.golden.score`) with a plausible mix of true positives and, just
as importantly, true negatives — stories that share surface vocabulary with
a Kalshi market ("divorce", "fire", "championship") but should not be
linked to one. Precision is the metric the product cares about most, and
precision is only measured by the negative cases.

This set is intentionally small. A later task should grow it toward ~40
cases by sampling real linked posts out of production (once the linker has
run against real markets long enough to have a track record worth
sampling), reviewing each one by hand, and recording the correct
`expected_tickers` — not by writing more synthetic cases like these.

Ticker ids follow Kalshi's `SERIES-YYMON[-STRIKE]` convention (see
`app/linker/verifier.py` and `tests/test_market_text.py` for examples
already in use elsewhere in this repo, e.g. `FED-26SEP`, `GOVSHUT-26OCT`).

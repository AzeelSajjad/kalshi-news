# SDD ledger — plan: docs/superpowers/plans/2026-09-17-backend-pipeline.md

**Spec:** docs/superpowers/specs/2026-09-17-kalshi-news-design.md
**Repo:** https://github.com/AzeelSajjad/kalshi-news (public)
**Issues:** #1–#14, one per task
**Test DB:** docker container `kalshi-pg`, pgvector 0.8.6,
`DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/kalshi_news_test`

## Branch strategy

Ruling: branch-per-task (`task-N-<slug>`) off `main`, PR per task, squash-merge
closing its issue — instead of one long-lived worktree branch. Why: the user
explicitly asked for "push the code and create a PR which you merge to close
that issue" per task. Cost if wrong: main accumulates 14 merge commits rather
than one; trivially rewritable.

## Pre-flight conflict scan

### Cross-task interface pairs

| Producer → Consumer | Produced | Consumed | Finding |
|---|---|---|---|
| T1 → T2, T10, T14 | `Settings.database_url`, `daily_llm_budget_usd`, `anthropic_api_key`, `job_token` | same names | clean |
| T2 → T5, T8, T9, T11, T13, T14 | 8 models, column names | `Market.series_ticker` (T13), `Post.linked_at` (T11), `Post.source` rel (T14), `Cluster.post_count` (T11/T14), `PostMarket.created_at` (T13), composite PK `(post_id, ticker)` (T11) | clean — every referenced column exists in T2 |
| T3 → T4, T5, T13 | `KalshiMarket`, `fetch_all_markets`, `fetch_candlesticks(..., series_ticker=)` | same signatures | clean |
| T4 → T5, T11 | `embed_texts`, `compose_market_text`, `text_hash` | patched at `app.jobs.sync_markets.embed_texts` / `app.jobs.link.embed_texts` | clean — both import the symbol into their own module |
| T9 → T10, T11 | `Candidate(ticker, title, rules_summary, close_time, yes_price, volume, distance)` | T10 test constructs positionally in that exact order | clean |
| T10 → T11 | `VerifiedLink`, `verify_candidates`, `estimate_cost` | all three imported by T11 | clean |
| T11 → T14 | `run_link(session, limit=100)` | called as `job(session)` | clean |
| T5/T8/T11/T13 → T14 | job signatures | all callable as `job(session)` | clean |
| T12 → (none) | `GoldenCase`, `score` | no consumer | clean — Interfaces block says "Consumes VerifiedLink" but the code does not; harmless doc slip, corrected in the brief |

### Per-task internal consistency

| Task | Tests vs. code it specifies | Finding |
|---|---|---|
| T1 | default `1.0` asserted, `1.0` implemented | clean |
| T2 | fixture creates extension before `create_all`; unique constraint test matches `uq_post_source_external` | clean |
| T3 | midpoint 71/73→72 asserted, `round((bid+ask)/2)` implemented | clean |
| T4 | patches module-level `_client`, which exists | clean |
| T5 | `embed.call_args.args[0] == []` vs. positional `embed_texts([...])` | clean |
| T6 | fixture `reuters.xml` specified with exact titles/dates the tests assert | clean |
| T7 | `&mdash;` stripping asserted, `_TRAILING_ATTRIB_RE` implements it | clean |
| T8 | **`test_one_failing_source_does_not_stop_the_others` depends on source iteration order**, but `query(Source).filter_by(enabled=True)` has no ORDER BY — `side_effect=[error, POST]` can bind to the wrong source | **CONFLICT 1** |
| T9 | distance math checks out: `[1,0…]` vs `[-1,0…]` → cosine distance 2.0, `<= 2.0` includes, `<= 0.5` excludes | clean |
| T10 | hallucinated-ticker and retry paths match implementation | clean |
| T11 | budget patch target `app.jobs.link.budget_remaining` is imported there | clean |
| T12 | seed golden set includes a negative case, as the test asserts | clean |
| T13 | 30h link with both prices filled is excluded by the `IS NULL` filter, so `fetch_candlesticks` is not called | clean |
| T14 | **`test_job_endpoint_runs_the_named_job` patches `app.api.run_ingest`, but `JOBS` captures the function object at import time — the patch never takes effect** | **CONFLICT 2** |
| T14 | **`Market.volume.desc().nullslast()` is not valid SQLAlchemy 2.0** (it is `.nulls_last()`, or the `nullslast()` free function) | **CONFLICT 3** |

### Rulings

**Ruling 1 (T8):** add `.order_by(Source.id)` to the source query in `run_ingest`.
Why: the plan's own test asserts an ordering the plan's code does not guarantee;
deterministic iteration is also correct behaviour independent of the test.
Cost if wrong: none — an ORDER BY on a tiny table.

**Ruling 2 (T14):** `JOBS` maps names to lambdas (`"ingest": lambda s: run_ingest(s)`)
so the global name resolves at call time and the test's patch takes effect.
Why: the spec requires the job endpoint to dispatch by name and the plan requires
the patch-based test; late binding satisfies both. Cost if wrong: one extra frame
per job call, no behavioural difference.

**Ruling 3 (T14):** use `Market.volume.desc().nulls_last()`.
Why: `.nullslast()` does not exist in SQLAlchemy 2.0; the intent (markets with no
volume sort last) is unambiguous. Cost if wrong: none — corrects a name that would
otherwise raise `AttributeError` at import.

## Progress

Task 1: dispatched (branch task-1-scaffolding, BASE 9f1a8a5, model sonnet)
Task 1: complete (commits 9f1a8a5..19d1262, review clean, CI pass 41s, PR #15 squash-merged, issue #1 closed)
Task 1: minor (deferred): secret settings default to "" rather than required — resolved: auth fails closed (T14 guard rejects on blank token), no change needed
Task 1: minor (deferred): .env.example uses port 55432 (local docker) vs CI 5432 — intentional, could use a clarifying comment

### Task 2 review rulings (3 Important, all plan-mandated)

**Ruling 4 (T2, Important 1):** replace `default=datetime.utcnow` with
`default=lambda: datetime.now(timezone.utc)` on all six defaulted timestamp columns.
Why: the plan's Global Constraints require tz-aware UTC timestamps, and the brief's
own code contradicts that constraint. The spec is the binding authority, so the
constraint wins over the brief's literal text. Naive values bound to `timestamptz`
are interpreted in the session timezone, so on a non-UTC host every freshness
window, 1h/24h price backfill, and daily spend rollup would silently be off.
Model-only change, no migration needed. Cost if wrong: none — strictly more correct.

**Ruling 5 (T2, Important 2):** `LlmSpend.usd` becomes `Numeric(10, 6, asdecimal=False)`,
keeping the `Mapped[float]` annotation.
Why: `Numeric` defaults to `asdecimal=True` and returns `Decimal`, so the annotation
was factually false. The reviewer's crash claim is overstated — Task 10's planned code
already wraps reads in `float(...)` — but an annotation that lies about its runtime
type is a trap for the remaining tasks. `asdecimal=False` makes annotation and reality
agree and turns Task 10's `float()` calls into no-ops. The DB column type is unchanged,
so no migration. Cost if wrong: float rounding at 6dp on dollar values under $1000,
which is far inside float precision.

**Ruling 6 (T2, Important 3):** stop routing the URL through
`config.set_main_option("sqlalchemy.url", ...)`; pass it straight to the engine.
Why: `set_main_option` delegates to `ConfigParser.set`, which treats `%` as an
interpolation token. Neon connection strings routinely percent-encode password
characters (`%40`, `%2F`), so production `alembic upgrade head` would die with an
opaque `InterpolationSyntaxError`. The local round-trip passed only because the dev
password has no `%`. Cost if wrong: none — removes a failure mode, adds none.

**Ruling 7 (T2, ⚠️ resolution):** add an `alembic upgrade head && alembic downgrade base`
step to the CI workflow.
Why: the reviewer correctly flagged that decision 3's round-trip was a one-off local
claim unverifiable from the diff, and that the suite builds its schema with
`create_all`, never the migration — so migration/model drift would go uncaught for the
remaining 12 tasks. This converts the claim into a permanent gate. Cost if wrong:
~15s of CI time per run.

Deferred minors (final review to triage): migration-vs-models drift beyond the new CI
step; `Market.updated_at` has no `onupdate`; no `server_default` on NOT NULL timestamps
so raw INSERTs fail; IVFFlat indexes built on empty tables need REINDEX after the first
backfill (runbook item, touches the 0.85 precision target); cache_clear guard would be
more durable as an autouse conftest fixture; relationships lack `back_populates`.
Task 2: fix round 1/5 (4 addressed: tz-aware defaults, asdecimal=False, env.py URL, CI migration gate; commits 7d78f8b..dbcb174)

**Ruling 8 (T2, fix round 2):** pin an explicit `[tool.ruff.lint] select` list and make the
tree clean under it.
Why: `ruff check .` now reports 19 errors, so the branch would fail CI's hard gate. The
implementer characterised these as pre-existing and left them — they are not: Task 1 had
zero findings and passed CI in 41s. The cause is that ruff 0.16.8's *default* rule set
fires UP017 (`datetime.timezone.utc` -> `datetime.UTC`), which Ruling 4 made ubiquitous by
converting six columns to `timezone.utc`. Relying on ruff's defaults means the lint
contract drifts with every ruff release — exactly the failure Task 1's decision 2 was meant
to prevent, and it landed anyway because that decision only pinned line-length and
target-version, not the rule selection. Cost if wrong: a future ruff release adds a rule we
do not get automatically; cheap to revisit.
Task 2: fix round 2/5 (1 addressed: pinned ruff lint selection, tree clean; commits dbcb174..b35228c)
Task 2: re-review clean — all 5 findings ADDRESSED, no new Critical/Important breakage
Task 2: minor (deferred): tz-aware-default and asdecimal=False fixes have no committed regression
  test (verified only by ad-hoc scripts in the fix report), so a future revert would go
  uncaught. Flag to final review — these two are foundational contracts for 12 later tasks.

**Ruling 9 (T2, fix round 3):** declare the distribution's packages explicitly in
`backend/pyproject.toml` (`[tool.setuptools] packages = ["app"]`).
Why: CI failed at `pip install -e "./backend[dev]"` with "Multiple top-level packages
discovered in a flat-layout: ['app', 'migrations']" — setuptools refuses to guess once
`migrations/` exists beside `app/`. This did not reproduce locally because the editable
install was performed in Task 1, before `migrations/` was created, and nothing re-ran it.
`migrations/` is deployment tooling, not importable library code, so `app` is the only
package that belongs in the distribution. Cost if wrong: none — the alternative (src-layout)
is a larger restructure for no benefit here.

**Process note:** a green local suite does not imply a green CI run when the package
manifest itself changed. For the remaining tasks, any task that adds a new top-level
directory under `backend/` must re-run `pip install -e ".[dev]"` from a clean state before
reporting.
Task 2: fix round 3/5 (1 addressed: explicit setuptools packages; commits b35228c..b15f2cb)
Task 2: re-review clean, CI pass 45s (install + ruff + alembic round-trip + pytest)
Task 2: complete (commits e178a8d..b15f2cb, 3 fix rounds, PR #16 squash-merged, issue #2 closed)

**Ruling 10 (T3, pre-emptive):** replace `[tool.setuptools] packages = ["app"]` with a find
directive `[tool.setuptools.packages.find] include = ["app*"]`.
Why: Ruling 9's literal package list names only `app`. Task 3 introduces `app/clients/`, the
first subpackage. Editable installs happen to resolve submodules through the top-level
finder, so CI would stay green — but a non-editable build would silently ship a
distribution missing `app.clients`, and every later task adds more subpackages
(`app/ingest/`, `app/linker/`, `app/jobs/`, `app/eval/`). Fixing the declaration once, at the
first subpackage, beats discovering it at deploy time. Cost if wrong: none — `app*` matches
exactly the packages that should ship.
Task 3: dispatched (branch task-3-kalshi-client, BASE 4a1fd11, model sonnet)

**Ruling 11 (T3, pre-review):** delete `backend/tests/fixtures/kalshi_markets.json`.
Why: the plan's Files section lists it, but the plan's own test code never loads it — every
payload in Task 3's tests is an inline dict, and Tasks 4, 5 and 13 use inline dicts and
MagicMock too, so no task ever reads it. The implementer correctly flagged this and filled
it with invented sample data to satisfy the file list. An unused fixture with fabricated
data is dead weight that rots and misleads later readers into thinking it is authoritative.
The plan's file list was wrong; the spec mandates nothing here. Cost if wrong: a later task
that wants recorded Kalshi payloads writes its own fixture from a real API response, which
is better than reusing invented data.
Task 3: review clean (spec ✅, approved, 0 Critical/Important)
Task 3: ⚠️ resolved — retry path has no test. Not a spec gap (the brief mandated no such
  test) and not load-bearing: Task 13 wraps candlestick calls in try/except. To final review.
Task 3: minor (deferred): @retry fires on any exception incl. permanent 4xx — wasted calls
  against Kalshi; retry_if_exception_type restricted to network/5xx/429 would be correct.
  Inherited from the plan's reference code.
Task 3: minor (deferred): httpx.Client created per KalshiClient and never closed — latent
  connection leak if instances are created repeatedly. Inherited from the plan.
Task 3: minor (deferred): no test covers the single-sided bid/ask midpoint branch.
Task 3: complete (commits 4a1fd11..78da7e4, review clean, CI pass 42s, PR #17 squash-merged, issue #3 closed)
Task 4: dispatched (branch task-4-embeddings, BASE dc906ed, model haiku)

**Ruling 12 (T4, cross-task migration fix):** `0001_initial.py` `downgrade()` must use
`DROP INDEX IF EXISTS` for both ivfflat indexes.
Why: the Task 4 implementer skipped the gated `alembic downgrade base` check, calling the
failure "pre-existing and unrelated". The claim was substantively right but unverified, so I
diagnosed it: `conftest.py` builds the test schema with `Base.metadata.drop_all/create_all`,
which rebuilds only what the *models* declare. The two ivfflat indexes exist solely as raw
SQL inside the migration, so running pytest drops them and never restores them, leaving the
database marked at head while structurally differing from what the migration builds — after
which `downgrade base` dies on `DROP INDEX ix_posts_embedding`. Verified directly:
alembic_version = 0001, tables present, `pg_indexes` shows zero `%embedding%` rows.
CI is green only by accident of step ordering (alembic runs before pytest); reordering the
steps, or adding a second pytest invocation, would break it. `IF EXISTS` makes downgrade
idempotent and order-independent. Cost if wrong: a genuinely missing index would no longer
fail loudly on downgrade — acceptable, since downgrade's job is reaching a clean base state.

**Ruling 13 (T4):** keep `create_all` in conftest rather than building the test schema with
alembic.
Why: the obvious "root fix" is to have tests run the migration so the schemas match. I am
declining it. An ivfflat index built on an empty table has degenerate centroids, and
pgvector can return *no rows* for similarity queries against it — which would make Task 9's
and Task 11's retrieval tests fail or, worse, pass vacuously for reasons unrelated to their
logic. `create_all` gives tests an exact sequential scan: deterministic and correct. The
production index still matters and still ships. Cost if wrong: test schema keeps drifting
from migration schema; mitigated by the CI round-trip gate added in Task 2, which runs
against a clean database.
Task 4: review — spec ✅, approved, 1 Important (plan-mandated), 2 Minor

**Ruling 14 (T4, Important):** rewrite the order-preservation test so it discriminates, and
add the batch-boundary test in the same round.
Why: the brief's test builds the fake OpenAI response already in index order, so
`sorted(response.data, key=lambda d: d.index)` could be deleted entirely and the test would
still pass. The sort exists because OpenAI's batch embeddings API does not guarantee
response order matches request order; if it regressed, every market would be stored against
another market's vector and retrieval would silently degrade — with no failing test and no
error, against a spec that targets ≥0.85 linking precision. A test that cannot fail for the
reason it was written is worse than no test, because it advertises coverage that is not
there. The batch-boundary test rides along: same file, same round, and the batching loop is
currently verified only by a reviewer's manual trace. Cost if wrong: two extra tests.

**Ruling 15 (T4, ⚠️ resolution — carried to Task 11):** `embed_texts` has no error handling,
and the reviewer correctly asked whether callers do. They do not, in the plan as written:
Task 11's `run_link` calls `embed_texts` bare, so an OpenAI outage would raise mid-job and
leave the `JobRun` row stranded at status='running'. The spec's "never crash" language is
scoped to the spend cap, so this is not a spec violation — but a job that dies without
recording why is a real operability gap. Resolution: Task 11's dispatch will require the job
body to be wrapped so any exception marks `JobRun.status='error'` with the message, then
re-raises. Not fixed here — this layer is correctly dumb. Cost if wrong: one job's failure
is diagnosed from CI logs instead of the job_runs table.
Task 4: fix round 1/5 (2 addressed: discriminating order test + batch-boundary test; commits a30b4ad..b806bf1)
Task 4: re-review clean — all findings ADDRESSED, no new breakage
Task 4: minor (deferred): EMBED_DIM defined but never asserted against returned vector length
Task 4: complete (commits dc906ed..b806bf1, 1 fix round, CI pass 40s, PR #18 squash-merged, issue #4 closed)
Task 5: review — spec ✅, approved, 1 Important (plan-mandated), 2 Minor

**Ruling 16 (T5, Important):** add the length guard inside `embed_texts`, not at the call site.
Why: the reviewer is right that a plain `zip(needs_embedding, vectors)` silently drops the
tail if `embed_texts` ever returns fewer vectors than texts — markets would keep stale or
absent embeddings with no error, no log and no test, degrading retrieval against the ≥0.85
precision target. But patching the `zip` in sync_markets fixes one call site; Task 11's
linker zips the same way. The actual defect is that `embed_texts` trusts OpenAI's response
to contain exactly `len(batch)` items and never checks. Guarding there protects every
present and future caller with one assertion. The implementer's diagnosis was correct and
the `strict=True` removal was right — the mock was the over-returning party, not the code.
Cost if wrong: a partial-batch response now raises loudly instead of corrupting silently,
which is the trade I want.

**Ruling 17 (T5, Minor folded in):** dedupe within a single fetch by registering newly
created markets into the `existing` map.
Why: a Kalshi pagination overlap returning the same ticker twice in one page set would
`session.add` two rows with the same primary key and kill the whole job on commit — a
crashed 15-minute cron, not a cosmetic issue. One line.

**Ruling 18 (T5, ⚠️ resolution — market status goes stale):** treat `close_time`, not
`status`, as the authority for whether a market is live, and carry this to Task 14.
Why: the reviewer correctly spotted that `fetch_all_markets()` defaults to `status="open"`,
so once a market settles Kalshi stops returning it and its row keeps `status='open'`
forever. I am NOT fixing this by inventing a settlement-reconciliation pass (marking every
market absent from the feed as settled), because a partial or degraded fetch would then
mass-mistag live markets — a much worse failure than a stale flag. Task 9's retrieval
already filters on `close_time > now`, so linking is unaffected. The only real exposure is
Task 14's trending query, which filters on `status == "open"` alone and would surface
settled markets. Task 14's dispatch will require `close_time > now` there too, making both
queries agree on one authority. Cost if wrong: the `status` column stays advisory rather
than authoritative; anything that must know true settlement reads `close_time`.
Task 5: fix round 1/5 (2 addressed: embed_texts length guard, in-fetch ticker dedupe; commits 55a0eaa..16c222f)
Task 5: re-review clean — all findings ADDRESSED, no new breakage
Task 5: complete (commits 12cb0fa..16c222f, 1 fix round, PR #19 squash-merged, issue #5 closed)
Task 6: review clean (spec ✅, approved, 0 Critical/Important)
Task 6: minor (deferred): `since` boundary is exclusive (`published <= since: continue`) but no
  test hits `published_at == since`, so a flip to inclusive would pass silently. Low risk as
  designed — Task 8 uses a rolling `now - LOOKBACK` window, not a last-seen cursor, and dedup
  is enforced by the (source_id, external_id) unique constraint rather than by `since`.
  Carried into Task 8's dispatch as an awareness note.
Task 6: minor (deferred): an entry with neither <guid> nor <link> yields empty external_id and
  url; two such malformed entries would collide on the dedup key. Not in the brief's test set.
Task 6: complete (commits 49ddfb9..c51cfff, review clean first pass, PR #20 squash-merged, issue #6 closed)
Task 7: dispatched (branch task-7-x-ingestor, BASE 0885a77, model sonnet)

**Ruling 19 (T7 concern → carried into Task 8): the plan never wires tweet discovery.**
The Task 7 implementer correctly flagged that `XIngestor.fetch` reads
`source.pending_tweet_ids` but nothing populates it — and my Task 8 brief does not wire it
either. As written, the X leg would hydrate nothing, forever, and the "news + X posts" feed
would silently be news-only. This is a plan defect, not an implementation one.
Resolution, to be required in Task 8's dispatch: after the RSS sources run, scan the `body`
of the posts ingested in that same run with `extract_tweet_ids`, drop IDs already stored as
X posts, assign the remainder to the X source's `pending_tweet_ids`, then run the X
ingestor. News outlets embed tweet URLs in article summaries constantly, so this costs zero
additional HTTP requests — the text is already in hand from the RSS fetch. Sources must
therefore be processed RSS-first, X-last.
Rejected alternative: fetching each article's full HTML to scan for embeds. It would find
more tweets, but it doubles the request count against news sites and adds a failure mode to
the hot path of the demo. If coverage proves thin, that is the upgrade — and a curated
seed list of tweet IDs is the cheaper fallback.
Cost if wrong: X coverage is limited to tweets that news outlets quote, which is a narrower
but higher-signal set than a raw account firehose.
Task 7: review clean (spec ✅, approved, 0 Critical/Important)
Task 7: minor (deferred): `_TRAILING_ATTRIB_RE` strips from the FIRST `&mdash;`, not the last —
  a literal `&mdash;` inside tweet text would truncate real content. Improbable (X escapes
  `&` to `&amp;` in bodies) but a genuine logic gap; rsplit on the last occurrence is correct.
Task 7: minor (deferred): the extract-order assertion can't distinguish first-seen order from
  accidental sorting — IDs ...001/...002 are both first-seen AND lexicographic order, so a
  `sorted(set(...))` implementation would pass. Low stakes (affects hydration order only).
Task 7: minor (deferred): XIngestor opens an httpx.Client with no close()/context manager —
  same pattern as KalshiClient and RssIngestor; one hardening pass should fix all three.
Task 7: minor (deferred): `fetch` ignores `since` by design (pending-ID queue); wants a comment.
Task 7: complete (commits 0885a77..463cb76, review clean first pass, PR #21 squash-merged, issue #7 closed)
Task 8: review — spec ✅ but **Needs fixes**: 2 Important, 5 Minor

**Ruling 20 (T8, Important 1):** extend per-source isolation to the store phase and guarantee
the JobRun reaches a terminal status.
Why: the try/except wraps only `ingestor.fetch`. The existence check queries the DB and so
cannot see rows pending in the session, meaning one RSS feed returning two items with the
same `external_id` — routine, and likelier still because RssIngestor falls back to the URL
when `<guid>` is missing — raises IntegrityError at commit, escapes `run_ingest` entirely,
skips every later source, and strands the JobRun at status='running' with finished_at NULL
forever. Ops then cannot tell a crashed run from an in-flight one. The sibling sync job
already dedupes within a batch (Ruling 17), so the standard exists in-repo. Requires:
store loop inside the guarded block with `session.rollback()` so the session survives for
the next source, in-batch `external_id` dedup, and try/finally around the bookkeeping.
Cost if wrong: a broad except could mask a systemic failure as a per-source one — mitigated
by recording the failure count and message on the JobRun (Minor 4, folded in).

**Ruling 21 (T8, Important 2):** make the already-hydrated filter run-wide, not per-source.
Why: `already_stored` filters on `source_id=source.id`, so a second X source would not know
the first already hydrated a tweet in the same run — two oEmbed calls and two Post rows for
one tweet (different source_id, so the unique constraint does not block it), producing
duplicate feed cards and a double charge against X. That directly contradicts XIngestor's
own "hydrate each one exactly once" contract and the spec's "never duplicate rows or
double-charge an API". Latent today (no second X source seeded) but invisible until it
isn't. Cost if wrong: none — a run-wide filter is strictly more correct.

**Ruling 22 (T8, Minors 3 and 4 folded in):** pin RSS-before-X as a tested property, and let
JobRun record failures.
Why: Minor 3 — both discovery tests insert the RSS source first, so the X source already has
the higher id; the structural partition that Decision 2 demanded is never actually exercised.
A test inserting the X source first is the only thing that distinguishes the guarantee from
a coincidence. Minor 4 — `status` is hard-coded 'ok', so a run where every source failed is
indistinguishable from a clean one; this pairs naturally with Ruling 20's bookkeeping change
and is the same pattern Ruling 15 requires of Task 11. Deferred: dead parameters on the X
path, redundant dedup bookkeeping, N+1 existence query.
Task 8: fix round 1/5 (4 addressed: store-phase isolation + rollback + in-batch dedup, run-wide
  hydrate filter, X-first ordering test, JobRun failure recording; commits 2d03458..569d8cf)
  Implementer also self-found a second-order bug: the handler logged `source.name` before
  `session.rollback()`, and a failed flush expires ORM objects, so that lazy reload hit the
  broken transaction and raised PendingRollbackError past the bookkeeping. Fixed by capturing
  the name before the guarded block. Re-reviewer verified the JobRun.error construction does
  not re-introduce it.
Task 8: re-review clean — all findings ADDRESSED, no new Critical/Important breakage
Task 8: minor (deferred): an exception raised inside run_ingest but outside any source's
  guarded block (e.g. during the initial Source query) still lands status='ok' because
  failed_sources is empty — terminal, but misleading. The original stuck-at-'running' bug is
  fixed.
Task 8: minor (deferred): the finally block's own commit is unguarded; a failure there sets
  the terminal status in memory without persisting it.
Task 8: complete (commits 1502d75..569d8cf, 1 fix round, PR #22 squash-merged, issue #8 closed)
Task 9: review clean (spec ✅, approved, 0 Critical/Important)
Task 9: implementer self-fixed a non-discriminating ordering test (brief inserted markets in an
  order matching the expected result, so ORDER BY removal survived); now inserts FAR before NEAR.
Task 9: minor (deferred): removing the `post.embedding is None` guard fails no test, because SQL
  NULL propagation through cosine_distance also yields []. The guard is present and correct; the
  constraint is about behaviour (no round-trip) that no current test can observe. A session.query
  spy would close it cheaply.
Task 9: complete (commits 48d9922..034e99d, review clean first pass, PR #23 squash-merged, issue #9 closed)

**Ruling 23 (process, my own error):** never chain a merge after `gh pr checks --watch` again.
On Task 9 the workflow had not registered yet, so `gh pr checks 23 --watch` printed "no checks
reported" and exited 0, and my `&&` chain merged the PR without CI having run. Main was green
afterwards (verified: run 35296230000 completed/success, and the PR's own run passed too), so
no damage — but the gate was bypassed by luck, not by design. New procedure: resolve the run id
first (`gh run list --branch <branch>`), confirm a run exists, then `gh run watch <id>
--exit-status`, and only merge on a non-zero-safe exit. Cost if wrong: a few seconds per task.
Task 10: review — spec ✅, approved, 2 Important (both plan-mandated), 6 Minor

**Ruling 24 (T10, Important 1):** the spend day key must be UTC — `datetime.now(UTC).date()`,
not `date.today()`.
Why: `date.today()` reads the process's local timezone. `app/spend.py` is the only module in
the backend on a local clock; everything else uses `datetime.now(UTC)`. On a US/Eastern host
the daily budget would roll at 04:00–05:00 UTC, and the boundary would silently move if the
deployment's TZ differed from the dev machine's. `LlmSpend.day` is a Date primary key, so rows
written under one TZ mis-key against another. A cap whose reset moment is environment-dependent
is not the hard cap the spec promises. Cost if wrong: none.

**Ruling 25 (T10, Important 2):** `verify_candidates` must return real token usage, and the
cost must sum across retry attempts.
Why: the code reads `message.content[0].text` but never `message.usage`, and returns only a
list — so no caller can recover the true counts. Task 11 would therefore charge a hardcoded
`estimate_cost(1200, 300)` per call. The reviewer estimates real usage at roughly double that
(ten candidates with real rules summaries plus the ~180-token system prompt), so a $1.00 cap
would permit ~$2.00 of spend — the cap fails open, which is precisely what the spec forbids.
The brief's own test fixture sets `usage=MagicMock(input_tokens=1200, output_tokens=300)` and
the implementation never touches it: dead scaffolding that shows the intent was there.
I am changing the interface: `verify_candidates` returns a `VerificationResult` carrying
`links`, `input_tokens`, `output_tokens`. Task 11's dispatch will be amended to record
`estimate_cost` from those real figures. Critically, usage must ACCUMULATE across both
attempts — a retry after malformed output is a second real charge, and the plan's design
silently billed it as zero. Cost if wrong: one small dataclass at a module boundary I own.

**Ruling 26 (T10, Minors 3-6 folded in):** four cheap fixes that each serve a binding
constraint, all in the same two files.
- Minor 5 (`IndexError`/`AttributeError` from `message.content[0].text` escape the except
  tuple): directly violates "never crash the caller" for malformed output. One-line fix.
- Minor 3 (fence unwrapping fails on an uppercase `JSON` tag or leading prose): fails closed,
  so precision is safe, but costs lost tags and a doubled charge per affected post — which
  now actually registers against the cap given Ruling 25.
- Minor 4 (one invalid entry rejects the whole batch): the prompt says "when related, state
  the direction" while also demanding one entry per candidate, so a null/`N/A` direction on an
  unrelated candidate is an outcome the prompt invites — and it would discard every good link
  on that post, twice. This is the first place to look if golden-set recall comes in low.
- Minor 6 (`max_tokens=1024` is tight for ten rationales): truncation yields incomplete JSON,
  which retries and likely truncates again, costing two charges for nothing.
Deferred: Minor 7 (unlocked read-modify-write in `record_spend`, and its `commit()` flushing
the caller's pending state) — acceptable for a single-process job runner, revisit if the
linker is ever parallelised. Minor 8 is a report-accuracy note only.
Task 10: fix round 1/5 (6 addressed: UTC day key, VerificationResult with accumulated real token
  usage, IndexError/AttributeError caught, brace-extraction unwrapping, per-entry link
  validation, max_tokens 2048; commits c50492b..7d7e1ce)
Task 10: re-review clean — all findings ADDRESSED; system prompt confirmed byte-unchanged; the
  per-entry validation still applies both the `related` filter and the ticker allow-list.
Task 10: minor (deferred, new): `_parse_links` iterates `payload["links"]` without an isinstance
  check — a response shaped `{"links": "text"}` would iterate characters, skip each, and return
  empty WITHOUT consuming the retry. Recall-only regression; no bad link can leak.
Task 10: complete (commits 1c91b3b..7d7e1ce, 1 fix round, CI verified via run 35297478270, PR #24 squash-merged, issue #10 closed)
Task 11: review — **Needs fixes**: 2 Important, 5 Minor, 1 ⚠️

**Ruling 27 (T11 Important 1, amends Task 10's decision 3):** a transport failure must still
propagate, but it must carry its accumulated token counts.
Why: `verify_candidates` bills attempt 1, and if that output is malformed it retries — where
`client.messages.create` can raise. Attempt 1's tokens are then real charges `run_link` never
sees, so `budget_remaining` never moves. This is not self-limiting: if the provider is
degraded, every scheduled run repeats the same billed-but-unrecorded call and the "hard cap
enforced in the database" is bypassed indefinitely. Task 10's decision 3 said transport
failures propagate to the job; I am keeping that (the job owns error recording) but adding a
`VerificationError` carrying `input_tokens`/`output_tokens`, which `run_link` catches, records
the spend from, and then re-raises or handles. Returning a partial result instead would hide a
real outage behind an empty-links response. Cost if wrong: one extra exception type.

**Ruling 28 (T11 Important 2):** add per-post isolation matching `ingest.py`'s per-source
pattern.
Why: the whole loop sits in a single try, so one post that makes the verifier raise ends the
run at that post. Because `pending` selects `linked_at IS NULL ORDER BY published_at DESC`,
the poison post stays in the working set and every later run aborts at the same place —
starving every older unlinked post behind it forever. `ingest.py` isolates at the per-source
unit for exactly this reason and its docstring says so. Cost if wrong: a systemic failure is
reported as N per-post failures; mitigated by naming the failed posts on the JobRun.

**Ruling 29 (T11 ⚠️ resolution):** the daily cap covers the Anthropic verifier only;
embedding spend is deliberately unmetered.
Why: the reviewer correctly noted `embed_texts` is called with no `record_spend`, and before
the budget check. At `text-embedding-3-small` rates ($0.02/1M tokens) a post's embedding costs
on the order of $0.000003 — roughly a thousandth of its verification call. Metering it would
add a second spend path and a second failure mode to protect against a rounding error. The
embeddings also persist and are reused, so the spend is one-time per post rather than per run.
Documenting the scope rather than widening it. Cost if wrong: at ~800 posts/day embeddings run
about $0.10/month, which would have to grow by two orders of magnitude to matter.

**Ruling 30 (T11, Minors 3-7 folded in):** all five are small, in the same two files, and two
of them guard re-charge hazards.
- Minor 3: no test pins `linked_at` being set on the verified-but-zero-links path, so moving
  that assignment inside the link loop would pass the whole suite while re-verifying and
  re-charging that post forever. The code is right; the regression lock is missing, and the
  report's "no gaps found" was overstated.
- Minor 5: the duplicate-ticker check relies on autoflush timing, and the verifier does not
  dedupe tickers — an IntegrityError on the composite PK would kill the job. `ingest.py`
  already documents avoiding exactly this pattern.
- Minor 4 (`written` counts links a failed commit rolled back), Minor 6 (a budget-paused run
  is indistinguishable from a complete one in job_runs), Minor 7 (tied `published_at` leaves
  the test's intent unpinned).
Task 11: fix round 1/5 (7 addressed: VerificationError carrying billed tokens, per-post
  isolation matching ingest.py, zero-links regression lock, commit-safe `written`, in-memory
  ticker dedupe, budget-pause note, unpinned test ordering; commits c29402a..df6e02f)
  Implementer reported that 2 of its own 7 mutation probes initially escaped detection (the
  dedupe set and the spend guard) and closed both gaps rather than glossing over them.
Task 11: re-review clean — all findings ADDRESSED, no new Critical/Important breakage
Task 11: minor (deferred): `logger.warning` reads `post.id` after rollback rather than
  capturing it before the guarded block like ingest.py does. Verified safe (rollback runs
  first, so the session is no longer in the needs-rollback state) — stylistic divergence only.
Task 11: minor (deferred): if a run has BOTH failed posts and a budget pause, `run.error`
  reports only the failed-posts message; the budget-pause note is silently dropped.
Task 11: complete (commits 5ad1587..df6e02f, 1 fix round, CI run 35299411422 success, PR #25 squash-merged, issue #11 closed)
Task 12: review clean (spec ✅, approved, 0 Critical/Important)
Task 12: minor (deferred): load_golden_set has no wrapping for malformed JSON / missing fields
  (defaults are informative but no test pins them, and errors don't name the offending case id);
  the `local-house-fire` negative is the least discriminating of the three; no literal empty-set test.
Task 12: complete (commits 5ada4e5..7559790, review clean first pass, CI run 35300031894 success, PR #26 squash-merged, issue #12 closed)
Task 13: review — **Needs fixes**: 3 Important (isolation granularity + failure-path bookkeeping)

**Ruling 31 (T13, Importants 1-3):** commit per link inside the guarded block, count only what
committed, and bring the Market lookup inside the guard.
Why: `run_impact` accumulates every `setattr` in one open transaction and commits once at the
end. A single late commit failure therefore discards every fill computed earlier in that run —
`ingest.py` and `link.py` both commit inside their per-item helper precisely so one item can
never undo another's persisted work. Worse, `filled` is incremented in memory and never reset
on rollback, so `finally` records a JobRun claiming N items filled when zero persisted: an
operator-facing lie on exactly the failure path where accuracy matters most. And the
`session.get(Market, ...)` sits outside the per-link try, so a DB hiccup on one lookup aborts
the whole run instead of skipping one link. The controller asked this task to match the
established idiom; this is the third divergent pattern that request was meant to prevent.
Cost if wrong: one commit per link instead of one per run — negligible at this volume, and the
same trade the other two jobs already make.

**Ruling 32 (T13, ⚠️ resolution):** the `series_ticker` fallback is acceptable as built.
Why: the reviewer flagged that if `Market.series_ticker` is often NULL, `fetch_candlesticks`
silently falls back to `ticker.split("-")[0]`. Task 5 does persist whatever Kalshi returns, and
the fallback matches Kalshi's own ticker convention, so the degradation is sensible rather than
silent corruption — and a wrong series ticker yields no candles, which this job already
tolerates by leaving the field NULL. Not worth a lookup table. Cost if wrong: impact numbers
stay unfilled for markets whose series cannot be derived, which is visible as an absent delta
rather than a wrong one.

Deferred minors: no confidence/distance recorded when the closest candle is far from the target
(inherited from the plan's reference design — a thin market with a candle 25 minutes off is
treated identically to an exact match, worth a future ticket); per-item failure taints run
status, consistent with the other two jobs.
Task 13: fix round 1/5 (3 addressed: per-link commit, committed-only counting, Market lookup
  inside the guard; commits 49ac18f..36f74bc)
Task 13: re-review clean — all findings ADDRESSED; capture-then-try matches _ingest_source exactly
Task 13: minor (deferred, new): applying the per-link guard removed the plan's per-FIELD
  try/except, so a raise while fetching price_1h now aborts price_24h for that link too. Only
  ever delays a fill (retried next run), never yields a wrong number — consistent with this
  task's "wrong is worse than missing" priority. Restoring a nested per-field guard inside the
  per-link guard would give both properties; flag to final review.
Task 13: complete (commits f4e3923..36f74bc, 1 fix round, CI run 35301160376 success, PR #27 squash-merged, issue #13 closed)
Task 14: review — **Needs fixes**: 2 Important (pagination), 8 Minor. All six controller
  decisions and both binding behaviours verified correct and genuinely test-pinned, including
  the ordering-preservation half of the N+1 fix.

**Ruling 33 (T14, Important 1):** `limit` needs a lower bound and the cursor line needs a guard.
Why: `Query(30, le=100)` constrains only the upper bound, so `?limit=0` validates, `posts` is
empty, `len(posts) == 0 == limit` is True, and `posts[-1]` raises IndexError straight out of the
handler — a trivially reachable 500 with a traceback on the feed, which is the demo's front
door. A negative limit reaches Postgres as `LIMIT -5` and errors too. Cost if wrong: none.

**Ruling 34 (T14, Important 2):** replace the bare-timestamp cursor with a keyset cursor on
`(published_at, id)`.
Why: ordering is `published_at DESC` with no tie-breaker and the next page filters
`published_at < cursor`. Three posts sharing a timestamp with limit=2 means the third is
excluded from every page, permanently — and since order among equal timestamps is
non-deterministic, *which* post vanishes changes between requests. This is not hypothetical
here: RSS feeds routinely round published_at to the minute and a batch ingest stamps many posts
identically. Cost if wrong: a slightly longer cursor string.

**Ruling 35 (T14, Minors folded in):** items 3,4,5,7,8,9 plus the socket guard (6).
- Minor 6 is the important one: nothing at the suite level prevents a live external call. The
  constraint "no test may make a live external API call" currently rests entirely on every test
  author patching the right symbol — and this task's own mutation experiment proved that a
  single mis-targeted patch becomes a real Kalshi request. An autouse socket block turns a
  convention into an enforced invariant.
- Minor 9 pins the ordering guarantees decision 5 named but no test asserts, and exercises
  `_load_cluster_sizes` beyond its empty-input early return.
- Minors 3 and 4 fall out of the pagination rewrite; 5, 7 and 8 are one-liners.
Deferred: Minor 10 (CORS wildcard also covers the job endpoints). `allow_credentials` is False
and the token is not a cookie, so a browser gains nothing curl could not already do; the
reviewer flagged it as a note rather than a defect and I agree.
Task 14: fix round 1/5 (9 addressed: limit lower bound, keyset cursor over (published_at,id),
  lookahead next_cursor, 422 on bad/naive cursor, sanitized 500 detail, autouse socket guard,
  compare_digest, cache_clear teardown, ordering+cluster_size assertions; commits 90ce4ba..40a62c5)
  Implementer's first socket guard silently did nothing (pytest-socket resets restrictions in
  its per-test teardown, so a session-scoped fixture held only for test 1). Caught solely
  because the required demonstration test existed — code inspection would have passed it.
Task 14: re-review clean — all findings ADDRESSED; cursor round-trip confirmed lossless at
  microsecond precision, socket allowance confirmed host-matched and unable to cover an
  external HTTPS call.
Task 14: minor (deferred): CORS wildcard also covers the job endpoints (allow_credentials is
  False and the token is not a cookie, so a browser gains nothing curl could not already do).
Task 14: complete (commits 7ae1a47..40a62c5, 1 fix round, CI run 35303098725 success, PR #28 squash-merged, issue #14 closed)

## FINAL WHOLE-BRANCH REVIEW — "With fixes". 2 Critical, 10 Important.

**C1 — the linker is inert against real Kalshi data.** `sync_markets` stores whatever Kalshi's
payload says (`status: "active"`, per this repo's own recorded fixtures), while `find_candidates`
and both trending queries filter `status == "open"`. Every downstream test hand-constructs
`Market(status="open")` and never goes through `sync_markets`, so producer and consumer disagree
while both halves pass. The reviewer probed it live against the test DB: stored status "active",
candidates found []. On deploy the feed renders entirely untagged and trending returns two empty
lists, with CI green.

**My Ruling 18 is the direct cause.** I concluded `close_time` is the authority and `status` is
advisory — then required only Task 14's trending query to add `close_time`, leaving `status ==
"open"` in place as a conjunct in every query including retrieval. Holding both positions is what
let C1 hide. The correct ruling was "remove `Market.status` from every WHERE clause," which would
have made C1 unreachable. Recording this as my error, not the implementers'.

**C2 — `linked_at` is a permanent tombstone.** Set unconditionally even when zero candidates were
found, and nothing clears it; the spec's nightly `relink` was omitted as "matters only once the
catalog churns." That framing (mine, inherited from the plan) was wrong: the cron runs `link`
every 10 min and `sync_markets` every 15, so on a cold deploy the first `link` can fire before any
market exists — permanently marking that batch linked. Compounded with C1, fixing the status bug
would still leave the entire backlog untagged forever.

Also: clustering links per post rather than per cluster (plan contradiction — Task 11's Interfaces
says "cluster representatives", its reference code links every post), the golden set never runs the
linker so the 0.85 target is unmeasurable, nothing can create a Source row, no README or deploy
config, and no test crosses a stage boundary — which is precisely why C1 survived 14 reviews.

Reviewer endorsed Rulings 12/14/20/25/27/34 and 13/23 explicitly; pushed back on 18 (above), 29
(framing understates that sync_markets embeds the whole catalog unbudgeted), and the relink
omission. Full report in the task transcript; triage of all 20 deferred minors recorded there.

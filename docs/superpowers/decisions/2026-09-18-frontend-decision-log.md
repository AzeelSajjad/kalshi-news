# SDD ledger — plan: docs/superpowers/plans/2026-09-18-frontend-and-deploy.md

**Spec:** docs/superpowers/specs/2026-09-18-frontend-and-deploy-design.md
**Product surface authority:** docs/superpowers/specs/2026-09-17-kalshi-news-design.md
**Repo:** https://github.com/AzeelSajjad/kalshi-news · **Issues:** #31–#42
**Branch strategy:** branch per task, PR per task, squash-merge closing its issue (as in the backend plan).
**CI gate procedure:** resolve the run id first, then `gh run watch <id> --exit-status`. Never chain a
merge behind `gh pr checks --watch`, which exits 0 before a workflow registers (backend Ruling 23).

## Pre-flight conflict scan

### Cross-task interface pairs

| Producer → Consumer | Produced | Consumed | Finding |
|---|---|---|---|
| T2 → T3-T11 | Vitest harness, `@` alias, Tailwind `@theme` tokens | `@/lib/types`, `@/components/*`, colour classes | **CONFLICT 1** — the `@` alias is configured in `vitest.config.ts` but T2 never states `tsconfig.json`'s contents, so `npm run typecheck` and `next build` would not resolve `@/` |
| T2 → all | `postcss.config.mjs` listed as created, contents never given | Tailwind v4 requires the `@tailwindcss/postcss` plugin or `@import "tailwindcss"` compiles to nothing | **CONFLICT 2** |
| T3 → T4,T5,T7,T9,T10 | `MarketRef`, `FeedItem`, `PostDetailData`, `TrendingPage`, `FeedPage` | same names, field-by-field | clean — verified against `backend/app/schemas.py` |
| T4 → T5,T9 | `<MarketTag market={ref} />` | same prop | clean |
| T5 → T8,T10 | `<PostCard item={item} />`, `timeAgo` | same | clean |
| T6 → T8 | `<Header active={...} />`, `CATEGORIES` | same | clean |
| T7 → T8 | `<TrendingRail trending={page} />` | same | clean |
| T8 → T10 | `app/page.tsx` | T10 modifies it to render `LoadMore` | clean — sequential, no overlap |
| T2 → T9 | `app/layout.tsx` | T9 modifies it to accept the `modal` slot | clean — sequential |
| T9,T10 → T11 | built app + routes | Playwright drives them | **CONFLICT 5** (below) |

### Per-task internal consistency

| Task | Tests vs. the code it specifies | Finding |
|---|---|---|
| T1 | recorded payload replayed through the real client; second test asserts retrieval ignores `status` | clean |
| T2 | CI runs `npm ci`, which needs a committed `package-lock.json`; `npm i` generates one and the commit adds `frontend/` | clean |
| T3 | MSW handlers use an absolute base matching `BACKEND_API_URL` | clean |
| T4 | `toHaveAttribute(name, expect.stringContaining(...))` — jest-dom supports asymmetric matchers | clean |
| T5 | `PostCard` renders `next/link`; **RTL has no Next router mounted** | **CONFLICT 3** |
| T6 | `Header` renders `next/link` throughout | **CONFLICT 3** (same cause) |
| T7 | volume formatting is exercised only indirectly; assertions are on text that does not depend on it | clean |
| T8 | `EmptyState` is pure; `page.tsx` deliberately untested (stated in the plan's self-review) | clean |
| T9 | `PostDetail` is pure and testable; `Modal` uses `useRouter` but no unit test renders it | clean |
| T10 | `LoadMore` calls `fetch("/api/feed?…")` — **a relative URL, which Node's fetch rejects** | **CONFLICT 4** |
| T11 | `page.route` intercepts browser requests; the feed page fetches **server-side**, so nothing is intercepted and the page errors | **CONFLICT 5** |

### Rulings

**Ruling 1 (T2, CONFLICT 1):** `tsconfig.json` must declare `"baseUrl": "."` and
`"paths": { "@/*": ["./*"] }`, matching the vitest alias.
Why: the plan configures the alias in one of the two places that need it. Without the tsconfig
half, `npm run typecheck` and `next build` fail on every `@/` import — and CI runs both, so this
would surface as a red build in Task 2 rather than as a subtle bug. Cost if wrong: none.

**Ruling 2 (T2, CONFLICT 2):** `postcss.config.mjs` must export
`{ plugins: { "@tailwindcss/postcss": {} } }`.
Why: Tailwind v4 compiles `@import "tailwindcss"` only through that plugin. Omitted, the build
succeeds and every utility class silently does nothing — a failure that looks like a CSS problem
rather than a config one, and no test would catch it. Cost if wrong: none.

**Ruling 3 (T5/T6, CONFLICT 3):** mock `next/link` globally in `vitest.setup.ts` to render a plain
anchor carrying `href`.
Why: `next/link` in the App Router asserts a mounted router and throws "invariant expected app
router to be mounted" under React Testing Library. Every `Header` and `PostCard` test would fail
for an environment reason unrelated to what they assert. A plain-anchor mock keeps the `href`
assertions — which are the actual contract those tests check — fully meaningful. Cost if wrong:
the tests verify the href we pass rather than Next's routing behaviour; Task 11's browser test
covers real navigation.

**Ruling 4 (T10, CONFLICT 4):** `LoadMore` builds an absolute URL from `window.location.origin`,
and its MSW handler registers that absolute URL.
Why: the plan's `fetch("/api/feed?…")` is valid in a browser and throws `Failed to parse URL` under
Node's fetch, which is what jsdom tests run on. Resolving against `location.origin` is correct in
both environments and costs one line. Cost if wrong: none — identical behaviour in the browser.

**Ruling 5 (T11, CONFLICT 5):** the e2e run needs a stub backend process, not `page.route`.
Why: the plan stubs with `page.route("**/api/feed*")`, which intercepts requests the *browser*
makes. The feed page is a Server Component — Next fetches the backend from the server, so the
browser never issues that request, nothing is intercepted, and the page errors against a dead
`127.0.0.1:9999`. The test would fail for a reason that looks like a routing bug. Fix: a small
`e2e/stub-backend.mjs` serving `/api/feed`, `/api/posts/:id` and `/api/trending`, started as a
second Playwright `webServer` entry on 9999. Cost if wrong: one extra file in the e2e harness.

## Progress

Task 1: dispatched (branch task-f1-kalshi-payload, BASE 8f3b074, model sonnet)

**Task 1 confirmed the premise: Kalshi's stored `status` is `"active"`, never `"open"`.** The
backend's Critical defect was real, and the fix (removing `status` from every WHERE clause) is
now pinned by a test that fails if it is ever re-coupled — verified by the implementer
temporarily reintroducing the filter and observing the failure.

**Ruling 6 (new Critical found by Task 1 — insert Task 1b before the frontend):** the Kalshi
client parses field names the live API does not use.
I verified the captured payload myself. It contains `yes_bid_dollars = '0.0000'`,
`yes_ask_dollars`, `last_price_dollars`, `volume_fp = '0.00'` and `open_interest_fp` — all
**strings, in dollars or fixed-point**. There is no `yes_bid`, no `yes_ask`, no `volume`, and no
`series_ticker` anywhere in the response. `KalshiClient` reads exactly the names that are absent,
so `raw.get()` returns None for every one.
Consequences against live data: every market stores `yes_price = None`; `price_at_link` is
therefore None; `price_delta` is therefore None on every link, forever — the impact tracker's
headline claim produces nothing. Trending `by_volume` orders an all-null column. And
`series_ticker` being absent means the candlestick call always uses the derived fallback rather
than a real series (Ruling 32 accepted that fallback; it is now confirmed to be the only path).
This is the same failure shape as the status bug — silently empty, tests green — and it lands on
the feature the frontend is about to render. Fixing it after the frontend would mean building
against fields that are always blank. Cost if wrong: one task's delay before UI work.

**Ruling 7 (T1b, price semantics):** `yes_price` prefers `last_price_dollars` when above zero,
falls back to the bid/ask midpoint, and is None when the market has never traded and has no
two-sided quote.
Why: the captured market is brand new — bid 0.0000, ask 0.0000, volume 0. A naive midpoint of a
0/1.00 spread on a thin market reports a confident 50¢ that no one would trade at, which is worse
than showing nothing. Prediction-market UIs show the last trade. Cost if wrong: markets with a
live two-sided quote but no trades show the midpoint instead of nothing, which is the correct
reading anyway.

**Ruling 8 (T1b, pagination):** bound the `fetch_all_markets` loop.
Why: the Task 1 implementer hit a real hang — replaying a recorded page whose `cursor` never
changes spun `while True` for over two minutes at 95% CPU until the process was killed. It
worked around this by blanking the fixture's cursor, which fixes the test and leaves the client
defect in place. Against live Kalshi, any repeated or sticky cursor hangs the sync job forever
and the 15-minute cron piles up behind it. Break when a cursor repeats, and cap total pages.
Cost if wrong: an unusually large catalog needs the cap raised.

**Ruling 9 (T1b, back-compat):** read the new field names with a fallback to the old ones.
Why: the existing `test_kalshi_client.py` fixtures use `yes_bid`/`yes_ask`/`volume`. Accepting
both keeps those tests meaningful rather than rewriting them to match whatever the API happens to
return today, and it survives Kalshi renaming things back. Cost if wrong: a few extra lines.
Task 1: review — spec ✅ but **Needs fixes**: 3 Important

**Ruling 10 (T1, Important 1):** the fixture's `close_time` values must be shifted relative to
`now` at load time, not replayed as recorded.
Why: the captured markets close 2026-09-21/22/23. `find_candidates` filters
`close_time > datetime.now(UTC)`, so within days of merge the regression test fails with
`assert []` — the exact symptom of retrieval being re-coupled to `status`. A future maintainer
would have no way to distinguish "the pin caught the regression" from "the fixture rotted," which
makes a durable pin into a periodic false alarm. This is the same failure class as everything
else this project has hit: a signal that looks authoritative while meaning nothing. Shift the
dates; leave `status` and every other field exactly as recorded. Cost if wrong: the fixture no
longer proves anything about close-time parsing, which test 1 already covers separately.

**Ruling 11 (T1, Importants 2-3):** the fixture's provenance and its one intentional edit must be
documented in shipped code, not only in the workspace report.
Why: the report lives in `.superpowers/`, which is gitignored — it does not travel with the
fixture. A future reader opening `kalshi_markets_live.json` cannot tell whether it is a real
capture or invented data, which is precisely the distinction this task was created to establish.
And the blanked `cursor` means the envelope is no longer wholly real; someone reasonably assuming
otherwise could build a pagination test on it. A docstring recording the capture date, the exact
endpoint and query, and the one edited field closes both. Cost if wrong: a few lines of comment.
Task 1: fix round 1/5 (3 addressed: load-time date shift, provenance docstring, cursor edit
  flagged; commits b92332e..25d0f87)
Task 1: re-review clean — shift confirmed computed at import time, fixture JSON byte-identical,
  `status: "active"` preserved, no stray temp file committed

**Ruling 12 (process, my own error):** stop committing documents directly to local `main`.
I committed the spec and plan to local main, branched from it, and let the squash-merge fold
those commits into the remote — so local main held two commits that remote never saw as
themselves, and `git pull --ff-only` refused. Verified before resetting: both files exist on
origin/main and are byte-identical to the local versions, so `git reset --hard origin/main` lost
no content, only two commit subjects that the squash body already absorbs. From here, spec and
plan commits go on the task branch that carries them, not on main. Cost if wrong: none — the
content was confirmed present before the reset, not assumed.
Task 1: complete (commits 8f3b074..25d0f87, 1 fix round, CI run 35368720069 success, PR #44 squash-merged, issue #31 closed)
Task 1b: review — spec ✅, approved, 1 Important, 3 Minor

**Ruling 13 (T1b, Important):** the fallback must trigger on value usability, not key presence.
Why: the guard is `if new_key in raw`, so a payload carrying the new key with `None`/`''`/garbage
alongside a usable old key returns `None` — it never looks at the old key at all. Inert against
today's live data (real responses contain no old keys) and it fails in the safe direction, but a
transition period where Kalshi ships both field styles is exactly the scenario the fallback was
added for, and this project has now been bitten twice by field-name assumptions. One line.
Cost if wrong: none — strictly more permissive in the direction the fallback already intends.

**Ruling 14 (T1b, Minor 3 folded in):** parse dollar strings with `Decimal`, not `float`.
Why: `round(float('0.6350') * 100)` is subject to binary float representation — the product is
63.49999…, so it rounds to 63 rather than 64, and the reviewer and I disagreed about what it
produces, which is itself the argument. This is a money path feeding a number the UI presents as
fact, and the project's recurring failure mode is precisely numbers that are quietly wrong.
`Decimal(value) * 100` quantized to an integer is exact and no harder to read. Cost if wrong:
negligible per-market parsing overhead on a job that already makes network calls.

**Ruling 15 (T1b, Minor 2 folded in):** cover the `last_price` old-name fallback with a test.
Why: only the `yes_bid`/`yes_ask`/`volume` old branches have real coverage; the `last_price`
branch is reachable and untested. Cheap, and it is the branch that now takes precedence over the
midpoint, so an error there silently changes every price.

Ruling 16 (T1b, Minor 1): no action — `test_kalshi_client.py` was listed as "Modify" in the brief
I wrote but needed no edits, because the fallback design kept those tests passing unchanged. That
is the better outcome and the implementer disclosed it. My file list was wrong, not the work.
Task 1b: fix round 1/5 (3 addressed: usability-based fallback, Decimal ROUND_HALF_UP with pinned
  boundaries, last_price fallback covered; commits 604ad00..c928016)
  Behaviour change recorded: '0.6250' produced 62 under float round() (banker's rounding) and
  produces 63 now. My own earlier claim that '0.6350' gives 63 under float was wrong — it gives
  64 either way. The divergence is at 0.6250, found only by rewriting the code to be unambiguous.
Task 1b: re-review clean — all findings ADDRESSED, InvalidOperation caught, old-field tests
  unaffected because they bypass the Decimal path entirely
Task 1b: complete (commits c6b6d2d..c928016, 1 fix round, CI run 35370597298 success, PR #45 squash-merged, issue #43 closed)
Task 2: dispatched (branch task-f2-scaffold, BASE 379d3e1, model sonnet)

**Ruling 17 (T2, TypeScript version):** endorse pinning `typescript@5.9.3`.
Why: the implementer found `npm i -D typescript` now resolves to 7.0.2 — the native/Go compiler —
which removed the `baseUrl` option that Ruling 1 required verbatim. It pinned 5.9.3 rather than
silently dropping the option or inventing a different alias scheme, and flagged the deviation.
That is the right instinct and the right call for a project whose whole purpose is a link that
works: Next 15's tooling targets TS 5.x, and a major compiler rewrite is not where this project
should be adventurous. Noting the alternative for the record — modern TS supports `paths` without
`baseUrl`, so TS 7 plus a bare `paths` map would also have worked — but that trades a known-good
toolchain for an unknown one to save nothing. Cost if wrong: a version bump later, on a project
that pins its Python dependencies for the same reason.
Task 2: review clean (spec ✅, approved, 0 Critical/Important)
Task 2: minor (deferred): @types/node ^26 is ahead of the Node 22 CI runtime (harmless today);
  the next/link mock spreads Link-only props onto a plain anchor, which may produce benign
  unknown-DOM-attribute warnings in later Header/PostCard tests.
Task 2: complete (commits 379d3e1..f80802f, review clean first pass, CI run 35371789339 success — backend AND frontend jobs both green, PR #46 squash-merged, issue #32 closed)
Task 3: review clean (spec ✅, approved, 0 Critical/Important). All six type contracts verified
  field-by-field against the backend shape — the check that matters most given this project's two
  producer/consumer field-name defects. Implementer added a 7th test after finding the brief's
  own "omits params" test never exercised the undefined-value guard (calling with no args makes
  opts `{}`, so the guard is unreachable); reviewer independently confirmed the gap and the fix.

**Ruling 18 (T3, minors deferred):** do not add `import "server-only"` to `lib/api.ts` now.
Why: it would convert an accidental client-side import from a runtime error into a build-time
one, which is genuinely better for the six downstream tasks — but the `server-only` package
resolves through a `react-server` export condition and can throw when imported under vitest,
which would break the very test suite that proves this module works. Current behaviour is safe:
`BACKEND_API_URL` is not `NEXT_PUBLIC_`-prefixed so Next never inlines it into the client bundle,
and a mistaken import fails loudly with "BACKEND_API_URL is not set" rather than leaking. Worth
revisiting once a component task actually needs the guard, where the vitest interaction can be
tested in isolation. Cost if wrong: a confusing runtime error instead of a clear build error, on
a mistake no current task makes. Also deferred: `ApiError` carries `path` only in its message,
not as a field.
Task 3: complete (commits a67ab64..0722531, review clean first pass, CI run 35372690688 success, PR #47 squash-merged, issue #33 closed)
Task 4: dispatched (branch task-f4-markettag, BASE 20a2a6f, model sonnet)

**Ruling 19 (T4, plan defect I own):** endorse gating the delta badge on `yes_price !== null`
as well as `price_delta !== null`.
Why: my plan's Step 3 reference component contradicted my plan's Step 1 test. Test 5 asserts no
`¢` renders when `yes_price` is null, but the reference gated the delta badge only on
`price_delta !== null` — so the fixture's `price_delta: 11` still rendered `▲ 11¢` and the test
failed against the code I supplied. The implementer ran it verbatim, observed the failure, and
fixed the component rather than weakening the test, which is the right order.
The fix is also semantically correct, not just test-satisfying: a delta is a change *relative to a
current price*, so showing "▲ 11¢" beside no price at all is a number without a referent — the
exact failure mode this project keeps hitting. A market with no price and a non-null delta is
itself an inconsistent state the backend should not produce. Cost if wrong: in that inconsistent
state the UI hides a delta it could have shown, which is the safe direction.
Task 4: review clean (spec ✅, approved, 0 Critical/Important). Reviewer verified character-by-
  character that the test file matches the brief unchanged, and that the delta gating is a strict
  narrowing — with a price present the condition reduces to the original, so only the no-price
  case changed.
Task 4: minor (deferred): `price_delta: 0` renders `▲ 0¢` in mint, i.e. "no movement" styled as
  positive (inherited from the plan's reference, untested by any brief test); `direction: string`
  is not a `"YES" | "NO"` union so any non-YES string falls to the negative branch; no test covers
  a NO-direction market with a non-null price.
Task 4: complete (commits 20a2a6f..8ad6f9c, review clean first pass, CI run 35373427397 success, PR #48 squash-merged, issue #34 closed)
Task 5: review clean (spec ✅, approved, 0 Critical/Important). Reviewer verified verbatim-brief
  claim by programmatic diff rather than eyeballing, and hand-traced timeAgo's three boundary
  transitions (60s, 60m, 24h) which the brief's tests do not exercise — all roll over cleanly.
Task 5: minor (deferred): a null author_name/author_handle renders a blank byline with no
  fallback; the headline link's href is never asserted despite the next/link mock existing to
  make that possible; MarketTag's `key={ticker}` would collide if one post ever carried two refs
  with the same ticker.
Task 5: complete (commits 7ce88bf..756f578, review clean first pass, CI run 35374089795 success, PR #49 squash-merged, issue #35 closed)

**Ruling 20 (batching Tasks 6 and 7):** dispatch Header and TrendingRail as ONE implementer.
Why: both are pure presentational components with complete code in the plan, no shared state, no
interdependency, and identical shape — the skill's own guidance is to batch same-shape work and
reserve one-dispatch-per-task for work needing its own judgment. Five tasks in, each loop is
costing four to five turns for components of a few dozen lines. One dispatch, one review of the
combined diff, one PR closing both issues. Cost if wrong: a review that has to reject one
component rejects both, costing one extra fix round — cheaper than the loop it replaces.
Tasks 6+7: review — TrendingRail ✅ approved; Header **Needs fixes** (1 Important, plan-mandated)

**Ruling 21 (T6, Important — my plan's defect):** replace the off-palette hex literals with
existing tokens rather than adding new ones.
Why: my Header reference uses `bg-[#0D1211]` and `text-[#06120F]`, neither of which appears in
the eight-token palette the plan's own Global Constraints mandate. They are leftovers from the
mockup, where the header bar was a shade off the page background and the active tab needed dark
text on mint. Both needs are already met by tokens: `bg-surface` (#14191A) for the bar and
`text-bg` (#0A0D0C) on mint, which has very high contrast. Using existing tokens beats adding two
more, because the constraint's point is that one palette governs the whole UI — TrendingRail
already follows it, so the header is the odd one out. Cost if wrong: the header bar is a slightly
different dark than the mockup showed, adjustable in one class.

**Ruling 22 (T7, Minors folded in):** fix the empty-heading asymmetry, the volume formatting, and
the pluralisation.
Why: the "Trending markets" heading renders unconditionally while "Most covered today" is guarded,
so a state with no volume-ranked markets but some covered ones shows an empty heading — reachable
on a fresh deploy, which is exactly when someone is most likely to be looking. And
`(volume / 1_000_000).toFixed(1)` renders any market under ~50,000 as `$0.0M vol`, which reads as
"no volume" for a market that has some — a number that renders confidently while meaning nothing,
which is the failure this project keeps finding. Kalshi has plenty of low-volume markets.
Cost if wrong: two formatting branches instead of one.

Ruling 23 (T6/T7, ⚠️ resolution): the reviewer could not verify the integration site because it
does not exist yet — `app/page.tsx` is Task 8, whose brief already specifies
`<Header active={category ?? null} />` and passes a real `TrendingPage`. Not a gap.
Tasks 6+7: fix round 1/5 (4 addressed: palette tokens, guarded first heading, sub-million volume
  format, singular pluralisation; commits 1f82b57..f975851)
Tasks 6+7: re-review clean — all findings ADDRESSED, no new breakage. `$0K vol` for a zero-volume
  market is accepted as distinct from null (deferred minor: "no volume" would read better).
Tasks 6+7: complete (commits dd9b110..f975851, 1 fix round, CI run 35375408397 success, PR #50 squash-merged, issues #36 and #37 closed)
Task 8: dispatched (branch task-f8-feed-page, BASE 45de5ee, model sonnet)

**Ruling 24 (T8, gap the implementer flagged rather than silently fixing):** add an error boundary.
Why: `fetchFeed`/`fetchTrending` throwing leaves Next's generic default error page — and that is
reachable in normal operation, not just catastrophe: a Railway restart, a deploy window, a Neon
hiccup. The spec's first success criterion is "a public URL that loads a populated, current feed
at any time," and a raw framework error page fails it in the most visible way possible, on a link
whose entire purpose is to be clicked once by someone forming an impression. The implementer was
right to flag rather than expand scope on its own; the right answer is to rule it in, here, where
the page lives. It is ~15 lines. Cost if wrong: a component that renders only when something has
already gone wrong.

**Ruling 25 (T8, second instance of a defect I wrote):** endorse replacing `text-[#06120F]` in the
NewsletterButton reference with `text-bg`.
Why: the same off-palette literal the Header carried, in a second file of my plan — so the defect
was not a one-off slip but a pattern in how I wrote the reference code. The implementer caught it
by checking the reference against the plan's constraints rather than only against its own tests,
which is exactly the widened check the previous round asked for. Cost if wrong: none.
Task 8: fix round 1/5 (1 addressed: app/error.tsx with reset(), palette tokens, no error.message
  in the DOM; commits 2d92091..68dcfb1)
Task 8: re-review clean. Implementer established that curl cannot observe this boundary at all —
  Next mounts error.tsx client-side after hydration, so failure HTML carries only a digest — and
  verified with headless Chrome instead of declaring success from a 500 status.
Task 8: minor (deferred): a no-JavaScript visitor sees the digest-only 500 rather than the
  friendly copy (Next's default behaviour); a root-layout failure still falls through to Next's
  default, which would need global-error.tsx.
Task 8: complete (commits 45de5ee..68dcfb1, 1 fix round, CI run 35376708692 success, PR #51 squash-merged, issue #38 closed)
Task 9: dispatched (branch task-f9-postdetail, BASE dbb5071, model sonnet). Intercepting routes
  WORKED — named fallback not needed. Verified live: direct /posts/1 server-renders the body,
  clicking a feed card navigates to /posts/1 with a [role=dialog] overlay over the still-mounted
  feed, backdrop click calls router.back(), /posts/999 renders 404 rather than an unhandled error.

**Pattern in my own plan, recorded:** that is now SIX off-palette hex literals across THREE files
of reference code I wrote — Header (2), NewsletterButton (1), PostDetail (3). Each was caught by a
different implementer only because they were told to check the reference against the plan's
constraints and not merely against its own tests. The plan's Global Constraints section names the
token palette, but I then wrote components using raw hex from the mockup, and no test anywhere
asserts palette compliance. The lesson is not "implementers should check" — they did — it is that
a constraint with no executable check gets violated by its own author.
Task 9: review — spec ✅ but **Needs fixes**: 2 Important, 5 Minor

**Ruling 26 (T9, Important 1 — my brief's defect):** the Modal must be dismissable by keyboard and
must announce properly.
Why: it declares `role="dialog" aria-modal="true"`, which tells assistive tech to hide everything
outside it — but focus is never moved in, so after the soft navigation a screen-reader user's
focus sits on the feed link *behind* the overlay, in content their reader has just been told to
ignore. There is no Escape handler and no close button, so the only way out is the mouse or
browser Back. That is a trapped user, not a polish item, and the rubric is right to call it a
defect. Inherited verbatim from my brief. Cost if wrong: a few lines of focus handling on a
component that is already the most complex in the UI.

**Ruling 27 (T9, Important 2):** add tests for the two unguarded binding constraints.
Why: the reviewer answered the question I asked it, and its argument is the right one — using the
brief's four tests verbatim justifies not *changing* them, not declining to *add* to them. Both
constraints mutate green today: strip `target`/`rel` from the outbound link, or replace the X
byline branch with a constant, and all four tests still pass. One of those is a reverse-tabnabbing
control. This plan has already shipped seven palette violations that no test could catch; the
pattern is unchecked constraints, and the answer is checks. Cost if wrong: two assertions.

**Ruling 28 (T9, Minors folded in):** items 3-6 are each one line or close to it and each prevents
a real future divergence.
- `revalidate` on the intercepted route: today both paths read the same 60s data cache because
  `fetchPost` pins it at the fetch level, so behaviour is correct — but the report reached that
  conclusion without checking segment config at all. Making the pair identical on inspection is
  how it stays correct when someone edits one of them.
- The stop-propagation wrapper is full-width, so clicking the gutters beside the article does
  nothing. With no Escape and no close button, dismissal was thinner than the browser evidence
  suggested — that test clicked the backdrop element directly rather than where a user would.
- `bg-black/60` is the **seventh** non-palette colour in my reference code. `bg-bg/60` is legal
  and visually near-identical.
- Body copy fell to `text-muted`, the same colour as the byline, flattening the hierarchy; the
  palette-legal substitute for primary copy is `text-text`.
Task 9: fix round 1/5 (6 addressed: Modal focus+Escape+close button+aria-labelledby, target/rel
  and @handle assertions on both branches, revalidate parity, backdrop dead zone, bg-bg/60,
  text-text body copy; commits 1324944..aaf80bf)
Task 9: re-review clean. The CDP methodology distinction was confirmed real: a synthetic DOM
  dispatch invokes a known node's listeners and can never reveal which element actually receives
  a click at a screen position, because it bypasses hit-testing. Real coordinate input does not.
Task 9: complete (commits dbb5071..aaf80bf, 1 fix round, CI run 35379017747 success, PR #52 squash-merged, issue #39 closed)
Task 10: review — spec ✅ but **Needs fixes**: 1 Important, 2 Minor

**Ruling 29 (T10, Important):** add a two-click regression test for append-vs-replace.
Why: `setItems(prev => [...prev, ...page.items])` is the whole purpose of this component, and the
brief's test cannot distinguish it from `setItems(page.items)` — internal state starts empty, so
one click passes identically under either. The only proof of real append behaviour was a live
browser run against a scratch stub that has since been deleted, so nothing in the repo will catch
a refactor that silently starts dropping earlier pages. This is the same shape as the seven
palette violations and the two unguarded link constraints: correct code with no executable check,
which in this plan has repeatedly meant a defect waiting for someone to look. Cost if wrong: one
more test in a file that already has the harness.

**Ruling 30 (T10, Minor folded in):** handle the rejected-fetch path rather than leaving an
unhandled promise rejection.
Why: `loadNext` is fired from `onClick` with nothing awaiting it, so a genuine network failure —
as opposed to a non-2xx response, which is handled — surfaces as an unhandled rejection. State
cleanup still runs so the UI does not stick, which is why the reviewer rated it Minor, but a
console-level unhandled rejection on a demo someone is poking at is avoidable in one line. Log it
the way `error.tsx` does: to the console, never to the user. Cost if wrong: none.
Not folded in: `limit` is not forwarded by the proxy, but the reviewer confirmed page 1 does not
send one either, so both pages consistently take the backend default — no inconsistency exists to
fix.
Task 10: fix round 1/5 (2 addressed: two-click append regression test asserting both pages present
  simultaneously, console.error on rejected fetch; commits d59ea1e..fa65065)
Task 10: re-review clean — test confirmed to fail under the setItems(page.items) mutation with
  "Unable to find an element with the text: Story 2", so it genuinely requires accumulation.
Task 10: complete (commits dfa2b99..fa65065, 1 fix round, CI run 35380706465 success, PR #53 squash-merged, issue #40 closed)
Task 11: review clean (spec ✅, approved, 0 Critical/Important). Reviewer corroborated the
  deliberate-break evidence by independent code inspection rather than trusting the narrative: a
  full navigation renders PostDetail without Modal's role="dialog" wrapper, so a broken
  interception fails both the dialog check AND the feed-still-visible check.
Task 11: minor (deferred): vitest's `exclude` replaces the built-in defaults rather than spreading
  configDefaults, silently dropping dist/cypress/config globs — inert today, a footgun later; the
  URL regex is unanchored on the left of the numeric segment.
Task 11: complete (commits c44a956..bdfacd4, review clean first pass, CI run 35381765076 success
  — frontend AND backend jobs green, which also resolves the ⚠️: Playwright's Ubuntu install and
  headless run were verified on real CI infrastructure, not assumed. PR #54 merged, issue #41 closed)
Task 12: dispatched (branch task-f12-deploy-runbook, BASE f102588, model sonnet)

**Ruling 31 (T12):** move the Procfile into `backend/` rather than documenting a workaround.
Why: the repo's only Procfile sits at the root and reads `web: cd backend && uvicorn ...`, but
Railway's root directory must be `backend/` for Nixpacks to find `pyproject.toml` — and at that
root the Procfile is invisible. The implementer found this genuine ambiguity (it came from my
earlier backend plan, not from anything it wrote) and resolved it by telling the reader to set an
explicit Custom Start Command, which works. But a runbook step that exists to route around a
misplaced file is a step that will rot: someone will eventually "fix" the Procfile, or follow the
default, and get a deploy that fails for a reason the document no longer explains. Moving it to
`backend/Procfile` with the `cd` removed makes the default behaviour correct and deletes the
workaround. Cost if wrong: if Railway is ever pointed at the repo root instead, there is no
Procfile there — which the runbook now states explicitly.
Task 12: fix round 1/5 (1 addressed: Procfile moved to backend/, runbook workaround removed;
  commits 8f0722e..fdb9629)
Task 12: review clean (spec ✅, approved, 0 Critical/Important). Reviewer spot-checked the
  runbook against the code rather than accepting the claim: env var names, /health response shape,
  job names, the X-Job-Token header, every table and column in the checkpoint SQL, the seed counts
  (9 sources, 7 enabled), and BACKEND_API_URL — all accurate. Step 4's checkpoint gives exact SQL
  with a branch table of what each result means, not "check the logs".
Task 12: complete (commits f102588..fdb9629, 1 fix round, CI run 35382861442 success, PR #55 squash-merged, issue #42 closed)

## FINAL WHOLE-BRANCH REVIEW — "With fixes". 2 Critical, 10 Important.

**C1 — three category tabs are permanently empty.** Header ships eight tabs; the seed migration
seeds only Politics/Economics/Finance/World, and `ingest.py` sets `post.category =
source.category` unconditionally, so a post can never have another category. Both World feeds are
seeded `enabled=False`. So Crypto, Sports and Culture render "No stories yet" forever, and the
empty-state copy ("in the current window") implies transience for a permanent state.

**Ruling 23 was wrong, and it caused C1.** I closed the Task 6/7 reviewer's ⚠️ — that it could not
verify Header's integration site — on the grounds that Task 8's brief already specified the props.
The props were never the risk. That was the single moment in thirteen tasks when anyone was
looking at `CATEGORIES` and the seeded data together, and I closed it. The right disposition was
"defer to Task 8's review", carried forward as an open item. Recording this as my error.

**C2 — RSS bodies are HTML rendered as literal text.** `rss.py` stores `entry.summary` verbatim;
Politico, Bloomberg and CNBC all put markup in `<description>`. `PostDetail` renders `{post.body}`
as a React text node, so the centered post view — the surface a recruiter clicks into — displays
`<p>` and `<a href=...>` as visible text. The reviewer verified this with feedparser rather than
assuming. Every test fixture uses plain prose, which is why nothing caught it.

Ten Importants, the sharpest being: `TrendingRail` formats a price directly, violating the
single-formatter constraint three lines from code a fix round had just edited; `MarketTag` renders
a NO-direction link as "NO 64¢" when 64¢ is the YES price and NO is 36¢ — the wrong number on the
product's central claim, to an audience of Kalshi employees; the route handler has zero tests at
any level; and the runbook never says deltas are empty for the first hour, so an operator will
conclude the impact tracker is broken.

**The reviewer's structural point, which I accept:** the pattern is broader than colour. Eight
palette literals, a component failing its own test, a relative-URL fetch, an unworkable Playwright
stub, and the two undetected survivors are all one defect — reference code written from the mockup
rather than checked against the constraints section of the same document. Its fix is better than
mine: **each Global Constraint should name its executable check where it is stated.** A constraint
that cannot name its check is one that will be violated.

## Close-out

Fix wave for the whole-branch review: PR #57, squash-merged as `dcf80b9`, closing issue #56.
All 13 findings plus both promoted minors verified ADDRESSED by a scoped re-review, with
file:line evidence for each. CI green on the merged `main` (run 35389510779, frontend and
backend jobs both success). Backend 154 → 164 tests; frontend 46 → 80 across 17 files.

Four low-severity minors left open as follow-ups, not gates:
- `truncate()` can split a surrogate pair at the cut point.
- `strip_html()` now also runs over RSS titles, which is harmless but unintended.
- The standalone post page now depends on `/api/trending` as well as `/api/posts/{id}`.
- Nulling `_price_cents` also suppresses the delta badge, by way of Ruling 19's gate.

Plan complete. Nothing in this ledger blocks the deploy.

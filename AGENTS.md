# CardProfitHunter Agent Guide

## Project purpose

Card Profit Hunter V5.2.40 is a Python/Streamlit application for finding and ranking sports-card opportunities from eBay. It runs saved searches, normalizes Browse API results, evaluates raw-flip and PSA-grading economics, and stores saved searches, watchlists, run outcomes, and opportunity snapshots in local SQLite. Treat all scores, profits, ROI values, and suggested offers as decision support, not guaranteed outcomes. The supported launch baseline is local-only, single-user development and controlled demonstrations; do not add hosted or multi-user behavior unless explicitly requested and separately reviewed.

## Repository layout

- `app.py`: Streamlit entry point, UI tabs, settings, searches, and CSV exports.
- `ebay_client.py`: eBay client-credentials OAuth, token cache, Browse API search, and result normalization.
- `profit_engine.py`: card matching, valuation safety checks, profit/ROI calculations, scoring, and recommendations.
- `database.py`: SQLite schema and data-access functions. The local database is `data/card_profit_hunter.db`.
- `config/settings.json`: tracked fee, cost, threshold, and offer-cap defaults.
- `sample_data/`: tracked demonstration listings and valuations. Bundled valuations marked `Example only` are not actionable.
- `tests/`: `unittest` regression, engine, eBay-client, workflow, and temporary-database tests.
- `output/`, `data/`, `.cache/`: generated local state; do not commit their contents.
- `requirements.txt`: runtime dependencies. `VERSION` contains the current release version.

## Setup, run, and test

Use Python 3.11 or 3.12; Python 3.12 is recommended. Use the commands documented by this repository:

```bash
cd ~/Projects/CardProfitHunter
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create `.env` only when it is absent; never overwrite a configured local file:

```bash
test -f .env || cp .env.example .env
```

Run all tests with the standard-library test runner; pytest is not required:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
```

Run the application:

```bash
python -m streamlit run app.py
```

There is no build step, package configuration, or lockfile in this repository. Do not invent one.

## Python and Streamlit conventions

- Follow the existing Python style: `from __future__ import annotations`, type hints, snake_case names, small helpers, and `pathlib.Path` paths rooted at the repository.
- Preserve established pandas input and output column names; the UI, database, CSV exports, and tests depend on them.
- Keep eBay network activity behind explicit Streamlit button actions. Importing or rendering unrelated tabs must not trigger searches.
- Preserve the isolated Streamlit startup smoke test: it must use a temporary copied runtime tree, strip inherited eBay variables, block outbound HTTP, and avoid real local state.
- Configure the Streamlit page before other UI calls. Follow the existing sidebar/tab structure, use `st.session_state` for transient results, and use `width="stretch"` for tables.
- Show actionable failures through the UI without exposing credentials, access tokens, or sensitive response data.
- Changes to matching, valuation, profit, scoring, or recommendation behavior require focused regression tests.
- Write discoverable tests as `unittest.TestCase` methods. Do not add module-level pytest-style `test_*` functions; the canonical `unittest` command skips them.

## eBay API safety

- This project uses application-level client-credentials OAuth for public marketplace browsing. Do not add buying, bidding, offering, seller-account, or other transaction actions without explicit authorization and a separate safety review.
- Start with `sandbox` for development and controlled demonstrations. Production must be selected deliberately. Automated tests must not call live eBay endpoints.
- Keep the existing 30-second request timeouts, marketplace header, environment-specific URLs, and search limit clamp of 1–200 unless a documented API requirement changes.
- Never print, log, commit, or place client secrets or bearer tokens in errors. Token data belongs only in the ignored `.cache/` directory; preserve private directory/file permissions and atomic cache replacement.
- Do not weaken strong card-identity matching. A player-name-only match must not select a specific card valuation.
- Preserve positive trading-card evidence gating for raw and Scout candidates. Ambiguous memorabilia without card evidence must remain excluded even when rarity, autograph, rookie, or seller signals would otherwise produce a high Scout score.
- Preserve single-card product gating for Scout candidates. Sealed boxes, cases, packs, tins, complete sets, multi-card bundles, uncut or promotional sheets/panels/strips, quantity multipliers, pairs, multiple copies, mixed/bulk lots, and choose-multiple listings must remain non-actionable, while explicit single-card condition phrases such as `pack fresh`, printing plates, and achievement wording such as `2X MVP` may remain eligible.
- Choice-menu inventory such as `U Pick`, choose/select-one, dropdown/list selection, complete-your-set, per-card pricing, and individually sold card listings must remain non-actionable across relevance, Scout, and direct financial-analysis boundaries; legitimate card identity words such as Draft Picks, Select, and Choice may remain eligible.
- Do not treat card-brand words as proof that an item is a card when strong memorabilia objects are present. Signed balls, photos, helmets, jerseys, bats, pucks, coins, and books must remain excluded unless the title explicitly identifies a supported card or relic construct.
- Card accessories, empty packaging, grading/cleaning/authentication services, replacement labels, and other non-card merchandise must remain non-actionable across relevance, Scout, and direct financial-analysis boundaries; ordinary included-protection wording may remain eligible.
- Redemption, rewards-points, points-card, and code-only products must remain non-actionable at classification, Scout, and financial-analysis boundaries. They are not substitutes for the underlying collectible card.
- Custom, replica, reproduction, unofficial, not/non-licensed, fan-made, handmade, ORICA, parody, AI-generated, concept, aftermarket, counterfeit, fan-art, ACEO, novelty, homemade, fake, bootleg, trimmed, altered, restored, color-added, and minimum-size-problem listings must remain non-actionable across relevance, Scout, and financial boundaries.
- Recognize common autograph wording consistently for discovery and parsing, but keep `signed`, `autographed`, and manufacturer-autograph valuation identities distinct unless the verified valuation explicitly supports the same wording.
- Presale, preorder, not-in-hand, unreleased, stock-image, representative-image, non-actual-item, and image-may-vary listings must remain non-actionable across relevance, Scout, and direct financial-analysis boundaries.
- Affirmatively disclosed scratches, print lines, off-centering, dents, dimples, wear, surface issues, whitening, chipping, scuffing, peeling, staining, creasing, fading, and paper loss must remain non-actionable; preserve explicitly negated no-defect wording.
- Mystery, repack, grab-bag, blind-bag, random-card/hit/player/team, surprise, hot-pack, and chase-pack products must remain non-actionable across relevance, Scout, and direct financial-analysis boundaries.
- Break participation, break spots, pick-your-team/player formats, rip-and-ship services, live rips, and box/case/pack opening services must remain non-actionable across relevance, Scout, and direct financial-analysis boundaries.
- Missing, NaN, `pd.NA`, blank, or malformed required listing title/condition values must fail closed across parsing, relevance, Scout, and direct financial-analysis boundaries; do not coerce missing containers into artificial text.
- Financial BUY and OFFER actions require a nonempty seller username, at least 100 feedback ratings, and at least 99.0% positive feedback. Missing, malformed, or below-threshold seller data must remain PASS and non-financial. Preserve the same fail-closed rule at engine, opportunity/watchlist persistence, dashboard, history, and recent-activity read boundaries; do not trust stored action labels without qualifying payload data. Return-policy verification remains a manual operator step unless a separately reviewed item-detail workflow is approved.
- Recognized grading-company labels, grades, slabs, encapsulation, and professionally graded wording must remain non-actionable as raw-card or raw-to-grade opportunities across parsing, classification, Scout, and direct financial-analysis boundaries.
- Rows marked `Example only`, rows without complete structured provenance, and expired valuations must remain non-actionable: no BUY or OFFER recommendation and no suggested offer.
- Profit, ROI, max-buy, and suggested-offer logic must use the same total-modeled-cost assumptions. Purchase tax, promoted-listing fees, return/defect allowance, and grading loss risk are required configurable inputs; missing or invalid values must fail closed.
- Suggested offers must remain capped at `max_offer_market_pct` (currently 90% of verified raw market value). Preserve or strengthen the associated regression tests.

## Environment variables

- Local values live in ignored `.env`; commit only empty/documented placeholders in `.env.example`.
- Preserve private local secret and diagnostic handling: `.env` and diagnostic log files use `0600`, diagnostic log directories use `0700` on POSIX, and symlinked targets fail closed.
- Supported variables are `EBAY_ENVIRONMENT`, `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, and `EBAY_MARKETPLACE_ID`.
- Never hardcode credentials or copy real values into documentation, fixtures, tests, screenshots, logs, or exceptions.
- When adding a variable, update `.env.example` and relevant setup documentation without adding a real value.
- Never add hosted secret handling or expose environment values to multiple users without explicit authorization and a separate security design.

## Data and database safety

- SQLite files (`*.db`, `*.sqlite`, and `*.sqlite3`) are local runtime state and must stay ignored. Never stage or commit them.
- Preserve private local SQLite handling: writable database/backup directories use `0700`, database/backup files use `0600` on POSIX, and symlinked database targets fail closed.
- Do not delete, reset, overwrite, or silently migrate a user's database. Schema changes must preserve existing data and be safe when `init_db()` runs repeatedly.
- Continue using parameterized SQL, the `connect()` context manager, UTC timestamps, explicit commits, and closed connections.
- Database tests should patch `database.DB_PATH` to a path under `tempfile.TemporaryDirectory`; new tests must not mutate the user's local database.
- Preserve fail-closed schema checks during database initialization and backup inspection. Existing unversioned databases may be adopted only when required tables, columns, foreign keys, and non-repairable index definitions are compatible; do not silently rewrite an incompatible schema.
- Database restore must remain local and explicit: verify integrity, exact supported schema version, required schema shape, and foreign keys; create a verified pre-restore safety backup; replace atomically; and never restore during normal rendering.
- Preserve validated atomic persistence for `config/settings.json` and `sample_data/card_values.csv`: write and `fsync` a same-directory temporary file, re-read it through the normal validator, atomically replace the destination, and leave the original intact on failure.
- Treat `sample_data/card_values.csv` as demonstration data unless a row has `verification_status=verified`, current ISO verification/expiry dates, an HTTPS source URL, and a positive comp count. Notes alone never make a valuation actionable. Do not convert example, unverified, malformed, or expired values into actionable recommendations.
- CSV exports and other generated output belong under ignored `output/` and must not be committed. Preserve spreadsheet sanitization, atomic replacement, private `0700`/`0600` directory and file modes on POSIX, and fail-closed symlink handling for generated CSV writes.
- Preserve bounded Sample Analysis inputs: each upload is at most 5 MB, and listing/valuation frames are limited to 1,000 rows and 64 columns before analysis.
- This public repository is a sanitized source copy with separate clean history. Never import or merge the private development repository's history; sync only a reviewed tracked tree after private-runtime artifact and secret checks pass.

## Dependency rules

- Use the standard library or current dependencies before adding a package.
- Add every new runtime import to `requirements.txt` with a justified compatible version constraint.
- Do not perform broad dependency upgrades as part of unrelated work.
- Keep the supported test suite on standard-library `unittest` unless a separate development dependency change is explicitly approved.

## Definition of done

A change is done when it is narrowly scoped, preserves the safety invariants above, and `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v` passes. For UI changes, also launch the app with the documented Streamlit command and verify the affected workflow. Update tests and documentation when behavior or setup changes. Do not leave secrets, databases, token caches, logs, generated output, or other runtime state staged.

## Review checklist before commits

- Review the staged diff and confirm only intended source, test, configuration, and documentation files are included.
- Confirm `.env`, `.cache/`, virtual environments, SQLite files, output files, logs, and Python caches are absent.
- Run `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v` and resolve failures rather than weakening tests.
- For engine changes, verify false card matches cannot produce BUY/OFFER actions, example and stale valuations remain PASS-only, and offer caps still hold.
- For eBay changes, verify sandbox/production routing, request limits, timeouts, marketplace handling, and secret redaction.
- For database changes, verify parameterized SQL, repeatable initialization, temporary test databases, and preservation of existing data.
- For UI changes, verify the affected tab manually and keep Streamlit API usage consistent with the existing app.
- Ensure dependency, setup, README/INSTALL, and `VERSION` changes are included only when the change requires them.

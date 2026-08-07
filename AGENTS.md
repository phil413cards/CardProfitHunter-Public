# CardProfitHunter Agent Guide

## Project purpose

Card Profit Hunter V5.2.3 is a Python/Streamlit application for finding and ranking sports-card opportunities from eBay. It runs saved searches, normalizes Browse API results, evaluates raw-flip and PSA-grading economics, and stores saved searches, watchlists, runs, and opportunity snapshots in local SQLite. Treat all scores, profits, ROI values, and suggested offers as decision support, not guaranteed outcomes. The supported launch baseline is local-only, single-user development and controlled demonstrations; do not add hosted or multi-user behavior unless explicitly requested and separately reviewed.

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
- Configure the Streamlit page before other UI calls. Follow the existing sidebar/tab structure, use `st.session_state` for transient results, and use `width="stretch"` for tables.
- Show actionable failures through the UI without exposing credentials, access tokens, or sensitive response data.
- Changes to matching, valuation, profit, scoring, or recommendation behavior require focused regression tests.

## eBay API safety

- This project uses application-level client-credentials OAuth for public marketplace browsing. Do not add buying, bidding, offering, seller-account, or other transaction actions without explicit authorization and a separate safety review.
- Start with `sandbox` for development and controlled demonstrations. Production must be selected deliberately. Automated tests must not call live eBay endpoints.
- Keep the existing 30-second request timeouts, marketplace header, environment-specific URLs, and search limit clamp of 1–200 unless a documented API requirement changes.
- Never print, log, commit, or place client secrets or bearer tokens in errors. Token data belongs only in the ignored `.cache/` directory.
- Do not weaken strong card-identity matching. A player-name-only match must not select a specific card valuation.
- Rows marked `Example only` must remain non-actionable: no BUY or OFFER recommendation and no suggested offer.
- Suggested offers must remain capped at `max_offer_market_pct` (currently 90% of verified raw market value). Preserve or strengthen the associated regression tests.

## Environment variables

- Local values live in ignored `.env`; commit only empty/documented placeholders in `.env.example`.
- Supported variables are `EBAY_ENVIRONMENT`, `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, and `EBAY_MARKETPLACE_ID`.
- Never hardcode credentials or copy real values into documentation, fixtures, tests, screenshots, logs, or exceptions.
- When adding a variable, update `.env.example` and relevant setup documentation without adding a real value.
- Never add hosted secret handling or expose environment values to multiple users without explicit authorization and a separate security design.

## Data and database safety

- SQLite files (`*.db`, `*.sqlite`, and `*.sqlite3`) are local runtime state and must stay ignored. Never stage or commit them.
- Do not delete, reset, overwrite, or silently migrate a user's database. Schema changes must preserve existing data and be safe when `init_db()` runs repeatedly.
- Continue using parameterized SQL, the `connect()` context manager, UTC timestamps, explicit commits, and closed connections.
- Database tests should patch `database.DB_PATH` to a path under `tempfile.TemporaryDirectory`; new tests must not mutate the user's local database.
- Treat `sample_data/card_values.csv` as demonstration data unless its notes identify verified comps. Do not convert example values into actionable recommendations.
- CSV exports and other generated output belong under ignored `output/` and must not be committed.
- Keep this repository's history free of local databases and other runtime data. Never merge or graft history from a private development repository into this clean public history.

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
- For engine changes, verify false card matches cannot produce BUY/OFFER actions, example valuations remain PASS-only, and offer caps still hold.
- For eBay changes, verify sandbox/production routing, request limits, timeouts, marketplace handling, and secret redaction.
- For database changes, verify parameterized SQL, repeatable initialization, temporary test databases, and preservation of existing data.
- For UI changes, verify the affected tab manually and keep Streamlit API usage consistent with the existing app.
- Ensure dependency, setup, README/INSTALL, and `VERSION` changes are included only when the change requires them.

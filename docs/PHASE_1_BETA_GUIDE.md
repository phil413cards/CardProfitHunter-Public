# CardProfitHunter Phase 1 Beta Guide

CardProfitHunter 5.2.42 is ready for private, controlled, local beta testing. Kevin is the only Phase 1 beta tester. There are no outside users, subscriptions, hosted deployments, or public marketing in this phase.

The Phase 1 goal is to prove usefulness, reliability, and real-world decision quality. Testing must not make or imply claims of guaranteed profit.

## What this tool does

CardProfitHunter helps a user evaluate sports-card listings from eBay. It can:

- run eBay Browse API searches using sandbox or deliberately selected production credentials;
- normalize listing data and reject incomplete or incompatible listings;
- conservatively match listings to card valuations;
- model raw-flip and PSA-grading profit and ROI;
- classify opportunities as actionable or non-actionable;
- save searches, watchlist entries, run history, and opportunity snapshots in local SQLite;
- analyze the bundled sample CSV files without calling eBay; and
- create spreadsheet-safe CSV exports and local database backups.

Recommendations are decision support only. They are not guarantees of authenticity, condition, grading outcome, sale price, fees, or profit.

## What this tool does not do

CardProfitHunter does not:

- buy, bid on, make offers for, or sell cards;
- submit cards to PSA or manage a grading pipeline;
- verify card authenticity or physical condition;
- provide verified sold comparables automatically;
- guarantee that a listing identity or valuation is correct;
- support shared, hosted, or multi-user operation; or
- replace independent review before spending money.

## How to install

Use Python 3.11 or 3.12. Python 3.12 is recommended.

```bash
git clone <repository-url> CardProfitHunter
cd CardProfitHunter
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
```

Do not overwrite an existing `.env`. If macOS reports a LibreSSL or urllib3 compatibility warning, recreate the virtual environment with a current Python 3.11 or 3.12 distribution.

## How to use sandbox credentials

Obtain sandbox application keys from the eBay Developer Program. Open the local `.env` file and enter only sandbox credentials:

```dotenv
EBAY_ENVIRONMENT=sandbox
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_MARKETPLACE_ID=EBAY_US
```

Keep `EBAY_ENVIRONMENT=sandbox` throughout Phase 1 testing. Production must be selected deliberately and is not required for the safe demo workflow.

Never commit or share `.env`. Do not paste credentials or tokens into screenshots, issue reports, chat messages, exported files, or application logs. If the environment value is missing, the app safely defaults to sandbox. If it is invalid, eBay calls are blocked until a valid environment is explicitly selected.

## How to run tests

Activate the virtual environment, then run the complete supported test suite:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
```

The project uses Python's standard-library `unittest` runner. pytest is not required. Do not continue with a beta demo if tests fail.

## How to start Streamlit

From the repository root with the virtual environment active, run:

```bash
python -m streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`. Stop the app with `Ctrl+C` in the terminal.

## How to run a safe demo workflow

1. Run the full test suite and confirm it passes.
2. Start Streamlit and confirm the sidebar environment is `sandbox`.
3. Open **Sample Analysis** and leave both upload fields empty so the bundled sample files are used.
4. Select **Run Sample Analysis**. This workflow does not call eBay.
5. Confirm the results load without an exception. Bundled valuations marked `Example only` are intentionally non-actionable and must not contribute positive financial opportunities.
6. Open **Dashboard** and confirm PASS or WATCH rows are not shown as financial opportunities.
7. Open **Setup** and review the sanitized diagnostics. The report must not display credentials, tokens, submitted values, database contents, or local paths.
8. Optionally test **Live Search** with sandbox credentials, a small result limit, and a valid query. Keep the environment set to sandbox and do not treat sandbox results as real buying opportunities.
9. Optionally save a search and run **Daily Buy Board**. Confirm empty, partial, failed, and successful states are clearly identified and stale results do not remain after a new failure.
10. If results are available, download a CSV and confirm it opens normally. Do not place orders or make offers based on a beta recommendation.

Do not use the retention deletion control during a routine demo. Database backup and cleanup are explicit local maintenance actions, not required demo steps.

## What feedback to record for Kevin

Record a concise report containing:

- operating system and version;
- Python version from `python --version`;
- the workflow and exact steps performed;
- expected behavior and actual behavior;
- whether the run was sample, sandbox, or local maintenance;
- the visible sanitized diagnostic event code, if one appeared;
- whether any card match, PASS reason, score, profit, ROI, or offer appeared incorrect;
- whether empty, partial, failed, and stale-result states were understandable; and
- any confusing labels, missing instructions, or accessibility problems.

A useful report format is:

```text
Summary:
Environment: sample or sandbox
OS / Python:
Steps:
Expected:
Actual:
Diagnostic code, if shown:
Suggested improvement:
```

Screenshots are helpful only after checking that they contain no credentials, tokens, `.env` values, private notes, or other sensitive local data. Do not send `.env`, SQLite databases, token caches, or raw diagnostic logs.

## Known limitations

- The supported baseline is local-only and single-user. Hosted or multi-user deployment is not ready.
- eBay searches require network access and valid application credentials; sandbox inventory and behavior may differ from production.
- Only USD listings with complete, valid price, shipping, condition, and supported buying-option data can become actionable.
- Conservative identity matching intentionally produces false negatives when card identity is ambiguous.
- Graded or slabbed listings are non-actionable as raw-flip or raw-to-grade opportunities.
- Example, demonstration, unverified, PASS, and WATCH rows are non-financial by design.
- Valuations must be supplied and verified by the user. Bad valuation data can invalidate the analysis even when schema validation passes.
- Profit and ROI are modeled estimates based on configured fees, shipping allowances, grading costs, and probabilities.
- The PSA submission and grading workflow is not implemented.
- Local SQLite data, backups, exports, token caches, and logs remain the user's responsibility and must not be committed or shared.

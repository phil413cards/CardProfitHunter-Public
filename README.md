# CardProfitHunter 5.1.1

CardProfitHunter is a Python/Streamlit application for finding and evaluating sports-card listings from eBay. It normalizes Browse API results, applies conservative card-identity matching, models raw-flip and PSA-grading economics, and stores local searches and opportunity snapshots in SQLite.

## Launch baseline

This release is for **local-only, single-user development and controlled demonstrations**. It is not ready for hosted or shared multi-user use. A hosted launch requires authentication, managed secrets, isolated per-user storage, database migration and backup procedures, and a separate privacy review.

Use eBay sandbox credentials first. Switching `EBAY_ENVIRONMENT` to `production` must be a deliberate decision after local validation.

## Requirements

- Python 3.11 or 3.12; Python 3.12 is recommended.
- Git and a terminal.
- eBay Developer Program sandbox application credentials for live sandbox searches.

Avoid the old macOS system Python. Its LibreSSL build is incompatible with urllib3 2.x and can emit TLS compatibility warnings.

## Local setup

Clone the repository, or open an existing checkout, and start from its root:

```bash
git clone <repository-url> CardProfitHunter
cd CardProfitHunter
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
```

Open `.env` locally and add eBay sandbox credentials. Keep this setting until production access is intentionally approved:

```dotenv
EBAY_ENVIRONMENT=sandbox
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_MARKETPLACE_ID=EBAY_US
```

Never commit `.env` or paste credentials into source, tests, documentation, screenshots, logs, or error reports.

Run the complete supported test suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
```

The supported test runner is Python's built-in `unittest`; pytest is not required.

Start the application:

```bash
python -m streamlit run app.py
```

The app creates local runtime state under `data/`, `.cache/`, and `output/`. These locations, database files, token caches, logs, and environment files must remain untracked. Bundled sample valuations are demonstration data and are non-actionable unless explicitly verified.

There is no separate build step or package artifact for this local baseline. See `INSTALL.md` for installation troubleshooting. This source repository is shareable, but the application itself remains local-only and is not ready for hosted or multi-user deployment.

## License

CardProfitHunter is available under the [MIT License](LICENSE).

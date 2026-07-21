# CardProfitHunter Local Installation

`README.md` is the canonical setup guide. This project is currently supported only as local, single-user development/controlled-demo software.

## Clean installation

Use Python 3.12 when available; Python 3.11 is also supported.

```bash
cd /path/to/CardProfitHunter
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
```

Edit the local `.env` with eBay sandbox application credentials. Leave `EBAY_ENVIRONMENT=sandbox` until production use is deliberately approved. Never copy `.env` from another project or commit it.

Verify the installation:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
python -m streamlit run app.py
```

pytest is not required; the supported suite uses Python's built-in `unittest` runner.

## macOS TLS warning

If urllib3 reports LibreSSL or an unsupported OpenSSL version, the virtual environment was created with an old system Python. Install a current Python 3.11 or 3.12 distribution, create a new virtual environment from that interpreter, and reinstall `requirements.txt`. Do not suppress the warning or downgrade urllib3 as the launch baseline.

You can inspect the active TLS runtime with:

```bash
python -c "import ssl; print(ssl.OPENSSL_VERSION)"
```

The local SQLite database is created at `data/card_profit_hunter.db`; eBay tokens are cached under `.cache/`; generated CSV files belong under `output/`. These files are local state and must not be committed or shared.

Hosted or multi-user deployment is out of scope. It requires authentication, managed secrets, isolated storage, database migrations and backups, and a privacy review before use.

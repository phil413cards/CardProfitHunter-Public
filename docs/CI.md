# Continuous Integration

The repository runs the standard `unittest` suite on Python 3.11 and
3.12 for pushes and pull requests targeting `develop` or `main`. The workflow
can also be started manually from GitHub Actions.

The workflow:

- grants read-only repository-content permission
- pins official checkout and Python-setup actions to reviewed commit SHAs
- installs the exact direct dependency versions from `requirements.txt`
- runs the canonical test command with bytecode generation disabled
- checks whitespace with `git diff --check`
- fails if a private runtime artifact is tracked

The tracked-artifact guard covers local environment files other than
`.env.example`, virtual environments, Python and test caches, SQLite files,
token-cache filenames, generated output, logs, coverage output, and related
runtime state. It checks paths only and never reads or prints file contents.

No eBay credentials or GitHub secrets are configured for this workflow. Tests
must continue to mock all eBay HTTP activity and use temporary SQLite paths.

Run the same controls locally with:

```bash
python scripts/check_tracked_artifacts.py
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
git diff --check
```

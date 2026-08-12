## Summary

Describe the user-visible outcome and the narrow scope of this change.

## Risk and scope

- [ ] The diff contains only intended files and preserves unrelated work.
- [ ] Scoring, money math, identity matching, valuation status, dashboard
      filtering, eBay behavior, database behavior, and exports are unchanged
      unless explicitly described below.
- [ ] Any behavior change has focused regression coverage.
- [ ] Local-only, single-user boundaries remain intact; no hosted or multi-user
      behavior was introduced without a separate review.

Risk-bearing behavior changed:

<!-- List each changed invariant, or write "None". -->

## Safety checks

- [ ] No `.env`, credential, token, database, cache, log, generated output, or
      private runtime artifact is tracked.
- [ ] No credential, bearer token, raw eBay response, database content, or
      traceback is exposed in tests, logs, screenshots, or documentation.
- [ ] eBay tests use mocks; no live marketplace mutation, purchase, offer, bid,
      or listing action was performed.
- [ ] Database tests use patched temporary paths and do not touch the local
      user database.
- [ ] Verified valuation changes include exact identity, current sold-comparable
      evidence, provenance, expiry, comp count, and conflict regression tests.
- [ ] PASS, WATCH, demonstration, unverified, invalid, and expired rows remain
      nonfinancial.

## Verification

- [ ] `python scripts/check_tracked_artifacts.py`
- [ ] `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v`
- [ ] `git diff --check`
- [ ] The affected Streamlit workflow was smoke-tested when UI code changed.
- [ ] Python 3.11 and 3.12 GitHub Actions jobs pass.

## Evidence and follow-up

Summarize test counts, audit results, known limitations, and any separately
scoped follow-up work.

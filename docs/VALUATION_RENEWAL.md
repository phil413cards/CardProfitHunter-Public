# Valuation Renewal Workflow

Verified valuation rows are intentionally time-limited. Run the local,
read-only renewal audit before a controlled demo and at least weekly while the
app is in active use:

```bash
python scripts/audit_valuations.py
```

The default report treats valuations expiring within 30 days as due soon. A
specific review date or window can be supplied for a reproducible check:

```bash
python scripts/audit_valuations.py --as-of 2026-08-09 --renewal-window-days 30
```

The command reads the valuation CSV, validates its schema, and prints aggregate
counts plus the rows requiring review. It does not call eBay, write the
valuation file, touch SQLite, or create output files.

Continuous integration uses the same read-only audit as a release gate:

```bash
python scripts/audit_valuations.py --fail-on-blocking
```

This mode exits unsuccessfully when a verified valuation is expired or has
missing or invalid provenance. Valuations that are merely due soon remain a
visible warning and do not fail the check. Demonstration and example-only rows
remain non-actionable and do not fail the check.

For each due or expired row:

1. Confirm the exact year, set, card number, player, parallel, variant, and
   grading state.
2. Review current exact-card sold comparables; do not substitute active asking
   prices or a different card identity.
3. Exclude damaged, ambiguous, lot, reprint, and otherwise incompatible sales.
4. Record the source URL, review date, expiry date, and comp count.
5. Keep grading probabilities at zero unless they are supported by a separate
   card-level condition assessment.
6. Run the full test suite before committing renewed values.

Expired, invalid, unverified, demonstration, and example-only rows remain
nonfinancial in the application. The audit is an operational reminder; it does
not weaken that enforcement or make any valuation actionable by itself.

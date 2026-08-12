# CardProfitHunter Known Limitations

This document describes the known limitations of CardProfitHunter 5.2.40 during the Phase 1 beta. The application provides decision support only and should not be treated as a guarantee of authenticity, condition, grading outcome, sale price, or profit.

## Essential beta boundaries

- Local-only.
- Not hosted.
- Not multi-user.
- Not financial advice.
- eBay data may be incomplete or stale.
- Users must verify card identity manually.
- Users must verify shipping, taxes, condition, seller, and market comparables manually.
- No profit is guaranteed.

## Launch scope

- The supported baseline is local-only and single-user.
- Kevin is the only Phase 1 beta tester; there are no outside users yet.
- Hosted, shared, and multi-user deployments are not supported.
- There is no subscription or other paid product offering yet.
- There is no public marketing during Phase 1.
- The Phase 1 goal is to prove usefulness, reliability, and real-world decision quality.
- No result or recommendation may be presented as guaranteed profit.
- The app has no user accounts, authentication, role-based access, or per-user data isolation.
- Buying, bidding, making offers, listing cards, and other eBay account actions are not implemented.
- Phase 1 testing should use bundled sample data or eBay sandbox credentials. Production must be selected deliberately.

## eBay search behavior

- eBay searches require network access and valid application credentials.
- Sandbox inventory and responses may differ substantially from production.
- Empty, partial, failed, and rate-limited searches are possible even when the app is operating correctly.
- The app retries selected rate-limit and server errors, but it cannot guarantee that a search will complete.
- Only fields supplied by the eBay Browse API can be analyzed. Missing required listing data makes a result non-actionable.
- Auctions, classified listings, unknown buying options, unsupported currencies, and incomplete listings are rejected for Phase 1 recommendations.
- OFFER recommendations require explicit best-offer support in the listing data.

## Card identity matching

- Matching is intentionally conservative. Ambiguous listings return PASS rather than attaching an uncertain valuation.
- False negatives are expected when titles omit the year, set, card number, parallel, or other identity details.
- False positives are still possible because seller titles can be inaccurate, incomplete, or unusual.
- The recognized vocabulary for parallels, inserts, reprints, print runs, grading terms, and product names is finite.
- The app cannot inspect a physical card or image to verify authenticity, condition, centering, surface quality, alterations, or the exact parallel.
- Graded and slabbed listings are non-actionable as raw-flip or raw-to-grade opportunities.

## Valuation data

- Card valuations are maintained by the user; the app does not automatically retrieve or verify sold comparables.
- Schema validation can reject malformed data, but it cannot prove that a market value or grading probability is accurate.
- Bundled valuations marked as example, demo, demonstration, unverified, or non-actionable never contribute to financial opportunities.
- A listing can become actionable only when its identity matches a sufficiently specific verified valuation.
- Valuation markets can change faster than the local CSV is updated.

## Profit and ROI modeling

- Profit and ROI are estimates based on configured fees, shipping allowances, grading costs, sale values, and grading probabilities.
- The model does not guarantee the final purchase cost, resale price, sale timing, grading result, or marketplace fees.
- Taxes, currency conversion, import duties, returns, refunds, chargebacks, damage, loss, discounts, and card-specific insurance needs may not be fully modeled.
- Only USD listings are actionable in the current release.
- Unknown or invalid price, shipping, currency, condition, buying-option, or required modeled-cost data forces PASS.
- Suggested offers and max-buy values are calculation limits, not instructions to transact.
- The PSA submission, order tracking, and grading pipeline are not implemented.

## Dashboard and recommendations

- Only BUY, OFFER, BUY_RAW_FLIP, and BUY_GRADE_PSA count as actionable financial opportunities.
- PASS and WATCH rows are non-financial and do not contribute to potential-profit, average-ROI, highest-score, or best-opportunity metrics.
- Scores rank modeled opportunities; they are not measures of certainty or guaranteed quality.
- A dashboard with no actionable rows correctly shows zero or empty opportunity states.

## Local data and privacy

- Saved searches, watchlist entries, run history, and opportunity snapshots are stored in a local SQLite database.
- Anyone with access to the local computer and files may be able to read that data.
- Database backups are manual and may contain private local history.
- History cleanup is manual, requires confirmation, and creates a backup first.
- There is no in-app database restore workflow or automatic backup pruning.
- `.env`, databases, token caches, logs, backups, and generated output must not be committed or shared.

## CSV imports and exports

- Uploaded CSV files must match the required schemas and numeric ranges.
- Spreadsheet-dangerous text is neutralized only when data is written to an app-generated CSV export. Internal values remain unchanged.
- Exported rows can still contain listing titles, seller names, URLs, searches, flags, or notes. Review every export before sharing it.
- CSV export does not make the underlying analysis correct; it only preserves and safely formats the current results.

## Diagnostics and recovery

- User-facing errors and local diagnostics are intentionally sanitized, so low-level exception details are not displayed in the app.
- Diagnostic event codes provide context but may not identify the root cause without reproduction steps.
- Local logging can fail if the filesystem is unavailable or unwritable; the app continues with a sanitized warning.
- A failed run clears or separates current results, but external eBay or network failures may still require a later retry.

## Installation and testing

- Python 3.11 and 3.12 are supported; Python 3.12 is recommended.
- The application runs from source and does not provide a packaged desktop installer or separate build artifact.
- The automated suite uses mocked eBay responses and temporary databases. It does not call the live eBay API.
- Streamlit browser workflows still require manual verification for each beta release.
- Mobile layouts, assistive-technology behavior, and broad cross-platform compatibility have not received a complete formal audit.

Report unexpected behavior using `docs/FEEDBACK_TEMPLATE.md`. Never include credentials, tokens, `.env` contents, SQLite databases, private notes, or raw diagnostic logs in a report.

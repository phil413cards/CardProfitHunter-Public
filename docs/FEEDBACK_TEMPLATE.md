# CardProfitHunter Beta Feedback Template

Use this template to record Kevin's owner-operated Phase 1 beta findings. There are no outside beta users, subscriptions, hosted deployments, or public marketing in this phase. Remove any section that does not apply.

The evaluation goal is to determine whether CardProfitHunter is useful, reliable, and capable of supporting better real-world decisions. Do not interpret or present beta results as guaranteed profit.

Do not include eBay credentials, tokens, `.env` contents, SQLite databases, private watchlist notes, raw diagnostic logs, or screenshots containing sensitive local data.

## Summary

**Short description:**

**Feedback type:** Setup / Usability / Search quality / Incorrect analysis / Missing feature / Export / Crash or error / Other

**Severity:** Blocking / High / Medium / Low

## Test environment

**CardProfitHunter version:**

**Workflow:** Bundled sample analysis / eBay sandbox / Other local workflow

**Operating system and version:**

**Python version (`python --version`):**

**Browser:**

**Installation method:** Fresh clone / Existing checkout

**Did the full test suite pass?** Yes / No / Not run

If tests failed, include only the failing test names and sanitized failure summary. Do not include environment values, local paths, or raw logs.

## Steps to reproduce

1.
2.
3.

**How often does this happen?** Every time / Sometimes / Once

## Expected behavior

Describe what you expected to happen.

## Actual behavior

Describe what happened instead. Include the visible run state: success, empty, partial, or failed.

## Analysis details

Complete this section for matching, recommendation, profit, ROI, or offer feedback.

**Listing description or sanitized title:**

**Expected card identity:**

**Matched card shown by the app:**

**Recommendation shown:** PASS / WATCH / BUY / OFFER / BUY_RAW_FLIP / BUY_GRADE_PSA / Other

**Reason or flags shown:**

**Which value appears wrong?** Identity / Price / Shipping / Fees / Profit / ROI / Suggested offer / Grading estimate / Other

**Why does it appear wrong?**

Do not include private seller communications or unredacted account information. A public eBay item URL is optional and should be reviewed before sharing.

## Diagnostics

**Visible diagnostic event code, if shown:**

**User-facing message:**

Do not paste exception traces, authorization headers, bearer tokens, credentials, `.env` lines, database contents, or the raw `output/logs/application.log` file.

## Usability and documentation

**What was confusing or difficult?**

**Which label, instruction, or workflow should change?**

**Suggested wording or behavior:**

## Beta evaluation

Complete the categories you tested. Write `Not tested` where appropriate.

### Setup problems

Did installation, environment setup, sandbox credentials, tests, or startup fail or feel unclear?

### Confusing screens

Which screen, label, action, result, or status was difficult to understand?

### Search result quality

Were the returned listings relevant to the search? Describe useful results and irrelevant noise.

### False positives

Did the app mark an unsafe or irrelevant listing as actionable? Include a sanitized title, the recommendation, and why it should have been rejected.

### False negatives

Did the app reject or miss a listing that should have been actionable? Explain the expected identity and recommendation.

### Wrong card matches

Did a listing attach to the wrong year, set, card number, parallel, print run, or grading state? Include the expected and displayed identities.

### Bad profit or ROI assumptions

Did any purchase price, shipping, fee, grading cost, sale value, profit, ROI, max-buy, or suggested-offer assumption appear wrong?

### Missing features

What task did you expect to complete but could not?

### Export issues

Did a CSV fail to download, contain incorrect data, open incorrectly, or expose information that should not be exported?

### Crash or error messages

Did the app stop, display an unclear message, or fail to recover? Include the visible sanitized diagnostic event code when available.

### Would you use this again?

Yes / Maybe / No

Why or why not?

### Would you pay for this later?

Yes / Maybe / No

If yes or maybe, what outcome or feature would make it worth paying for? Optionally describe an expected price range or payment model.

## Attachments checklist

Before attaching a screenshot or exported CSV, confirm:

- [ ] No eBay client ID or client secret is visible.
- [ ] No OAuth token, authorization header, or `.env` content is visible.
- [ ] No private notes or unrelated local data is visible.
- [ ] No SQLite database, token cache, or raw log is attached.
- [ ] Any CSV has been reviewed for information you do not want to share.

## Additional context

Add any other detail that would help reproduce or understand the feedback.

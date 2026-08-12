# Beta Decision-Quality Workflow

Use this workflow to measure whether CardProfitHunter improves real-world card
decisions during the owner-operated local beta. It records human review outcomes
without changing recommendations, calling eBay, or writing to SQLite.

## Start a local review file

Copy the tracked header-only template into the ignored output directory:

```bash
mkdir -p output/beta_reviews
cp docs/templates/beta_review_template.csv output/beta_reviews/session-YYYY-MM-DD.csv
```

Keep completed review files local. They can contain listing references, search
context, and private notes and must not be committed or shared without review.

## Run a review session

1. Record one session ID and the UTC review date.
2. Record whether the evidence came from `sample`, `sandbox`, or deliberately
   selected `production` search. Never paste credentials or tokens.
3. Review every BUY, OFFER, BUY_RAW_FLIP, and BUY_GRADE_PSA result in the
   selected run.
4. Review a consistent sample of PASS and WATCH rows from the same run. This is
   required to observe false negatives, not just false positives.
5. Verify the exact card identity, current valuation evidence, shipping and
   other modeled costs, seller details, condition, return terms, and listing
   availability manually.
6. Record `human_verdict` as `actionable`, `non_actionable`, or `uncertain`.
   This is a review label, not permission to buy or make an offer.
7. Record identity as `correct`, `incorrect`, or `unknown`; money assumptions as
   `reasonable`, `unreasonable`, or `unknown`; and usefulness as `useful`,
   `not_useful`, or `unknown`.
8. Select one issue category. Use `none` when no issue was found.

Supported issue categories are `none`, `false_positive`, `false_negative`,
`wrong_card_match`, `bad_profit_roi_assumption`, `search_result_quality`,
`export_issue`, `crash_error`, `missing_feature`, and `other`.

## Summarize the evidence

Run the read-only summarizer:

```bash
python scripts/summarize_beta_review.py \
  --input output/beta_reviews/session-YYYY-MM-DD.csv
```

The command validates the complete CSV before reporting aggregate counts. Local
review files are limited to 5 MB and 5,000 rows. The command does not print
listing references or notes, call eBay, modify the review file, write SQLite,
or create an output report.

The confusion-matrix labels mean:

- `true_positive`: the app and human review both marked the listing actionable;
- `false_positive`: the app marked it actionable and human review did not;
- `true_negative`: the app and human review both marked it non-actionable; and
- `false_negative`: the app marked it non-actionable but human review found it
  actionable.

`uncertain` human verdicts remain in the total but are excluded from precision
and recall. `not_available` means the reviewed evidence did not contain a valid
denominator for that metric.

## How to use the results

Treat every false positive, wrong-card match, unreasonable money result, crash,
or privacy concern as a concrete investigation ticket. Review false negatives
for usefulness improvements without weakening established safety gates.

Do not set or claim a launch-quality threshold from a small or biased sample.
Compare multiple sessions, keep the selection method consistent, and retain the
underlying local evidence for manual review.

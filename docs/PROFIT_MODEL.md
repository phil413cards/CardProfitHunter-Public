# Total-Modeled-Cost Profit Model

CardProfitHunter uses a conservative expected-cost model for private local
decision support. It is not accounting, tax, grading, or financial advice.
Replace the bundled assumptions with rates supported by your own location,
selling account, promotion strategy, return history, and grading history.

## Required settings

All percentage settings are decimal rates. For example, `0.10` means 10%.
Zero is valid when a cost genuinely does not apply, but a missing, nonnumeric,
negative, nonfinite, or greater-than-100% value blocks financial actions.

| Setting | Controlled-demo default | Meaning |
| --- | ---: | --- |
| `purchase_tax_pct` | 0.10 | Tax applied to listing price plus inbound shipping |
| `promoted_listing_fee_pct` | 0.05 | Expected promoted-listing fee applied to modeled sale value |
| `return_defect_allowance_pct` | 0.05 | Expected return, defect, refund, and dispute loss applied to modeled sale value |
| `grading_loss_risk_pct` | 0.01 | Expected total-loss/damage allowance applied to PSA-path capital at risk |

The existing `ebay_fee_pct`, outbound shipping allowances, grading fee, and
grading shipping/insurance remain required modeled costs. Marketplace,
promoted-listing, and return/defect percentages may not exceed 100% in total.

## Raw-flip formula

Let:

- `A` = purchase price plus inbound/listing shipping
- `T` = purchase-tax rate
- `S` = verified raw sale value
- `F`, `P`, `R` = marketplace, promoted-listing, and return/defect rates
- `O` = raw outbound shipping and packaging allowance

Then:

```text
raw total modeled cost = A × (1 + T) + S × (F + P + R) + O
raw profit = S - raw total modeled cost
raw ROI = raw profit / raw total modeled cost
```

## PSA formula

The expected PSA sale value is still the probability-weighted PSA 10, PSA 9,
and lower-grade outcome. Let `G` be grading fee plus grading
shipping/insurance, `L` be grading loss risk, and `O` be PSA-sale outbound
shipping:

```text
PSA capital at risk = A × (1 + T) + G
grading loss allowance = PSA capital at risk × L
PSA total modeled cost = PSA capital at risk
                       + grading loss allowance
                       + expected sale value × (F + P + R)
                       + O
PSA profit = expected sale value - PSA total modeled cost
PSA ROI = PSA profit / PSA total modeled cost
```

`grading_loss_risk_pct` represents loss, damage, or claim risk while capital is
in the grading path. It does not represent an ordinary lower grade; lower-grade
outcomes are already included in the expected sale value.

## Max-buy and offers

Raw and PSA max-buy amounts solve the same formulas against both minimum profit
and minimum ROI thresholds. Suggested offers derive from those risk-adjusted
max-buy amounts, then retain the configured safety margin and verified raw
market-value cap. No purchase-price-only ROI or offer calculation remains.

## Known approximation

eBay states that final value fees are based on the total amount of a sale and
that selling costs can include ad fees and refunds. CardProfitHunter applies
percentage selling costs to its modeled sale value because future buyer tax,
collected shipping, fixed order fees, and account-specific fee details are not
known at sourcing time. Treat results as screening estimates and verify actual
account costs before buying.

Official reference: <https://www.ebay.com/help/selling/fees/selling-fees?id=4822>

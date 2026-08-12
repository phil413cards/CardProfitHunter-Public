# CardProfitHunter 5.2.41

CardProfitHunter is a Python/Streamlit application for finding and evaluating sports-card listings from eBay. It normalizes Browse API results, applies conservative card-identity matching, models raw-flip and PSA-grading economics, and stores local searches, run outcomes, and opportunity snapshots in SQLite.

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
git clone https://github.com/phil413cards/CardProfitHunter-Public.git CardProfitHunter
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

The supported test runner is Python's built-in `unittest`; pytest is not required. A discovery-completeness regression check prevents module-level pytest-style tests from being silently skipped by the canonical command.
The suite includes an isolated Streamlit startup smoke test that copies runtime inputs to a temporary directory, blocks outbound HTTP, and creates only temporary database and log state.

Start the application:

```bash
python -m streamlit run app.py
```

The app creates local runtime state under `data/`, `.cache/`, and `output/`. These locations, database files, token caches, logs, generated CSVs, and environment files must remain untracked. On POSIX systems, writable runtime directories are restricted to `0700`; database, backup, `.env`, token-cache, diagnostic-log, and generated CSV files are restricted to `0600`. Symlinked private runtime targets are rejected. Generated CSV files are spreadsheet-sanitized and atomically replaced so a failed save leaves the prior file intact. Never copy or share private runtime files. Bundled sample valuations are demonstration data and are non-actionable unless explicitly verified.

Settings and Card Values edits are validated, written to an exclusive temporary file, re-read for validation, and atomically replaced. A failed save leaves the prior tracked file intact and reports a sanitized local error.

Sample Analysis CSV uploads are limited to 5 MB each. Listing and valuation inputs are also capped at 1,000 rows and 64 columns so malformed or unexpectedly large files fail with a sanitized validation message before analysis.

Live-search results must contain positive trading-card evidence before they can become raw-card or unverified Scout candidates. Ambiguous memorabilia such as signed baseballs, photos, coins, books, and mini helmets is filtered instead of being ranked as a card opportunity. Scout candidates remain non-financial and still require manual identity, condition, seller, and sold-comparable review.

Sealed products and multi-card inventory—including retail and hanger boxes, cases, packs, tins, complete sets, and card bundles—are also excluded from single-card Scout results. Legitimate single-card condition wording such as `pack fresh` remains eligible.

Multi-quantity listings are excluded even when they otherwise describe a desirable raw card. This includes quantity multipliers, quantity fields, pairs, multiple copies, numeric or word-based card counts, mixed/bulk lots, and choose-multiple listings. Single-card numbers, serial numbers, achievement phrases such as `2X MVP`, and `Pick 2 Card` identity wording remain eligible.

Uncut card sheets, panels, strips, press/sell/proof/promo sheets, sticker or tattoo sheets, and other clearly multi-card sheet products are excluded through the single-card product boundary. Printing plates, individual proof cards, named panel relic cards, and card names such as `Sheet Metal` remain eligible.

Choice-menu inventory is non-actionable when the listing requires the buyer to select which card is received. `U Pick`, choose/select-one, list/menu/dropdown selection, card-of-your-choice, complete-your-set, per-card pricing, and individually sold card wording are excluded from search recommendations, Scout, and financial analysis. Card identities such as Draft Picks, First Overall Pick, Panini Select, Photo Variation, and Choice parallels remain eligible.

Strong non-card object terms override card-brand words during classification. Branded signed balls, photos, helmets, jerseys, bats, pucks, coins, and books remain excluded, while explicit card constructs such as signed baseball cards, jersey-patch autos, coin cards, photo variations, relic cards, and booklets remain eligible.

Card accessories, empty packaging, and card-related services are also excluded when the title identifies the accessory or service rather than a purchased card. This includes display stands and frames, holders sold alone, storage products, supply lots, wrappers or labels only, grading/cleaning/authentication services, and replacement labels. Normal shipping-protection wording such as `Ships In Toploader`, `With Penny Sleeve`, or `One Touch Included` remains eligible for an otherwise valid card listing.

Redemption cards, rewards or points cards, code cards, QR/digital codes, and Home Run Challenge code products are excluded from both Scout and financial analysis. These items are not treated as the underlying collectible card and cannot receive valuation or profit fields.

Custom, replica, reproduction, unlicensed, counterfeit, fan-art, ACEO, novelty, homemade, fake, and bootleg listings are excluded. Titles that disclose trimming, alteration, restoration, added color, or minimum-size problems are also non-actionable and cannot attach financial fields.

Additional unofficial-card wording—including not/non-licensed, fan-made, handmade, ORICA, parody-card, AI-generated-card, concept-card, and aftermarket-card listings—is excluded through the same authenticity boundary. Legitimate officially licensed, Fanatics-exclusive, hand-numbered, artist-proof, and named insert/parallel wording remains eligible.

Autograph wording such as `auto`, `autograph`, `autographed`, and `signed` is recognized consistently for raw-card discovery and parsing. Financial identity matching remains conservative: generic signed wording is not treated as interchangeable with a verified manufacturer-autograph valuation.

Presale, preorder, not-in-hand, not-yet-released, stock-image, representative-image, non-actual-item, and image-may-vary listings are excluded from Scout and financial recommendations. The launch workflow requires an immediately available listing with photos of the actual card.

Listings that affirmatively disclose material card defects—including scratches, print lines, off-centering, dents, dimples, edge/corner wear, soft corners, surface issues, whitening, chipping, scuffing, peeling, staining, creasing, fading, or paper loss—are non-actionable. Explicit no-defect wording such as `No Damage`, `No Scratches`, and `Scratch Free` is preserved for discovery.

Randomized products—including mystery boxes, mystery cards, repacks, grab or blind bags, random cards/hits/players/teams, surprise products, hot packs, and chase packs—are excluded. Scout and financial recommendations require the listing to identify the specific card being purchased.

Break participation and opening-service listings—including player/team/division breaks, break spots, pick-your-team/player formats, rip-and-ship offers, live rips, and box/case/pack openings—are excluded from search recommendations, Scout, and financial analysis. Legitimate card names containing `Breakout`, `Breakaway`, `Record Breaking`, or `Unbreakable` remain eligible.

Missing or malformed listing titles, conditions, and search text fail closed across parsing, relevance filtering, Scout ranking, and financial analysis. Pandas-style missing values such as `NaN` and `pd.NA` are treated as absent data rather than converted into artificial title or condition text.

Financial BUY and OFFER actions require a named seller with at least 100 feedback ratings and at least 99.0% positive feedback. Missing, malformed, or below-threshold seller data returns PASS and exposes no valuation, profit, ROI, max-buy, or suggested-offer fields. Opportunity and watchlist persistence independently enforce the same rule, while dashboard and history reads fail closed on legacy rows that lack qualifying stored seller data without rewriting that history. Seller return terms still require manual review before purchase in this private controlled-demo baseline.

Third-party grading and slab labels are recognized consistently across parsing, classification, Scout filtering, and financial analysis. Compact, spaced, and hyphenated labels from PSA, Beckett/BGS/BVG/BCCG, SGC, CGC/CSG, TAG, HGA, GMA, ISA, KSA, AGS, MNT, FCG, Arena Club, Rare Edition, and Degree Grading remain non-actionable as raw-card opportunities. Generic slab, encapsulated, and professionally graded wording is also blocked, while unrelated raw-card wording such as player names and product-line terms remains eligible.

Financial valuation rows must include structured provenance: `verification_status=verified`, ISO `verified_at` and `expires_at` dates, an HTTPS `source_url`, and a positive integer `comp_count`. Expired rows remain visible for review but cannot generate BUY or OFFER recommendations. Demonstration and unverified rows remain non-financial.

Profit, ROI, max-buy, and suggested-offer calculations use the same total-modeled-cost assumptions, including purchase tax, promoted-listing fees, expected return/defect loss, and grading loss risk. Review the configurable defaults and formulas in `docs/PROFIT_MODEL.md` before acting on any result.

## Local database recovery

The Setup tab can create, verify, and restore full SQLite backups under `output/database_backups/`. Restore accepts only a local backup with a valid integrity check, the supported schema version, the required tables and columns, and no foreign-key violations. It requires both explicit verification and confirmation, then creates a separate safety backup of the current database before atomically replacing it. No backup or restore runs automatically.

Database startup and backup verification also check the required table columns, foreign-key declarations, and index definitions. A truly empty database is initialized normally, while an incompatible unversioned or damaged database fails closed instead of being silently adopted or rewritten.

Backups contain private local history. Keep them local, do not commit or share them, and verify the selected filename before restoring. A restore replaces saved searches, search history, watchlist rows, and opportunity snapshots with the selected backup's contents.

There is no separate build step or package artifact for this local baseline. See `INSTALL.md` for installation troubleshooting. This repository is a sanitized, shareable source copy with clean public history; the application itself remains local-only and is not ready for hosted or multi-user deployment.

## Phase 1 beta

- [Phase 1 Beta Guide](docs/PHASE_1_BETA_GUIDE.md)
- [Feedback Template](docs/FEEDBACK_TEMPLATE.md)
- [Known Limitations](docs/KNOWN_LIMITATIONS.md)

## License

CardProfitHunter is available under the [MIT License](LICENSE).

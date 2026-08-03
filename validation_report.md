# Validation report (50-review holdout, hand-labeled)

**Methodology note:** the human labeler used descriptive free-text labels
("High price", "Wrong item delivered + poor support", "Product Quality", etc.)
rather than the fixed taxonomy slugs. Barrier labels were translated into the
8-slot taxonomy via a disclosed, fixed lookup table (below) - a standard
qualitative-coding step, not a per-review judgment call; every substantive
call (does this review show a barrier, and which one) was made by the human.
`categories_mentioned` was left unscored: the human's "Category" column
described issue types (Price, Product Quality, Customer Support & Returns),
not one of the 12 product categories, and guessing at products the reviewer
didn't actually name would defeat the point of validation. Because of this,
the exact-match rate below is structurally deflated (it requires categories
to match too, and human categories are always empty) - **the per-barrier
precision/recall table is the meaningful result, not the exact-match number.**

**Barrier mapping used:** price/discount/surge-charge/offer complaints ->
`price_perception` · quality/expired/melted/torn/warm/unsealed complaints ->
`trust_quality` · wrong-item/no-returns/refund-refused/faulty-no-support ->
`past_bad_experience` · out-of-stock/wants-more-variants -> `assortment_doubt`
· "None (Positive)" -> no barrier.

**7 of 50 reviews described issues with no fit in the 8-barrier taxonomy** and
were scored as "no barrier": no-cash-on-delivery (payment method), 4x
Hindi/Kannada language-support requests, a missing "no bag" checkout feature,
and "not available in my area." These are the AI over-predicting relative to
a taxonomy gap, not a tagging error - worth noting as a real taxonomy
limitation surfaced by validation, particularly the repeated language/
localization complaints.

**Exact-match rate (categories AND barriers both match exactly): 34%** (see caveat above)

## Per-barrier precision/recall

| label               |   support |   precision |   recall |
|:--------------------|----------:|------------:|---------:|
| assortment_doubt    |         2 |        0.50 |     1.00 |
| awareness           |         0 |        0.00 |   nan    |
| occasion_mismatch   |         0 |        0.00 |   nan    |
| past_bad_experience |        11 |        0.69 |     1.00 |
| price_perception    |        10 |        0.90 |     0.90 |
| trust_quality       |        10 |        1.00 |     0.50 |
| ux_findability      |         0 |        0.00 |   nan    |

**Reading this:** `price_perception` is reliable both ways (90/90). `past_bad_experience`
has perfect recall but only 69% precision - the AI applies it somewhat more
broadly than a human would (consistent with the earlier self-consistency
finding that this label is the most batch-context-sensitive of the eight).
`trust_quality` is precise when used (100%) but under-triggered (50% recall) -
the AI sometimes folds quality complaints into `past_bad_experience` instead
of `trust_quality`. `assortment_doubt`, `awareness`, `occasion_mismatch`, and
`ux_findability` have too little support (0-2 reviews) in this holdout to
say anything meaningful about them.

## Per-category precision/recall

Not scored this run - see methodology note above.

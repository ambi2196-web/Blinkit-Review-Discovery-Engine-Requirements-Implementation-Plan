# AI self-consistency check (50/50 holdout reviews re-tagged)

**This is NOT human validation.** It measures whether the tagger gives the same answer to itself under a different context (single-review call vs. the original's batch-of-25 context) and mild sampling variation (temperature 0.4 vs. the original's 0). It tells you the tagger is *stable*, not that it's *correct* - for correctness, human-labeled validation (`--score`) is still needed.

**Exact-match rate between the two runs: 32%**

## Per-barrier agreement

| label               |   agree_rate |   run1_only |   run2_only |   both |
|:--------------------|-------------:|------------:|------------:|-------:|
| assortment_doubt    |         0.94 |           3 |           0 |      1 |
| awareness           |         0.96 |           2 |           0 |      0 |
| occasion_mismatch   |         0.98 |           1 |           0 |      0 |
| past_bad_experience |         0.76 |          11 |           1 |      5 |
| price_perception    |         0.88 |           6 |           0 |      4 |
| trust_quality       |         0.96 |           2 |           0 |      3 |
| ux_findability      |         0.98 |           0 |           1 |      1 |

## Per-category agreement

| label                   |   agree_rate |   run1_only |   run2_only |   both |
|:------------------------|-------------:|------------:|------------:|-------:|
| electronics_accessories |         0.98 |           1 |           0 |      2 |
| fresh_produce           |         0.96 |           1 |           1 |      2 |
| grocery_staples         |         0.74 |          12 |           1 |      3 |
| home_kitchen            |         0.96 |           2 |           0 |      0 |
| pharma_wellness         |         1    |           0 |           0 |      2 |
| snacks_beverages        |         0.94 |           3 |           0 |      1 |
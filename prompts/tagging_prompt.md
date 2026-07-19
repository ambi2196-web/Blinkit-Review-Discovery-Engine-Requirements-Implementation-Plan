You are tagging user reviews of Blinkit (an Indian quick-commerce grocery app) for a product research pipeline studying why users don't explore new categories beyond their habitual repeat purchases.

For each review in the input batch, produce one tag object. Return ONLY a single JSON object of this exact shape, no markdown fences, no commentary:

```
{"tags": [
  {
    "id": "<the review id, copied exactly from input>",
    "relevant": true | false,
    "sentiment": "positive" | "negative" | "neutral" | "mixed" | null,
    "categories_mentioned": ["<category>", ...] | [],
    "barrier_type": ["<barrier>", ...] | [],
    "discovery_channel": "search" | "browse" | "reorder" | "offer" | "word_of_mouth" | "none_stated" | null,
    "segment_signals": ["<segment>", ...] | [],
    "verbatim_quote": "<best quote, <=25 words, original language preserved>" | null
  },
  ...
]}
```

`relevant` = true only if the review says something about category/product-discovery behavior: why the user buys what they buy, what stops them trying something new, how they found a product, a frustration tied to a specific product/category, or a segment-revealing detail. Pure delivery-time/payment/app-crash/customer-support complaints with no product or category substance are `relevant: false`.

If `relevant` is false, set every other field to its null/empty value (sentiment: null, categories_mentioned: [], barrier_type: [], discovery_channel: null, segment_signals: [], verbatim_quote: null). Do not guess at fields for irrelevant reviews.

## Category taxonomy (use exactly these 12 slugs, only ones actually referenced)
grocery_staples, fresh_produce, snacks_beverages, household_cleaning, personal_care, beauty_cosmetics, baby_care, pet_supplies, pharma_wellness, electronics_accessories, home_kitchen, festive_seasonal

## Barrier taxonomy (use exactly these 8 slugs, only ones actually evidenced - can be multiple or empty)
1. `habit_autopilot` - reorders from list/buy-again, never browses
2. `trust_quality` - doubts freshness/authenticity/expiry in a category
3. `price_perception` - believes category is cheaper elsewhere (kirana/DMart/Amazon)
4. `awareness` - didn't know Blinkit sells that category
5. `occasion_mismatch` - buys that category on a different cadence/channel (monthly supermarket run)
6. `assortment_doubt` - assumes limited/wrong selection in that category
7. `ux_findability` - category exists but hard to find/search/suggests wrong things in app
8. `past_bad_experience` - tried once, failed (wrong item, damaged, refund pain)

## Discovery channel
How the user found the product they're talking about, if stated: `search`, `browse`, `reorder` (buy-again/list), `offer` (promo/discount drove the purchase), `word_of_mouth`, or `none_stated` if not mentioned.

## Segment signals
Free-form but short slugs inferred from context, e.g. `parent`, `pet_owner`, `student`, `bulk_buyer`, `late_night`, `price_sensitive`. Leave empty if nothing is inferable - don't force one.

## Few-shot examples

Input:
```
{"id": "ex1", "text": "this waste app if I am searching for rose water but this blinkit app showing suggestion of kewra water, how can this app put rose water and kewra water in same suggestion category and for replacement they only looking our complaint and not resolving. this is worst app i ever seen . we can for zepto, Swiggy insta mart, big basket and new app.", "rating": 1, "source": "play_store"}
```
Output:
```
{"tags": [{"id": "ex1", "relevant": true, "sentiment": "negative", "categories_mentioned": ["grocery_staples"], "barrier_type": ["ux_findability"], "discovery_channel": "search", "segment_signals": [], "verbatim_quote": "showing suggestion of kewra water"}]}
```

Input:
```
{"id": "ex2", "text": "no customer help never useful. i hate this app worst experience i ordered gift wrapping roll but got small pieces and applied for return but was refused", "rating": 1, "source": "play_store"}
```
Output:
```
{"tags": [{"id": "ex2", "relevant": true, "sentiment": "negative", "categories_mentioned": ["festive_seasonal"], "barrier_type": ["past_bad_experience"], "discovery_channel": "none_stated", "segment_signals": [], "verbatim_quote": "ordered gift wrapping roll but got small pieces"}]}
```

Input:
```
{"id": "ex3", "text": "Google pay not working here", "rating": 1, "source": "play_store"}
```
Output:
```
{"tags": [{"id": "ex3", "relevant": false, "sentiment": null, "categories_mentioned": [], "barrier_type": [], "discovery_channel": null, "segment_signals": [], "verbatim_quote": null}]}
```

Input (Hinglish):
```
{"id": "ex4", "text": "hamesha grocery aur snacks hi order karti hoon list se, kabhi doosri category try nahi ki, pata hi nahi kya kya milta hai isme", "rating": 4, "source": "play_store"}
```
Output:
```
{"tags": [{"id": "ex4", "relevant": true, "sentiment": "neutral", "categories_mentioned": ["grocery_staples", "snacks_beverages"], "barrier_type": ["habit_autopilot", "awareness"], "discovery_channel": "reorder", "segment_signals": [], "verbatim_quote": "kabhi doosri category try nahi ki, pata hi nahi kya kya milta hai"}]}
```

Now tag the following batch. Return ONLY the JSON object, one tag per input review, same order, ids copied exactly.

---
name: mtg-data-ecosystem
description: Use when writing or reviewing MTG Analyzer code that integrates external MTG data sources (EDHREC recommendations, Commander Spellbook combos, Moxfield/Archidekt/TappedOut decklists), parses deck or inventory files (Arena/Moxfield/Archidekt text, ManaBox/Deckbox CSV), or implements the recommendation / deck-construction engine — covers each source's access method, ToS cautions, file formats, and the recommendation algorithm design.
---

# MTG data ecosystem, file formats & recommender design

**Rule:** Only **Scryfall** and **Commander Spellbook** are sanctioned/documented for programmatic
use. EDHREC, Moxfield, Archidekt, TappedOut JSON endpoints are **unofficial** — cache aggressively
(refresh nightly, not per query), throttle, send a descriptive User-Agent, never redistribute their
bulk data. Isolate each behind an adapter interface so we degrade gracefully to Scryfall-only.
**Key everything to Scryfall `oracle_id`.**

## EDHREC — recommendation statistics

De-facto Commander aggregator (crawls public decklists). **No official API**; backed by public
static JSON on `json.edhrec.com` (no key):

| Pattern | Returns |
|---|---|
| `json.edhrec.com/pages/commanders/<slug>.json` | top + high-synergy cards, composition |
| `json.edhrec.com/pages/commanders/<timeframe>.json` | top commanders (`week`/`month`/`year`/`all`) |
| `json.edhrec.com/pages/average-decks/<slug>.json` | average decklist, avg price, type counts |
| `json.edhrec.com/pages/cards/<slug>.json` | per-card associations / similar cards |

Slug: lowercase, strip punctuation, hyphenate spaces (`Atraxa, Praetors' Voice` →
`atraxa-praetors-voice`). `AccessDenied` XML = bad slug, not a rate limit. Each cardview has `name`,
**`id` (Scryfall UUID — join key)**, `num_decks`, `inclusion`, `synergy`, `label`, `price`.
**Library:** `pip install pyedhrec` (`get_high_synergy_cards`, `get_top_cards`,
`get_commanders_average_deck`, `get_card_combos`; 24 h cache). Caution: undocumented internal JSON,
can change/lock down — cache nightly, pair with Scryfall for actual card data.

## Commander Spellbook — combo / interaction detection

Free, **open-source (MIT)**, real REST API. Base `https://backend.commanderspellbook.com/`
(docs `/schema/redoc/`, `/schema/swagger/`). Combos stored as structured **variants**:
`uses` (specific combo cards) · `requires` (generic templates, e.g. "Man-Land that Enters Untapped")
· `produces` (results — flag any "Infinite…" / "Win the game") · `identity` · `manaNeeded` ·
prerequisites · `legalities` · `prices` · `popularity`.

| Endpoint | Purpose |
|---|---|
| `/find-my-combos` | GET/POST a decklist → combos present + "almost there" |
| `/variants/` | full combo DB (DRF paginated, `limit`/`offset`, ≤1000/page) |
| `/card-list-from-text`, `/estimate-bracket` | decklist parsing + bracket estimate |

`/find-my-combos` response buckets: `included` (fully present), `almost_included` (missing exactly
one piece), `almost_included_by_adding_colors`, `included_by_changing_commanders`. Diff `uses`/
`requires` vs the deck to name the missing piece; label via `produces`. **Bulk:** the single-file
dump was removed (~2024) — page `/variants/?limit=1000&offset=N` into a local cache, or **self-host
the MIT backend** (Docker) for the most robust local option. Backend repo:
github.com/SpaceCowMedia/commander-spellbook-backend. Combo data is fan content (attribute, don't
resell).

## Other decklist sources

- **Archidekt** (unofficial, tolerated): `GET archidekt.com/api/decks/<id>/` (full JSON incl.
  categories/commander); `GET /api/decks/cards/` (search). Throttle, cache, set UA.
- **Moxfield**: real API (`api2.moxfield.com`) but **locked down ~Nov 2024** — anonymous/automated
  blocked; needs an allow-listed UA via their support. **Don't depend on it** — accept pasted exports.
- **TappedOut**: no modern API; export via URL params (`?fmt=txt` most reliable). Treat as scraping.
- **MTGGoldfish**: **no API**, Cloudflare-protected — avoid. Use Scryfall `prices` instead.

## Deck & inventory file formats (ingest)

**Decklist lines** — one tolerant parser handles `.txt`/Arena/Moxfield/Archidekt/MWS:
`[SB:] N[x] Name [(SET) Number]` + section headers (`Deck`/`Sideboard`/`Commander`/`Companion`) or
blank-line separators + `//` comments. Arena/Moxfield/Archidekt share `1 Sol Ring (LTC) 284`; the
`(SET) #` suffix disambiguates the printing (name-only is ambiguous — Sol Ring has dozens).

**Inventory CSVs** (parse by **header name**, not column position):
- **ManaBox** (target first — has set code + collector # *and* `Scryfall ID`): columns include
  `Name, Set code, Collector number, Foil, Quantity, Scryfall ID, Condition, Language, ...`.
- **Deckbox**: `Count, Name, Edition, Card Number, Condition, Foil, ...`.
- **Moxfield collection**: `Count, Name, Edition, Condition, Foil, Collector Number, ...`.

**Canonical resolution priority:** `Scryfall ID → (set code + collector #) → (name + set) →
name-only (flag ambiguous)`. Report unresolved lines.

## Recommendation engine — four-stage funnel

1. **Candidate generation** (union, dedupe by `oracle_id`, drop in-deck): EDHREC top + high-synergy
   for the commander; co-occurrence/CF neighbors from a decklist corpus (if available); Scryfall
   theme/`otag:` queries per category gap.
2. **Score** each candidate:
   `w_fit·lift + w_cf·Σsim + w_gap·gap[cat] + w_curve·curveGap + w_theme·themeMatch + w_owned·owned − w_price·pricePenalty`
   (normalize components). EDHREC **lift** = ratio `P(card | commander) / P(card | color identity)`
   (>1 = positive association; stable for staples) is the primary "fit"; **synergy** (the
   difference) is the human-readable explanation. α-blend fit↔theme for cold-start commanders
   (`α = n_decks/(n_decks+k)`, k≈50).
3. **Hard filters:** color-identity legal, not banned, singleton, ≤ budget (unless owned).
4. **Rank + diversify:** category quotas / MMR so output fills gaps (not 15 mana rocks). Attach
   explanations ("+72% synergy, fills ramp gap 6/10, owned, $0").

**Co-occurrence/CF** (if a local decklist corpus is built): decks=rows, cards=cols → sparse binary
matrix `M`; co-occurrence `C = Mᵀ·M`; item-item cosine; down-weight popularity via PMI/lift. EDHREC
gives aggregate stats, **not** raw decklists — initially rely on EDHREC lift/synergy alone; optionally
build a small corpus from Archidekt search later.

**Budget substitution:** price via Scryfall `prices.usd` (min across reprints since we key on
`oracle_id`); for expensive card T find S with same function tag + identity + lower price, scored by
tag overlap + CMC closeness + oracle-text similarity. Owned cards → price 0 + owned bonus.

**Deck construction from inventory:** fill category/curve targets (see `commander-format` skill)
using owned cards first, then recommend buys for gaps; optionally seed from EDHREC average deck ∩
inventory.

Sources: github.com/stainedhat/pyedhrec · backend.commanderspellbook.com/schema/redoc · github.com/SpaceCowMedia/commander-spellbook-backend · manabox.app/guides/collection/import-export · edhrec.com/articles/from-synergy-to-lift

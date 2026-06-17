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

`/find-my-combos` response buckets (camelCase): `included` (fully present), `almostIncluded`
(missing one), `almostIncludedByAddingColors`, `includedByChangingCommanders`, plus `identity`.
Request body is a `DeckRequest`: `{"main":[{"card":"Name","quantity":1}], "commanders":[…]}` — cards
are **objects**, not bare strings. Diff `uses`/`requires` vs the deck to name the missing piece;
label via `produces`. Each `uses[].card` carries `oracleId` (join to Scryfall). `requires` are
generic templates with a `scryfallQuery`; find-my-combos resolves them server-side.

**Verified live (2026-06): ~92k variants total / ~90.5k commander-legal.** `/variants/` caps `limit`
at **100** (not 1000) and disables `count` unless `?count=true`; `q=legal:commander` and
`q=card:"Name"` filters work; follow `next` for pagination (pass `params=None` when following it —
an empty `params={}` strips the query and infinite-loops).
**Do NOT mirror the whole DB by paging** (~900 requests) — it trips an aggressive rate limit / IP
cooldown and is poor citizenship. Prefer **on-demand + cache**: live find-my-combos per deck
(authoritative, always current, covers all 90k server-side) and `q=card:"…"` per card. For a true
offline mirror, **self-host the MIT backend** (Docker, github.com/SpaceCowMedia/commander-spellbook-backend).
Combo data is fan content (attribute, don't resell).

## Other decklist sources

- **Archidekt** (unofficial, tolerated): `GET archidekt.com/api/decks/<id>/` (full JSON incl.
  categories/commander); `GET /api/decks/cards/` (search). Throttle, cache, set UA.
- **Moxfield**: real API (`api2.moxfield.com`) but **locked down ~Nov 2024** — anonymous/automated
  blocked; needs an allow-listed UA via their support. **Don't depend on it** — accept pasted exports.
- **TappedOut**: no modern API; export via URL params (`?fmt=txt` most reliable). Treat as scraping.
- **MTGGoldfish**: **no API**, Cloudflare-protected — avoid. Use Scryfall `prices` instead.

## Deck & inventory file formats (ingest)

**Decklist lines** — one tolerant parser handles `.txt`/Arena/Moxfield/Archidekt/MWS:
`[SB:] N[x] Name [(SET) Number] [*F*] [[Category]]` + section headers (`Deck`/`Sideboard`/
`Commander`/`Companion`/`Maybeboard`) or blank-line separators + `//` comments. Constrain the
trailing `(SET) #` so a card name with parentheses (e.g. `Erase (Not the Urza's Legacy One)`) isn't
misparsed: the set code is short and space-free.

**Verified from real exports (2026-06):**
- **ManaBox deck `.txt`** marks sections with **comment-markers** — `// COMMANDER` then the
  commander, a **blank line**, then the unmarked mainboard. Treat `// <SECTION>` as a section header
  (not a skipped comment); let a blank line end a commander block.
- **Archidekt deck CSV** is **headerless + positional** (18 cols): `qty, name, set name, set code,
  category, label, deck-section, finish, collector#, modifier, color, mv, rarity, scryfall id, type,
  price, ownership, oracle text`. The commander = the row with **category == "Commander"**; other
  categories are functional tags (Land/Ramp/Removal — handy for Phase 3 analysis). Detect it (col 0
  is an int, col 13 a UUID). **A `.csv` may be a deck OR a collection — route by content, not
  extension.**

**Inventory/collection CSVs** (parse by **header name**, not column position):
- **ManaBox** collection: `Name, Set code, Collector number, Foil, Quantity, Scryfall ID,
  Condition, Language, ...` (Foil values `normal`/`foil`/`etched`).
- **Deckbox**: `Count, Name, Edition, Card Number, Condition, Foil, ...`.
- **Moxfield collection**: `Count, Name, Edition, Condition, Foil, Collector Number, ...`.

**Resolution priority: NAME first** → oracle_id (a card name maps uniquely to a gameplay identity;
that's all resolution needs — store printing details verbatim). Then `Scryfall ID` →
`(set code + collector #)` as fallbacks. *Do NOT try set+collector before name:* the local bulk DB
holds one representative printing per card, so a `(set, collector)` from an export can match a
*different* card's representative printing and mis-resolve (this split Sol Ring across two oracle_ids
in testing). Report unresolved lines; don't drop them.

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

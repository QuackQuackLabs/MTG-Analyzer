---
name: scryfall-api
description: Use when writing or reviewing any code in MTG Analyzer that fetches Magic card data, rulings, prices, or images from Scryfall — covers the base URL, required headers, rate limits, bulk-data downloads, the card object's analysis-relevant fields, double-faced-card handling, the search syntax, card identification/batch lookup, color-identity rules, and licensing.
---

# Scryfall API reference (verified against live api.scryfall.com, 2026-06-17)

Scryfall is the **sanctioned, documented, free** source of MTG card data. For this local tool,
**ingest bulk data into SQLite and query locally**; use the live API only for autocomplete, fuzzy
single-card resolution, and ad-hoc searches.

## Base, auth, headers, rate limits

- Base URL: `https://api.scryfall.com` (HTTPS, TLS 1.2+). Images: `https://cards.scryfall.io`;
  bulk files: `https://data.scryfall.io`.
- **No authentication / API key.** The read API is fully public. (OAuth exists only for write access
  to user-owned data — not used here.)
- **Required headers — requests without them are rejected (403):**
  - `User-Agent: MTGAnalyzer/0.1 (jacob@quackquacklabs.com)` — must identify our app; don't let the
    HTTP library set a default.
  - `Accept: application/json` (or `*/*`).
- **Rate limit:** keep under ~10 req/s; insert a **~100 ms delay** between requests. `/cards/search`
  is tighter (~2 req/s). On HTTP `429`, back off (≈30 s). Errors return an object with
  `"object":"error"`, `status`, `code`, `details` — always check the `object` field.

## Bulk data — primary path for a local tool

`GET /bulk-data` → list of `bulk_data` objects, each with `type`, `name`, `updated_at`, `size`,
`download_uri` (gzip), `content_encoding`. **Regenerated ~every 12 h** — poll, compare `updated_at`,
download only when it changes. Don't hardcode `download_uri`s.

| `type` | size (~) | use |
|---|---|---|
| `oracle_cards` | ~176 MB | **Primary DB** — one object per `oracle_id` (deduped gameplay identity). |
| `default_cards` | ~547 MB | Add only if you need per-printing price/set/image. |
| `rulings` | ~25 MB | All rulings, join on `oracle_id`. |
| `all_cards` | ~2.5 GB | Every printing/language — overkill. |

**Plan:** Oracle Cards + Rulings as the core; add Default Cards (or a printings table) for
prices/images. Files are gzipped JSON — handle `content_encoding: gzip`.

## Card object — fields that matter for analysis

`name` · `oracle_id` (**primary join key**, stable across printings) · `id` (specific printing) ·
`mana_cost` · `cmc` (float "mana value") · `type_line` · `oracle_text` · `colors` (≠ identity) ·
**`color_identity`** (governs Commander legality, see below) · `keywords` · `legalities` (map; check
`legalities.commander` ∈ `legal`/`not_legal`/`banned`/`restricted`) · `prices` (`usd`,`usd_foil`,
`eur`,`tix`; strings or null) · `set`/`set_name` · `collector_number` (string) · `image_uris`
(`small`/`normal`/`large`/`png`/`art_crop`) · `card_faces` (array; see DFC below) · `produced_mana`
(for ramp/mana-base analysis) · `power`/`toughness`/`loyalty` (strings, may be `*`) · `layout` ·
`game_changer` (bool — bracket signal) · `edhrec_rank` · `reserved` · `rulings_uri`.

**Double-faced / multi-face handling:** branch on `layout`
(`transform`/`modal_dfc`/`split`/`adventure`/`flip`/`meld`). For those, `mana_cost`, `oracle_text`,
`image_uris`, and P/T/loyalty live on **each `card_faces` entry**, NOT the top level. But `cmc`,
`color_identity`, `legalities`, and `keywords` stay at the **top level** — trust them there.

## Color identity (Commander-critical)

A card's color identity = colors in its mana cost **plus** any colored mana symbols in its rules text
(and color indicators), regardless of frame color. Scryfall's top-level **`color_identity`** is
already computed correctly — use it directly. Commander legality = `legalities.commander == "legal"`
**AND** `card.color_identity ⊆ commander.color_identity`. (e.g. Command Tower has empty
`color_identity` despite producing all colors → legal anywhere.)

## Search — `/cards/search`

`GET /cards/search?q=<urlencoded>` → paginated (175/page; follow `next_page` while `has_more`).
Params: `unique` (`cards`/`prints`/`art`), `order` (`name`/`cmc`/`edhrec`/`usd`/`released`), `dir`.

Key operators: `id:`/`identity:` (color identity, with `<=` "fits in", `>=`, `=`) · `c:`/`color:` ·
`t:`/`type:` · `o:`/`oracle:` (`fo:` includes reminder text) · `f:commander` · `is:` (`is:commander`,
`is:dual`, `is:permanent`) · `mv:`/`cmc:` · `pow:`/`tou:` · `r:` · `produces:` · `otag:`/`oracletag:`/
`function:` (Tagger function tags — `otag:ramp`, `otag:removal`, `otag:card-advantage`,
`otag:board-wipe`, `otag:tutor`, `otag:counterspell`) · `-` negation. Color nicknames: guilds
(`azorius`), shards (`esper`), wedges (`mardu`), `c` colorless.

Examples: fits a Jeskai deck → `q=id<=jeskai f:commander`; legal Sultai commanders →
`q=is:commander id:sultai`; cheap green ramp → `q=id<=g t:creature mv<=2 produces>=1 f:commander`.
Tags are high-precision/low-recall — back them with oracle-text regex.

## Identification & batch lookup

- Exact: `GET /cards/named?exact=Sol+Ring` · Fuzzy (typo-tolerant): `?fuzzy=sol+rng` (+`set=`).
- Autocomplete (UI typeahead): `GET /cards/autocomplete?q=<partial>` (≤20 names).
- Set+number: `GET /cards/{set}/{collector_number}` · By Scryfall id: `GET /cards/{id}`.
- **Batch:** `POST /cards/collection` with `{"identifiers":[...]}`, **max 75 per request**.
  Identifier forms: `{"id"}`, `{"oracle_id"}`, `{"name"}`, `{"name","set"}`, `{"set","collector_number"}`.
  Response has `data` (order not guaranteed) + `not_found`. Chunk parsed decklists into 75s.

## Rulings

`GET /cards/{id}/rulings`, `/cards/{set}/{number}/rulings`, or `/cards/{oracle_id}/rulings`. Each
`ruling` has `oracle_id`, `source` (`wotc`/`scryfall`), `published_at`, `comment`. Prefer the bulk
Rulings file joined on `oracle_id`.

## Licensing

Free under WotC's Fan Content Policy (NOT CC0). Allowed: this non-commercial local tool. **Do not**
paywall/gate the data, repackage/proxy it as a service, crop the artist/copyright line off images,
recolor/distort images, or imply Scryfall/WotC endorsement. If showing `art_crop`, surface the
artist + copyright elsewhere. Cache images locally rather than hotlinking at scale. Crediting
Scryfall is good practice.

Docs: scryfall.com/docs/api · /rate-limits · /bulk-data · /syntax · /api/cards · /api/cards/collection · /docs/terms

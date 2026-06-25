# Format tag + enrichment cleanup — implementation spec

## Goal

Add a **multi-value, overlapping `content_formats`** tag (a video can be both `meme` and
`ugc`), wired to search as a hard filter + fuzzy semantic signal. Along the way, put two
already-paid-for-but-unused Gemini fields to work and stop paying for three dead ones.

Designed product-agnostic: 100% skincare data today, but the vocab and prompt generalize to
the planned categories (beauty / food / electronics / gym).

---

## Decisions (settled)

| Decision | Choice | Rationale |
|---|---|---|
| Format cardinality | **multi-value** (`jsonb` array) | formats overlap; mirrors existing `age_brackets` |
| Vocabulary | **Core 13**, strict enum | cross-category coverage without fragmentation |
| Which LLM pass | **cheap text pass** (`audience_enrichment.py`) | backfills existing rows with no video re-download/vision cost; reads `ai_description` which already encodes visual cues |
| Legacy `content_format` (singular) | **supersede, keep column** | new field is authoritative + wired to search; old left as harmless legacy, droppable later |
| Format → which embedding | **search** space (already wired there via old field — upgrade it) | format is a literal descriptor, not an audience/vibe abstraction |
| `production_quality` | **icp** embedding | abstract aesthetic; pairs with `visual_style` |
| `emotional_drivers` | **icp** embedding | inferred persuasion psychology; pairs with `primary_emotion` |
| `has_product` | **filter + format signal**, NOT embedded | boolean fragments embeddings; use as format-detection input |
| `time_product_was_mentioned`, `has_text_overlay`, `is_trending_format` | **drop from Gemini schema/prompt** | unused, low/no signal; stop paying tokens |

### Format vocabulary (Core 13)

```
talking_head, ugc, product_montage, voiceover, meme, grwm,
unboxing, tutorial, testimonial, before_after, skit, listicle, asmr
```

All product-agnostic. Cross-category sanity check:
- **beauty:** grwm, product_montage, before_after, tutorial, testimonial, asmr, talking_head
- **food:** tutorial (recipe), product_montage (plating), asmr, listicle, testimonial
- **electronics:** unboxing, tutorial (setup), product_montage, testimonial, listicle
- **gym:** before_after, tutorial (workout), testimonial, ugc, talking_head

---

## Changes by file

### A. Stop generating the 3 dead fields — `src/instaagent_pipeline/ad_enrichment.py`

Persisting is driven by `PAID_AD_ANALYSIS_COLUMNS` (line 475:
`payload = {key: analysis.get(key) for key in PAID_AD_ANALYSIS_COLUMNS if key in analysis}`).
Remove the three fields from **all three** spots so Gemini stops being asked and they stop persisting:

1. `PAID_AD_ANALYSIS_COLUMNS` (lines 45–66) — delete `has_text_overlay`, `is_trending_format`,
   `time_product_was_mentioned`. **Keep `has_product`** (now used by format detection).
2. `ENRICHMENT_SCHEMA.properties` (lines 75–114) — delete the same three keys.
   (`required` is the `PAID_AD_ANALYSIS_COLUMNS` spread, so it updates automatically.)
3. `ENRICHMENT_PROMPT` (lines 139–154) — delete the bullet lines for the three fields.

DB columns stay (harmless legacy); they just stop being written. No migration needed to drop them.

### B. Format tagging in the cheap text pass — `src/instaagent_pipeline/audience_enrichment.py`

This pass already does text-only enrichment over `ai_description` + `transcript`. Fold format in:

1. Add the vocab constant:
   ```python
   CONTENT_FORMATS = (
       "talking_head", "ugc", "product_montage", "voiceover", "meme", "grwm",
       "unboxing", "tutorial", "testimonial", "before_after", "skit", "listicle", "asmr",
   )
   ```
2. `AUDIENCE_SCHEMA` — add a multi-value enum property (mirror `age_brackets`):
   ```python
   "content_formats": {"type": "array", "items": {"type": "string", "enum": list(CONTENT_FORMATS)}},
   ```
   and add `"content_formats"` to `required`.
3. `PROMPT_TEMPLATE` — add a category-neutral instruction line + feed `has_product` as a hint:
   ```
   - content_formats: an array of EVERY production format that applies (they overlap), each one of
     {formats}. Definitions span product types — e.g. product_montage = polished shots of the
     product with no person on screen (a serum bottle, a sneaker, a gadget, a plated dish);
     ugc = casual phone-shot creator style; talking_head = a person speaking to camera.
   ```
   Also pass `has_product` into the prompt context (helps disambiguate `product_montage`).
   → add `has_product` to `SELECT_COLUMNS` (line 63) and into `_call_audience_llm`'s `.format(...)`.
4. `_normalize` (lines 178–211) — add
   `"content_formats": _enum_list(analysis.get("content_formats"), CONTENT_FORMATS)`.
5. Skip-logic: the pass skips rows where `target_generation` is already set (line 112). Since we're
   adding a new field to existing rows, run with `--overwrite` once to backfill format onto rows
   already audience-enriched (see rollout).

### C. Migration — `supabase/migrations/020_content_formats.sql`

```sql
-- Phase 6: multi-value production-format tag (overlapping), derived by the text-only
-- audience pass (audience_enrichment.py). Supersedes the legacy single-value content_format
-- (left in place as harmless legacy). jsonb array like age_brackets.
alter table item_enrichments add column if not exists content_formats jsonb;
```

If `item_enrichments` is the SQL view (migration 016) rather than a base table, add the column to
the underlying `paid_ads` / `ugc_items` analysis tables and thread it through the view's SELECT —
confirm which during implementation. (Audience fields in 018 alter `item_enrichments` directly, so
follow that exact precedent.)

### D. Search backend

**`src/instaagent_pipeline/api/search.py`**
- `_ENRICH_FULL_COLUMNS` (line 387) — append `,content_formats`.
- `_to_video_result` (lines ~426–429) — add `"content_formats": enr.get("content_formats") or []`.
- `_assemble` signature (lines 262–266) + `want_formats` set + overlap filter (mirror `want_brackets`,
  lines 269 / 309):
  ```python
  want_formats = {s.strip().lower() for s in content_formats} if content_formats else None
  ...
  if want_formats is not None and not (want_formats & {f.lower() for f in result.get("content_formats") or []}):
      continue
  ```
- Thread `content_formats` through the call sites (lines 144, 245) like `age_brackets`.

**`src/instaagent_pipeline/api/routes_search.py`**
- `SearchRequest` (line ~22): `content_formats: Optional[list[str]] = None  # multi-select, overlap match`.
- Pass `content_formats=req.content_formats` into the search call (line ~54).

### E. Embeddings — `src/instaagent_pipeline/embeddings.py`

**Format → search space (upgrade existing line, don't add a new one):**
- `SEARCH_TAG_FIELDS` line 385 currently `("format", "content_format")`. Change to read the new
  multi-value field: `("format", "content_formats")`. `flatten_jsonish` already handles arrays.
- `ENRICHMENT_SELECT_COLUMNS_BASE` (lines 32–36) — add `content_formats`; remove the legacy
  `content_format` if fully cut over (optional — leaving it costs nothing).

**`production_quality` + `emotional_drivers` → icp space:**
- `ICP_TAG_FIELDS` (lines 360–367) — append:
  ```python
  ("quality", "production_quality"),
  ("drivers", "emotional_drivers"),
  ```
- `ENRICHMENT_SELECT_COLUMNS_BASE` — add `production_quality, emotional_drivers` (and
  `content_formats` per above). These already exist as columns; just select them.

### F. Frontend — `frontend/`

**`app/search/page.tsx`**
- Add constant (mirror `AGE_BRACKETS`, line 27):
  ```ts
  const CONTENT_FORMATS = ['talking_head','ugc','product_montage','voiceover','meme','grwm',
    'unboxing','tutorial','testimonial','before_after','skit','listicle','asmr']
  ```
- State: `const [formats, setFormats] = useState<Set<string>>(new Set())` (line ~52).
- Request body (line ~79): `content_formats: formats.size ? Array.from(formats) : null`.
- UI: a `<ChipFilter label="Format" .../>` next to Age/Language (line ~200).
- Result chips (lines ~306–312): render `r.content_formats`.

**`lib/types.ts`** — add `content_formats?: string[] | null` to `SearchFilters`; `content_formats: string[]`
to the video result type.

**`lib/api.ts`** — thread `content_formats` through `searchAds()`.

---

## Rollout order (with cost notes)

1. **Migration 020** — add `content_formats` column. *(free)*
2. **Backend code** — B, D, E. Ship behind no flag; empty arrays until enriched.
3. **Drop dead fields** — A. *(saves Gemini tokens on all future enrichment)*
4. **Backfill format** — `enrich-audience --overwrite` over the library. *(cheap text LLM, no video
   re-download)*
5. **Re-embed** — rebuild **both** spaces:
   - `search` space: format tag now reads `content_formats`.
   - `icp` space: now includes `production_quality` + `emotional_drivers`.
   *(Voyage embed pass — cheap relative to vision; not free)*
6. **Re-cluster icp** — icp embeddings get clustered (`clustering.py`); icp text changed, so
   re-run clustering. *(OpenRouter label calls)*
7. **Frontend** — F. Ship the Format chips last, once data exists.

## Tests to update
- `tests/test_ad_enrichment.py` — assert the 3 dropped fields are gone from schema/prompt;
  `has_product` retained.
- `tests/test_search.py` — `content_formats` overlap filter (matches any, drops rows lacking it).
- Audience enrichment test (fixtures) — `content_formats` normalized to vocab, junk values dropped.

## Open item to confirm during build
- Whether `item_enrichments` is a base table (alter directly, per 018) or a view over
  `paid_ads`/`ugc_items` (add to base tables + view SELECT). Migration 016 defines it — check there.

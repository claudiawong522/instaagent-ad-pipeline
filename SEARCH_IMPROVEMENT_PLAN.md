# Search Improvement Plan — Niche-Query Fix

## BUILD STATUS (2026-06-24)
**DONE & verified live (71 tests pass):** Phase 1 (icp text = persona/audience/generation/tone/style/emotion via `ICP_TAG_FIELDS` + `build_icp_text`; `content_tone`/`visual_style` added to `ENRICHMENT_SELECT_COLUMNS`), Phase 2 (both-space recall + Voyage `rerank-2.5`, cosine floor replaced by `rerank_min_score=0.5`; `config.py` rerank knobs; `embeddings.rerank()`), Phase 3 (`search.expand_query` via OpenRouter), and `days_live` (paid `running_duration` → result + `min_days_live` filter, route field added). **icp space embedded for the first time** (run `362039a6-d91f-4dc3-a36a-538e152785ca`, 90 vectors — it had 0 before).
- Live results: `scientific` 0→3, `comedy` 0→3, `before and after` 0→34, `genz` 0→1, `professional`→13; variable counts confirmed (`skincare` 61 > `oily skin` 16). `days_live` 12–483d, `min_days_live=300`→2 paid. `meme` still 0 (skincare-only corpus; needs Phase 4 humor/audience tagging).

**Phase 4 CODE DONE (2026-06-24), pending migration apply:** migration `supabase/migrations/018_audience_fields.sql` (adds `target_generation`/`price_positioning`/`age_brackets`/`languages` to item_enrichments); `audience_enrichment.py` (text-only LLM pass over ai_description+transcript, enum-constrained, upserts on item_type,item_id) + CLI `enrich-audience --run-id <id> [--source --overwrite --dry-run]`; `target_generation` wired into icp embed (ENRICHMENT_SELECT_COLUMNS) and `languages`/`age_brackets`/`price_tier` filters wired into search (`_enrichments` select, `_to_video_result`, `_assemble`, `SearchRequest`). **All selects use a 400-fallback** so search keeps working before migration 018 is applied (verified: 71 tests pass). `rerank_candidate_pool` raised 50→100 (was capping broad queries on the 93-item corpus).
**REMAINING (3 steps, needs the user — no direct DB/DDL access from here):** (1) apply `018` in Supabase SQL editor; (2) `python -m instaagent_pipeline.cli enrich-audience --run-id 362039a6-d91f-4dc3-a36a-538e152785ca`; (3) re-embed icp so target_generation lands: delete existing icp rows for the run then `embed-items --run-id <id> --space icp` (or they're skipped as existing).

**Phase 5 frontend DONE (2026-06-25, type-checks clean):** `frontend/app/search/page.tsx` adds age-bracket + language multi-select chips (`ChipFilter`), price-tier dropdown, type-scoped engagement inputs (min views = UGC-only, min days-live = paid-only, conditionally rendered by item type), relabeled the score badge to "% relevance" (it's the rerank score), and surfaces `days_live` + audience badges (price/generation/age/language) on each card. `lib/types.ts` (`VideoResult` audience fields + `SearchFilters`) and `lib/api.ts` (`searchAds` body) wired to the existing backend filter params. Audience fields stay empty in the UI until migration 018 + enrich-audience run (backend already 400-falls-back).

**ROLLOUT COMPLETE (2026-06-25):** migration 018 applied; all 93 rows have audience fields (`enrich-audience` data present: 76 genz/16 millennial/1 boomer, price 26 budget/63 mid/3 premium/1 luxury, age_brackets + languages populated); icp space deleted + re-embedded (93 vectors) so `build_icp_text` now includes `generation:` (verified). End-to-end search verified live: `genz`→70 all-genz, `price_tier=premium`→3 premium, `age 13-17`+`Spanish` overlap→1, `min_days_live=300`→4 paid-only (days_live 364–800). Migration `019_icp_hnsw_index.sql` (icp HNSW perf index) is OPTIONAL at this corpus size — not yet applied; run standalone (`CREATE INDEX CONCURRENTLY`, no transaction) when the corpus grows. **The whole search-improvement project is now done.**

**PERF: query expansion DISABLED by default (2026-06-25).** A warm search was ~6.2s, dominated by two serial AI round-trips: query expansion (gemini-3-flash, ~2.3s) and Voyage rerank (~2.7s). A/B over `genz/comedy/meme/before-and-after/skincare/oily skin` showed expansion changed **zero** results (identical sets, same top, jaccard 1.00) — the enriched icp space + reranker already surface the right candidates, and the 100/space candidate pool covers the whole 93-item corpus. New flag `config.query_expansion_enabled` (env `QUERY_EXPANSION_ENABLED`, default `0`) gates `expand_query`. Result: warm search ~6.2s→~2.7–3.1s (~55% faster), cold ~10s→~5s, same 80 results. Re-enable once the corpus outgrows the candidate pool (expansion's recall benefit returns when KNN starts leaving candidates out). Next lever if more speed needed: rerank is now the dominant cost (~2.7s) — trim the rerank doc (drop transcript) or shrink the pool.

---
# Search Improvement Plan — Niche-Query Fix (original)

**Goal:** Fix search returning nothing for niche queries (`genz`, `old woman`, `dry skin`, `meme`, `comedy`, `scientific`, `professional`). Make one search bar that queries two embedding spaces, expands the query, reranks, and gates results by a *calibrated* relevance score.

---

## Diagnosis (already verified, do not re-investigate)

Live experiments against the corpus (93 search-space embeddings, all skincare/beauty) showed **three** root causes:

1. **The 0.30 cosine floor (`config.search_min_similarity`) gates correct matches.** The KNN *finds* the right video but it's cut off. Measured: `scientific`→0.294 (top hit was literally the "laboratory experiment" video, killed by 0.006), `comedy`→0.332, `before and after`→0.27, `meme`→0.273. Working queries: `dry skin`→0.53, `skincare`→0.66. Cosine scales with query length, so short queries land ~0.05–0.15 lower → a fixed cosine floor is mis-calibrated and punishes short niche queries.

2. **The embedded text lacks abstract-attribute vocabulary.** `build_search_text` indexes literal visual description + product tags, with no words for tone/humor/audience-generation. Experiment: appending explicit `audience/tone/humor` tags lifted matches +0.06 to +0.13 (`meme` 0.27→0.40, `comedy` 0.42→0.52, `genz` 0.11→0.23).

3. **Corpus is tiny & single-niche** (`old woman` returns nothing because there are none). Data problem — out of scope here.

## Design decisions (settled with user)

- **One search bar**, not two. Query **both** the `search` space (what's in the video) and the `icp` space (audience/tone). No intent router — searching both + reranking handles mixed queries without a misroute failure mode.
- **Query expansion**: rewrite the query with a cheap fast model before embedding (`"genz"` → `"gen z, young, casual, trendy"`), fixing short-query dilution at the source.
- **Reranker**: Voyage **`rerank-2.5`** ($0.05/1M tokens, 200M free/month — effectively free at this scale) reads query+doc together and produces a *calibrated* relevance score.
- **Final cut is by rerank score, NOT a fixed count.** Variable output: `skincare` returns many, `oily skin` returns few, `watermelon` returns none. Keep a max cap (~100) as a rare ceiling. The cosine floor goes away — the reranker's score is the trustworthy bar.
- **Embed vs filter split**:
  - **Embedded (icp space):** `content_tone`/`visual_style` (style), `target_generation`, `persona`, `primary_emotion`.
  - **Filter (categorical, exact cuts):** `language` (multi, jsonb array), `age_brackets` (**multi-select**, jsonb array — a video can target/depict several age groups), `price_positioning` (single) (+ existing platform/views/virality). Multi-value filters use array-overlap (OR) matching.
  - **Performance filters are type-scoped (not cross-type):** UGC → `virality_score` (engagement÷views %, `recompute_virality` in `normalizers.py`) + `views`; **Paid → `running_duration`** (numeric, **days** the ad has been live = longevity = a "this creative works" proxy). VERIFIED LIVE: column is **`running_duration`** (migration 005, written by `normalize_apify_ad` → `apify_running_duration_days`), populated 76/76 on the live DB. NOTE: the `running_duration_days` column + `paid_ads_longevity_idx` from migration 001 were superseded and **do not exist on the live table** — use `running_duration`; it has **no index** (fine at 76 rows; add `create index ... on paid_ads(running_duration desc)` if the corpus grows). Each metric is `None` for the other type, so a virality/views filter drops all paid and a days-live filter drops all UGC — surface them as type-scoped in the UI. The **rerank score is the primary cross-type sort**; these are secondary "proven creative" filters.
- Dropped from scope: campaign-objective scoring, video re-download, more data, humour-as-separate-field (folded into style), skin-type (too product-specific).

## Key fact — most columns already exist

`item_enrichments` **already has** columns (verified in migrations): `content_tone`, `visual_style`, `persona` (jsonb), `target_demographic`, `primary_emotion`, `age` (int), and a language column (`creator_language` / `languages`). These are emitted by the vision prompt in `ad_enrichment.py` / `ugc_enrichment.py`.

- **No re-enrichment needed** to use tone/style/persona/emotion/age/language — just wire them into the embed-text builder / filters.
- **Only genuinely new:** `target_generation` and `price_positioning` → need new columns + a **text-only** enrichment pass over stored `ai_description`+`transcript` (NOT a video re-watch).

---

## Relevant files (verified locations)

- `src/instaagent_pipeline/embeddings.py` — `build_search_text`, `build_icp_text`, `SEARCH_TAG_FIELDS`, `embed_query`, `ENRICHMENT_SELECT_COLUMNS`, `EMBEDDING_SPACES=("icp","search")`, `embed_items`, `vector_literal`, `request_json` usage.
- `src/instaagent_pipeline/api/search.py` — `search_ads` (does the RPC + hydrate + `_assemble`), `MAX_RESULTS`, uses `config.search_min_similarity`.
- `src/instaagent_pipeline/api/routes_search.py` — `SearchRequest` pydantic model, `/search` endpoint.
- `src/instaagent_pipeline/config.py` — `search_min_similarity=0.30`, `embedding_model="voyage-4-lite"`, `voyage_api_key`, `openrouter_*`, `claude_*`.
- `supabase/migrations/017_match_min_similarity.sql` — `match_item_embeddings` RPC (cosine KNN with `p_min_similarity`).
- `src/instaagent_pipeline/ad_enrichment.py` — vision enrichment, `PAID_AD_ANALYSIS_COLUMNS`, prompt + JSON schema. `ugc_enrichment.py` — UGC version (reuses `PAID_AD_ANALYSIS_COLUMNS`).
- `frontend/` — Next.js search UI (single search bar).
- `.env` has `VOYAGE_API_KEY`, `OPENROUTER_API_KEY`, `SUPABASE_*`. Config `load_dotenv` strips key whitespace.

---

## Implementation phases (in order)

### Phase 1 — Enrich the `icp` space text (biggest recall win)
1. **`embeddings.py` → `ENRICHMENT_SELECT_COLUMNS`**: add `content_tone, visual_style` (persona, target_demographic, primary_emotion already selected).
2. **`embeddings.py` → `build_icp_text`**: currently only `persona + target_demographic`. Expand to a labeled tag block (mirror `build_search_text` style) including: persona, target_demographic, content_tone (label "style"/"tone"), visual_style, primary_emotion, and (once Phase 4 lands) target_generation. Keep field order fixed.
3. Verify the columns are actually populated for existing rows (quick Supabase select); if sparse, they'll fill on next enrichment.

### Phase 2 — Search both spaces + add the reranker
4. **`config.py`**: add `rerank_model="rerank-2.5"`, `rerank_min_score` (start ~0.5, tune), `rerank_candidate_pool` (~50). Keep `search_min_similarity` but **set the RPC call's `p_min_similarity=0.0`** (let rerank be the gate) — or repurpose it as a loose floor (~0.15) just to bound the candidate pool.
5. **`embeddings.py`**: add `rerank(query, documents)` calling Voyage `POST /v1/rerank` (`https://api.voyageai.com/v1/rerank`, body `{query, documents, model, top_k}`, Bearer `voyage_api_key`) — mirror `embed_query`'s `request_json` pattern. Returns indices + relevance_scores.
6. **`api/search.py` → `search_ads`**: 
   - Run the KNN **twice** (or via one RPC call per space): `p_space="search"` and `p_space="icp"`, each `p_limit=rerank_candidate_pool`, `p_min_similarity=0.0`.
   - Pool + dedupe candidates by `(item_type,item_id)` (keep best cosine for tie-context).
   - Hydrate candidates (existing `_hydrate`/`_enrichments`).
   - Build a rerank document per candidate from its `source_text` (or ai_description+tags+transcript) and call `rerank(expanded_query, docs)`.
   - **Gate by `rerank_min_score`** (variable count), cap at `MAX_RESULTS`/a config cap. Order by rerank score. Put the rerank score on each result (replace/augment `similarity`).
   - Apply secondary filters (platform/virality/views — existing) + the new categorical filters from Phase 4.

### Phase 3 — Query expansion
7. **New helper** (e.g. `api/search.py` or a small module): `expand_query(config, query) -> str`. One call to `google/gemini-3-flash-preview` via OpenRouter (already wired) OR `claude-haiku-4-5`. Prompt: "Expand this search query into a short comma-separated list of synonyms and related concepts for semantic video search. Query: {q}". Keep it small + fast; cache per-query if trivial. Fall back to the raw query on error/timeout.
8. Call `expand_query` before `embed_query` in `search_ads`. Embed the expanded text; also pass the expanded (or original) query to the reranker — test which reranks better (likely original or lightly-expanded).

### Phase 4 — New abstract fields (text-only enrichment)
9. **Migration** `018_audience_fields.sql`: `add column if not exists target_generation text, price_positioning text, age_brackets jsonb` to `item_enrichments`. (`languages` jsonb already exists; the old single-int `age` is superseded by `age_brackets` — leave `age` in place, don't filter on it.)
10. **New text-only enrichment pass** (new function, e.g. `enrich_audience_text.py` or extend `ugc_enrichment`): for rows missing the fields, send stored `ai_description`+`transcript` to a text LLM (gemini-flash/haiku) with a JSON schema → `target_generation` (gen_z|millennial|gen_x|boomer|mixed), `price_positioning` (budget|mid|premium|luxury), `age_brackets` (**array**, items enum: 13-17|18-24|25-34|35-44|45-54|55+ — "every age group the video targets or prominently depicts"), and backfill `languages` if null. **No video download.** New CLI cmd e.g. `enrich-audience`. Constrain every categorical value with a JSON-schema `enum` so values can't fragment.
11. Wire `target_generation` into `build_icp_text` (embed) and `languages`/`age_brackets`/`price_positioning` into the filter path (array-overlap for the multi-value ones).

### Phase 5 — API + Frontend
12. **`routes_search.py` → `SearchRequest`**: add optional filter fields — `languages: list[str]`, `age_brackets: list[str]` (both multi-select), `price_tier: str` (single), `min_days_live: int` (paid performance, mirrors existing `min_virality`/`min_views` for UGC).
13. **`api/search.py`**: (a) add `running_duration` (the verified-populated column; NOT `running_duration_days`, which doesn't exist live) to `PAID_HYDRATE_COLUMNS`; in `_to_video_result` paid branch expose it as `days_live` (UGC branch keeps `virality`/`views`). (b) `_assemble`: apply the new categorical filters (mirror existing `platform`/`min_views` checks). Multi-value filters (`languages`, `age_brackets`) match by **array overlap (OR)** — keep the row if any of its values is in the selected set; `price_tier` is exact-match. `min_days_live` is paid-only, `min_virality`/`min_views` are UGC-only (each `None` for the other type).
14. **`frontend/`**: single search bar stays. Surface new filters next to existing platform/views: `age_brackets` and `language` as **multi-select checkboxes**, `price_tier` as a single dropdown. Show rerank score instead of cosine.

---

## Re-embedding & rollout steps (run after code changes)
- Apply migration `018` in Supabase SQL editor.
- (Phase 4) Run `enrich-audience` to populate target_generation/price_positioning (+ backfill age/language).
- Re-embed the `icp` space: `embed-items --space icp` (new `build_icp_text` output needs new vectors). The `search` space is unchanged (untouched) unless you also enrich its text.
- Backend: `uvicorn instaagent_pipeline.api.app:app --reload`. Frontend: `npm run dev` in `frontend/`.

## Verification (the experiment harness already exists — see git stash / scratchpad pattern)
Re-run the niche queries (`genz`, `old woman`, `dry skin`, `meme`, `comedy`, `scientific`, `professional`, `before and after`) end-to-end and confirm:
- `scientific` / `comedy` / `before and after` / `meme` now return their correct top video (rerank score above bar).
- `genz` returns gen-z-coded content (after Phase 4).
- `skincare` returns *more* results than `oily skin` (variable count proves the score-gate works, not a fixed N).
- `old woman` still returns ~nothing (data gap — expected).
- A nonsense query (`watermelon`) returns nothing.

## Recommended build order
Phase 1 → 2 (the big recall + calibrated-threshold win) → 3 (expansion) → 4 (new fields) → 5 (API/UI polish). Phases 1–3 likely fix most failing queries on their own; measure before doing 4.

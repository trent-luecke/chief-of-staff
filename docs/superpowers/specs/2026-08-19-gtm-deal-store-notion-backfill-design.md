# GTM Deal Store — Notion Backfill (one-shot import) — Design

**Date:** 2026-08-19
**Project:** chief-of-staff
**Status:** Design (ready for implementation plan)
**Parent design:** `docs/superpowers/specs/2026-08-18-gtm-deal-store-phase1a-design.md` (§8 follow-on: backfill t-0867b7)
**Depends on:** Phase 1a + 1b (deal spine, fold, review surface, pipeline board) — all merged to `main`.
**Tracked:** Registry project `gtm-producer-deal-data-foundation`.

## 1. What this is

A **one-shot import** of the ~111 legacy Notion pipeline records into the event-sourced
deal store, so the Registry UI pipeline board and review surface reflect the *whole*
pipeline instead of just newly-folded demos. After it runs, **Notion is retired** from
the deal path: new deals come only from the nightly demo feed and the review surface.

This closes the gap the Phase 1a design flagged: the projection can't become a true
superset of the live pipeline until the historical records live in the deal store.

### Decisions locked during shaping (do not relitigate)

1. **One-shot import, Notion retired.** Not an ongoing sync. Consequence: there is no
   path to add a *pre-demo* lead after this until an "add deal" action exists in the
   Registry UI — tracked as a **follow-up**, out of scope here.
2. **Cache-snapshot-driven, not live-Notion.** The backfill reads a
   `data/pipeline_cache.json` snapshot the user produces via the normal sync path; the
   script never calls Notion. (The `.env` `NOTION_TOKEN` is expired; sync happens through
   the claude.ai Notion connector.) This decouples the import from Notion auth and makes
   it testable against a fixture.
3. **A new `seed` DealEvent kind** carries each record's imported state; the fold honors a
   seed's stage/outcome as ground truth **only while a component has no real
   demo/trial/sale events**. Real events supersede it later.
4. **Keying:** normalized email when the record has one (~91/111 do), else a stable
   synthetic `notion:<page_id>`. Seeds carry a Notion account name, so they do **not**
   flood the identity review queue.
5. **Clean-slate stale clock:** open seeds anchor their 45-day review clock to the
   *import date*, so nothing floods the 45-day queue on day one; only post-import
   inactivity surfaces them. The real `Last Contacted` is preserved for board display.

## 2. Architecture — two decoupled steps

```
Step 0 (human, once)                 Step 1 (script, idempotent)
────────────────────                 ───────────────────────────
sync-pipeline-cache skill            scripts/backfill_deals.py
  → data/pipeline_cache.json           reads pipeline_cache.json (snapshot)
    (all ~111 records)                  → normalize_seed_events(leads, import_ts)
                                          → list[DealEvent] (kind="seed")
                                        → append_events(registry_storage, events)
                                          → data/deal_events.jsonl (git-anchored)
                                             │
                                             ▼  next fold (existing)
                                        build_deals()  ── board + review surface
                                                          reflect all ~111 deals
```

The board and review surface need **no change** — they already fold `deal_events.jsonl`
via `GET /api/deals` and `GET /api/deals/review`. Seeds flow through automatically once
they're in the log.

## 3. Components (each independently testable)

### 3.1 `lib/deal_status_map.py` — Notion status → (stage, outcome) (pure)

`map_notion_status(status: str) -> tuple[str, str]`. Exact mapping over the live
Status vocabulary (8 values; the 2 currently-unused values are handled for
future-proofing). Unknown/blank status → `("demoed", "open")` (defensive, never raises).

| Notion Status | stage | outcome |
|---|---|---|
| `Demo Scheduled` | demoed | open |
| `No-Show` | demoed | open |
| `Out of Demo / Need Upate` *(sic — Notion's spelling)* | demoed | open |
| `No Trial / Post Demo` | demoed | open |
| `On-Hold` | demoed | open |
| `In-Trial / Post Demo` | in_trial | open |
| `Closed` | won | won |
| `Lost` | lost | lost |
| *(anything else / empty)* | demoed | open |

Notes: `On-Hold` is not modeled as a snooze — the clean-slate clock (§3.4) governs when
it re-surfaces. `in_trial` is a valid stage the board already renders (an empty column
today); backfill is the first thing to populate it.

### 3.2 `lib/deal_backfill.py` — `normalize_seed_events` (pure)

`normalize_seed_events(leads: list[dict], import_ts: str) -> list[DealEvent]`.
For each cache lead:
- **key:** `normalize_email(lead["email"])` if it yields an email, else
  `f"notion:{lead['page_id']}"`. (Reuse the existing email normalizer.)
- **event_id:** `make_event_id("seed", lead["page_id"], key)` — deterministic on the
  Notion page id, so re-running the backfill is a no-op on the fold (idempotent).
- **kind:** `"seed"`; **source:** `"notion-backfill"`.
- **timestamp:** the real `last_contacted` (ISO) when present, else `import_ts`. This
  drives the board's "last contacted" display and fold ordering.
- **account_name:** Notion `name`.
- **payload:** `{stage, outcome}` from `map_notion_status(status)`, plus
  `import_ts` (the clean-slate anchor, §3.4), `estimated_value`, `source`, `priority`,
  `contact`, `page_id`, and `last_contacted` (raw, for provenance).
- Total: never raises on a malformed lead (missing fields default; a lead with no
  usable key still gets a `notion:<page_id>` key). Records dropped for any reason are
  counted and logged, never silently swallowed.

### 3.3 `lib/deal_fold.py` — seed handling in `build_deals` (extend)

Add `seed` to the per-event loop and the post-loop derivation. Rules:
- A `seed` event contributes `seed_stage`, `seed_outcome`, `seed_import_ts`,
  `seed_account`, `seed_value` for its component (last-write-wins by the existing
  `(timestamp, event_id)` sort — deterministic).
- **Real signal wins.** If the component has any real `demo`/`trial`/`sale` event, stage
  and dates derive as they do today; the seed only provides fallback `account_name` /
  `deal_value` provenance.
- **Seed-only components** (no real events): `stage = seed_stage`, `outcome =
  seed_outcome`, `deal_value = seed_value`.
- **account_name precedence:** `crosswalk[email]` → `seed_account` → `domain_to_name(email)`.
  (For `notion:<page_id>` keys there is no domain, so `seed_account` is the name.)
- Fold stays **pure and total** — seed payload read via `.get`, no field can raise.

### 3.4 Clean-slate stale clock (fold detail)

The seed carries `payload.import_ts`. In the fold, a seed-only **open** deal uses
`import_ts` as its stale-clock anchor (`effective_start`), so it becomes stale
`import_ts + 45d` — i.e., nothing surfaces on import day; only post-import silence does.
The board still shows the *real* `last_contacted` (from the event timestamp /
`last_event_at`), separate from the stale anchor.

**Required fold refinement:** the 45-day stale branch must require `outcome == "open"`,
so terminal `won`/`lost` seeds (84 of the 111) never surface for review. Today the chain
excludes `lost` (terminal, handled first) but not `won`; add the `open` guard so an
imported `won` deal with an old date can't wrongly flag stale.

### 3.5 `scripts/backfill_deals.py` — orchestration (thin, one-shot)

Loads `data/pipeline_cache.json` via `registry_storage(config)`, computes `import_ts`
(the run date), calls `normalize_seed_events`, `append_events`, and prints a summary
(counts by stage, email vs `notion:` keys, appended vs skipped-idempotent). Because it
writes a registry store, the operator commits `deal_events.jsonl` back to `origin/main`
after a dry-run inspection (see §6). Not scheduled — run once, by hand.

## 4. What the board shows after import

All ~111 deals fold in. Expected columns from the current snapshot: **Lost 48**,
**Won 36**, **In-Trial 14**, **Demoed 13** (8 Out-of-Demo + 3 On-Hold + 2 No-Trial).
20 records are name-only (`notion:<page_id>` keys); 91 are email-keyed and will
auto-merge with any future demo on the same address.

## 5. What stays unchanged / deferred (explicit non-goals)

- **Consumer seam-swap.** The brief / meeting-prep still read `pipeline_cache.json`;
  pointing them at the deal-store projection is the separate deferred step (design
  t-d0d636). Backfill only makes the store a superset — it does not swap consumers.
- **OMS `/api/deals/ingest`.** The push stays inert; that endpoint is the user's next
  project (t-78bb8e), cross-repo.
- **"Add deal" UI** for pre-demo leads — the gap created by retiring Notion. Follow-up.
- **Cross-demo/name auto-matching.** A `notion:<page_id>` seed and a later same-account
  demo are linked by the existing manual **merge** action (Queue A), not by fuzzy
  name-matching.

## 6. Rollout (one-shot, reversible)

1. **Step 0:** user runs the pipeline-cache sync → fresh `data/pipeline_cache.json`
   (~111 leads) on `main`. *(Done 2026-08-19.)*
2. Run `scripts/backfill_deals.py` locally in **dry-run** (compute events, print the
   summary, do not append). Inspect: 111 events, expected stage counts, 20 `notion:`
   keys, 0 dropped.
3. Run for real → append to `deal_events.jsonl`; fold and eyeball the board.
4. Commit `deal_events.jsonl` to `origin/main`.
5. Re-run once to confirm **idempotency** (0 appended the second time).

Reversibility: seeds are append-only events with deterministic ids; a bad import is
undone by removing the `source == "notion-backfill"` lines from `deal_events.jsonl`
(one commit), then re-folding. No consumer is swapped, so nothing downstream breaks.

## 7. Error handling

- `normalize_seed_events` is total: a malformed lead never aborts the batch; unusable
  leads are counted and reported.
- `append_events` is idempotent by `event_id` (existing behavior); re-runs are no-ops.
- The fold is pure/total (existing invariant); seed payloads are read defensively.
- If Step 0's cache is stale or partial, the import reflects exactly what's in the
  snapshot — the snapshot is the auditable input, re-runnable after a fresh sync.

## 8. Testing

- `map_notion_status` — each of the 8 statuses + unknown/empty default; never raises.
- `normalize_seed_events` — email key vs `notion:<page_id>` fallback; deterministic
  `event_id` on `page_id` (idempotent); timestamp = last_contacted else import_ts;
  payload carries stage/outcome/import_ts/value; malformed lead tolerated.
- `build_deals` seed handling — seed-only deal takes seed stage/outcome; a real demo on
  the same key supersedes seed stage; clean-slate (import-anchored) → not stale on
  import day but stale after `import_ts + 45d`; terminal won/lost never surface for
  review; account_name precedence (crosswalk → seed_account → domain).
- End-to-end fixture — a small `pipeline_cache.json` fixture folds into the expected
  board stage counts and review queues (identity empty for named seeds; stale empty on
  import day).

## 9. Open questions / follow-ups

- **"Add deal" entry path** (post-Notion) — the one real workflow gap; design separately.
- **Consumer seam-swap** (t-d0d636) — now unblocked once the store is a superset.
- **Email-keyed seed vs future demo dedup** — 91 seeds are email-keyed; verify a later
  demo on the same normalized email folds into one deal (it should, by construction).
- **`estimated_value` fidelity** — most records have null value; conversion/$-weighted
  views stay approximate until values are backfilled (not in scope).

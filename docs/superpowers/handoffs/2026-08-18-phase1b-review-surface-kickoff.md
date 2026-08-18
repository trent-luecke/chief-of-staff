# Phase 1b Kickoff — Deal Review Surface + Cross-Demo Merge

**Repo:** chief-of-staff · **Date written:** 2026-08-18 · **For:** a fresh session starting Phase 1b

> This is a jump-start doc. Read it, then read the design's **§3.10** and **§5**
> in `docs/superpowers/specs/2026-08-18-gtm-deal-store-phase1a-design.md` — that
> spec already shaped this work; you are planning + building it, not re-deciding it.

## Where things stand (what's already live)

**Phase 1a — the deal spine — is MERGED and live** (PR #31). Every night `avoma_sync`:
1. Turns Avoma demos into `DealEvent`s → appends `data/deal_events.jsonl` (git-anchored, `merge=union`, accessed via `lib.storage.registry_storage`).
2. Folds them (`lib/deal_fold.build_deals`) into email-keyed `Deal`s.
3. Writes a projection to `data/deal_pipeline_cache.json` — a **side file**, NOT the live `pipeline_cache.json` (deliberate: the deal store is demo-only until backfill, so it must not clobber the Notion-populated live cache).
4. Pushes to OMS `/api/deals/ingest` (currently **inert** — that endpoint doesn't exist yet; separate handoff).

**Validated on real demos.** The fold's same-domain collapse works (a 13-attendee demo → one deal). A follow-up **PR #32** (may or may not be merged when you start — CHECK) tuned the normalizer to drop automated senders (`no-reply@zoom.us`) and flag free-email prospects (`gmail.com` → `free_email`). **If PR #32 is open, merge it before starting** — Phase 1b's identity queue surfaces exactly these flags.

## The goal of Phase 1b

Turn the flagged deals into something Trent can act on, and make human decisions flow back as events. Three pieces (all in the design §3.10 unless noted):

1. **Extend the fold to apply `status` and `manual` events.** Today `build_deals` only folds `demo` events. The `DealEvent` vocab already includes `kind ∈ {demo, trial, sale, status, manual}` (`lib/deal_events.py`). Phase 1b makes the fold *apply* them:
   - `status` events → set `outcome=lost` (+`lost_reason`), or set `review.check_back` (on-hold snooze date), or reset the 45-day clock (still-active).
   - `manual` events → identity resolution: confirm primary / choose different primary / split / merge / not-a-deal.
   This is pure fold logic — **do it TDD**, and keep order-independence (see the Task-5 fix: sort each email's events by `(timestamp, event_id)` before folding; a Critical order-dependence bug already bit us there).

2. **The two review queues, surfaced in the Today tab.**
   - **Queue A — Identity review** (`review.kind == "ambiguous"`, reason codes: `multi_domain`, `no_email`, `generic_inbox`, `free_email`, `account_conflict`). Actions → a `manual` DealEvent.
   - **Queue B — 45-day review** (`review.kind == "stale_check"`). Actions: **Lost** / **On hold (prompts for a check-back date)** / **Still active**. Each → a `status` DealEvent. *Never auto-Lost.*
   - Surface: a `deals_to_review` block in `processors/today_brief.build_today_brief` (it returns a dict with `meetings` + `needs` — add the block, rendered **under meetings**). Rendered in `tools/registry_ui.html`.

3. **Cross-demo account merge** (was deferred here from 1a). Two separate demos sharing a contact email should become **one** deal. Today `build_deals` groups strictly by primary `email`, so `jane@acme` and `bob@acme` from two demos = two deals. Implement union-find over shared `contact_emails` in the fold, and emit the `account_conflict` reason when a new demo's email matches an existing deal with a different account. This pairs with Queue A's **merge** action.

## What to build on (exact anchors)

- **The fold:** `lib/deal_fold.py` — `build_deals(events, crosswalk, today, stale_days=45)` returns `dict[email, Deal]`; `Deal.review = {needs, kind, reason, proposed, ...}`. Extend here.
- **Events:** `lib/deal_events.py` — `DealEvent`, `make_event_id`, `append_events`, `load_events`. Human decisions are new events appended here.
- **Read model for the UI:** fold the event log via `registry_storage` → `build_deals` → filter `review.needs`. There is no separate "current deals" store; the fold IS the source of truth.
- **Registry write path:** `tools/server.py` — every write goes through `_write_main(mutate, msg)` which commits to `origin/main` via a throwaway worktree (see the `POST /api/tasks` handler as the template). Add `POST /api/deals/<id>/review` (identity) and `POST /api/deals/<id>/status` (lost/hold/active) that append DealEvents. **Gotcha:** the deal key is an email (or `unresolved:<uuid>`), which is awkward in a URL path — consider a `deal_id` scheme or pass the email in the POST body.
- **UI:** `tools/registry_ui.html` — render the review block + quick actions + the on-hold date picker. Launch via the `registry-ui` skill or `python3 tools/server.py` (port 8787).
- **Today tab:** `processors/today_brief.py` — `build_today_brief(...)`.
- **The design:** `docs/superpowers/specs/2026-08-18-gtm-deal-store-phase1a-design.md` §3.10 (full review-surface design), §5 (heuristics + why each flag exists).

## Decisions already locked (do NOT relitigate)

- Event-sourced; **human decisions ARE DealEvents** (`status`/`manual` kinds) — a resolved flag clears on the next fold, never re-prompts.
- On-hold **prompts for a check-back date** (not a fixed snooze); **Still active** is a distinct action that resets the 45-day clock.
- Notion is retired; the projection is a side file until backfill.
- 45-day rule is **human-confirmed, never automatic**.

## Open questions to resolve while planning

- **Deal identity in the URL/endpoint** (email vs synthetic id) — pick one, keep it stable across re-folds.
- **Read model performance** — folding the whole event log on every UI request is fine now (tiny), but note it; a cached fold may be wanted later.
- **Cross-demo merge + `event_id` stability** — `event_id` currently keys on `prospects[0]`; a merge changes which email is primary. Make sure the merge is derived in the fold (not by rewriting events) so the append-only log stays immutable.
- **What the email brief (if still sent) shows** — it can't have working buttons; design says read-only summary + "open Today" link.

## Suggested first move

The design is detailed enough to skip re-brainstorming. Recommended path:
1. Confirm PR #32 is merged; pull `main`.
2. Use `superpowers:writing-plans` to plan Phase 1b as ~2 sub-plans: **(a) fold extension + read model** (pure, TDD, no UI) and **(b) endpoints + Today-tab block + UI**. Ship (a) first — it's testable in isolation and everything else depends on it.
3. Execute subagent-driven (as Phase 1a was).
4. **Validate against real flagged deals:** the validation approach from Phase 1a (fold real Avoma demos, inspect `review` flags) already produces `free_email`/`generic_inbox`/`no_email` cases — use them to exercise the identity queue end to end.

## Tracking

Registry project `gtm-producer-deal-data-foundation` holds the follow-on tasks (t-a43140 = Registry pipeline view; the review-surface work maps to it + the deferred cross-demo merge).

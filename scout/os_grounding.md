## The OS Grounding Profile (agent's core context)

This is the single most important artifact. It is stored as `scout/os_grounding.md`, hand-curated (not machine-written), and injected verbatim into the analysis prompt for every teardown. The model may ONLY assign OS-relevance tags by looking features up against this profile; when a feature does not map cleanly it must tag `❓ Your call` rather than guess.

### Strengths (crown jewel first)
1. **Programming depth** — periodized, %-based strength & conditioning; genuine sport-performance training fit. Best-in-class vs. CrossFit-native tools.
2. **One member app** — booking + scheduling + billing + workout tracking in a single member-facing app (OS + Strength combo).
3. **Transparent single price** — $200/mo published, no tiers, no feature-gating.
4. **0% payment processing cut** — Stripe-native; revenue is subscription only.
5. **Facility ops** (scheduling, check-in, membership management) — solid vs. incumbents but not leading. **OS has NO access control.**

### Gaps
1. **Reporting — the headline gap.** No at-risk/churn report (absent-member or churn-signal surfacing), no granular revenue (revenue per membership/package, net-new MRR), no per-class/service attendance economics (to decide what schedule items to add/drop), no location-separated revenue.
2. **Multi-location** support generally (reporting aggregates across the whole account, not per location).
3. **Integrations / automation** — Zapier shipped but dead on arrival (3 of 91 accounts, 6 zaps). The OS Workflow Builder pitch is the in-progress answer.
4. **Native AI** — a gap, but **actively being built/explored** (Workflow Builder's Claude layer). Competitor AI features tag as "gap — in progress," never a blind-spot alarm.
5. **Lead management + native marketing** (email/campaigns/CRM) — **deliberately out of scope**; positioned as focus + integration.
6. **SSO** — exists, but a paid add-on built for larger accounts. **Member-booked appointments** — ~10 days from launch as of 2026-08-06 (treat as shipping imminently).

### Market fit
- **ICP:** strength & conditioning facilities, sport-performance gyms, hybrid clinic-gyms. Serves — but is **not optimized for** — yoga/spa/general-wellness.
- **Loses to** "sophisticated" operators: multi-location businesses, highly structured marketing funnels needing native CRM/marketing integration, or buyers who simply want lots of bells & whistles.
- **Guardrail (from positioning memory):** OS + Strength are two subscriptions / two invoices sharing one member app. Never attack a competitor for being "two products / two invoices / an integration between them" — that's a glass house.

### OS Jobs-To-Be-Done (confirmed by Trent 2026-08-06)

The agent must NOT regenerate this weekly — it is curated here and looked up, exactly like strengths/gaps. (Synthesized from platform-level signal in the Workflow Builder JTBD interviews — 410 Fitness, FSP, Orca — where consolidation-not-automation and login-aversion were directly evidenced.)

- **Buyer:** the S&C / sport-performance facility owner-coach.
- **Functional job:** *"When I'm running my facility across a pile of disconnected tools — programming in one place, scheduling/billing/members in another — I want one platform that runs the operation AND delivers real, periodized S&C programming through a single member app, so I can run a legit, professional facility without stitching together a stack or becoming a software company."*
- **Emotional job:** feel in control and credible — not duct-taping tools or apologizing for a clunky member experience.
- **Social job:** look as buttoned-up to my athletes/members (and youth-SP parents) as a big franchise does.
- **The wedge OS uniquely gets hired for:** *consolidation + programming depth* — "be the hub, and be the one platform that actually does the training, not just the front desk."
- **Hired over:** front-desk tool + separate Trainerize · spreadsheets + calendars + booking tool · a CrossFit-native tool with shallow programming.
- **NOT hired for:** a marketing/lead-gen engine, a multi-location HQ command center, or a maximal-feature Swiss-army platform. (These are the "sophisticated operator" losses above.)

### Reaction taxonomy
Every notable competitor feature gets exactly one tag:

| Tag | Meaning |
|-----|---------|
| ✅ **We do this** | OS already has it — name the OS equivalent |
| 🎯 **Real gap** | OS lacks it AND it hits real ICP pain |
| 🚫 **Out of scope** | OS deliberately chose not to — note the reason |
| ➖ **Adjacent / not-optimized** | For a segment OS serves but isn't built for (e.g. yoga/spa) or doesn't serve at all (e.g. medspa SOAP notes) |
| ✨ **Genuinely novel** | Nobody in the space does this — pure inspiration |
| ❓ **Your call** | Doesn't map cleanly to the profile — flag, don't guess |

**Two hard rules baked into the prompt:**
- **Lean by default.** A missing feature is `🎯 Real gap` *only* if it hits real ICP pain (e.g. the reporting gaps). Bells-and-whistles OS deliberately skipped → `🚫 Out of scope`, not `🎯`. This keeps the email signal-dense and respects OS's deliberate focus.
- **AI is in progress.** Competitor AI features → `🎯` tagged "in progress," never framed as a blind spot.

This profile is expected to drift; it is version-controlled and hand-edited as OS ships (e.g. when member-booked appointments launches, move it from gap to strength).

### JTBD verdicts

Each teardown includes a JTBD analysis: the agent reads the **platform's** JTBD from its own marketing copy (fair — it's their stated positioning), then compares it to the **confirmed OS JTBD** above and lands exactly one verdict:

| Verdict | Meaning | Output |
|---------|---------|--------|
| 📣 **Positioning gap** | Platform loudly sells a job OS *already does* but doesn't market | Copy/messaging opportunity — agent quotes the platform's exact line so Trent reacts to real language. **This is the primary payload of the JTBD section.** |
| 🎯 **Real job gap** | A job OS genuinely can't do | Cross-references the feature taxonomy (🎯/🚫) |
| ➖ **Different job** | Not OS's ICP/job | Note briefly and move on |

Same grounding rule as the feature taxonomy: the platform's JTBD is derived from their copy, but the OS-comparison verdict is a **lookup against the confirmed OS JTBD**, never invented product/marketing strategy. Unclear cases → flag for Trent's judgment rather than guess.

## Category fingerprint (what "one of these platforms" looks like)

Used by the discovery layer to recognize an in-scope platform and by the analysis prompt as reference. Derived from profiling six exemplars during brainstorming:

1. **"All-in-one" consolidation** is the universal pitch (replace-your-stack framing).
2. **Anti-incumbent pricing** as the common differentiator — free tier, flat-unlimited, or inverted economics (e.g. free software funded by payment processing).
3. **AI packaged as a named SKU or the whole pitch**, not a checkbox feature.
4. **Exactly one "weird wedge"** per platform — the novelty is almost never in the core CRM but in one adjacent bet (localization, vertical depth, business model).
5. **"0% cut / keep your money"** payment positioning.
6. **All-features-included, scale-by-size-not-feature** pricing.
7. **Founder-operator origin story** as the trust signal.
8. **Two buckets:** (A) brick-and-mortar gym/studio ops, (B) online coaching. Both in scope. Occasionally straddled.

# TeamBuildr OS — Competitor Comparison Pages: Content Spec

**Owner:** Trent Luecke · **Build partner:** RevOps
**Status:** Draft for review · **Last updated:** 2026-07-23

---

## Purpose

Per-competitor comparison pages positioning **TeamBuildr OS** against gym/studio management platforms. One page per competitor — not a single master grid.

**Competitor set (7):** MindBody, Walla, Glofox, ZenPlanner, PushPress, Wodify, exercise.com.

## The strategic frame (why this isn't a normal comparison chart)

OS is **intentionally feature-light and operationally focused.** A traditional feature-to-feature grid rewards feature *count* and would make OS look like the wrong choice by design. So these pages **change the axes of comparison** — they compare experience, focus, economics, and fit rather than feature quantity. On those axes, a focused product beats a bloated one.

**The spine of every page:** OS handles everything that touches a paying member — booking, billing, scheduling, POS, staff reporting, flexible schedule items (classes/appointments/workshops) — and does it cleanly, then integrates with the marketing/lead tools you already trust. Focused instrument vs. junk drawer.

**OS scope (the foundation — do not overstate):**
- **In scope:** member-facing booking, billing, scheduling; staff-facing reporting, POS, flexible schedule items; native workout delivery / programming (TeamBuildr heritage).
- **Deliberately NOT in scope:** lead management, native marketing (email workflows, campaign generators, CRM). This is owned as a *stance*, not hidden as a gap — see "What OS leaves to the specialists" below.

**Honest buyer qualifier (bake in, don't hide):** OS is for gyms whose lead-gen lives elsewhere (a marketer, existing tools, word-of-mouth) and who want the member-ops layer to be simple. A gym that wants one login for *leads + ops + marketing* is not the buyer, and the page shouldn't pretend otherwise.

**Transparent pricing is a differentiator, not just a data point.** OS publishes its price ($200/mo or $2,000/yr); most competitors here are quote-only / "book a demo to hear the price." Printing the number on the page *is* the message: no games, no sales gauntlet. Lean into it.

---

## Two page archetypes

The deciding fact is **whether the competitor has native workout delivery / programming.** If it doesn't, a gym on it needs a *second app* on every member's phone — OS's sharpest edge. If it does, that edge disappears and the page needs a different wedge.

### Archetype A — "Second app" (no native programming)
**MindBody, Walla, Glofox.** Share one skeleton; lead with the one-app + built-for-coaches + focus story. Glofox (ABC Fitness) also gets an "independent, not enterprise" angle.

### Archetype B — "Has programming" (one-app *existence* hammer blunted)
**PushPress, Wodify, exercise.com, ZenPlanner.** These have native workout/programming, so "one app, not two" and "built by gym people" don't differentiate on existence alone. Same skeleton; each needs its own wedge (see below). **Design these deliberately — do not inherit Archetype A's framing.**

B is not monolithic — split by programming *quality*:
- **Competent programming (PushPress, Wodify, exercise.com):** can't win on programming existence *or* quality easily → win on depth, breadth, pricing, or simplicity. Drop the member-experience row.
- **Weak/dated programming (ZenPlanner):** win on *quality* — a modern, coach-grade experience. Keep a reframed member-experience row, but **demonstrate** it (screens/clip), don't assert "theirs is bad." Confident, not petty; also more legally defensible.

> ⚑ **Archetype assignment depends on native-programming status — verify per competitor before building.** All of B rests on this. (ZenPlanner confirmed: has native programming, but dated.)

---

## The reframed comparison table

The OS column is constant. The competitor column changes per page.

### Shared row skeleton — OS column (constant, provable claims)

| Row | **TeamBuildr OS** |
|---|---|
| **Built for** | Strength & performance gyms and their coaches |
| **Member experience** | **One app** — booking, billing, *and* workouts in a single member app |
| **What you pay for** | The features your staff use every day |
| **Pricing** | **$200/mo or $2,000/yr** (save ~17% annually). Bundle with TeamBuildr Strength for up to ~20% off (varies by Strength tier). |
| **How we make money** | Only your subscription — **we take 0% of your Stripe processing fees** |
| **Marketing & leads** | Bring the tools you already use — we integrate, we don't bloat |
| **Contracts** | Month-to-month (cancel anytime) or save with an annual plan |
| **Support** | Real people who understand gyms |
| **Time to go live** | Days |

**Notes on the OS column:**
- *Member experience* — the marquee row for **Archetype A only**. Drop or soften it on Archetype B pages (those competitors also have programming).
- *Pricing* — Stripe-native (Stripe only). Explicit price is intentional; annual $2,000 vs. $2,400 monthly = ~17% savings; OS+Strength bundle ≈ 20% off depending on Strength subscription level.
- *How we make money* — the claim is NOT "bring your own processor." It's: OS takes **no cut** of Stripe processing fees; the only OS revenue is the subscription. Incentive-alignment story — "we only make money if you stay happy."
- *Contracts* — monthly plan cancellable anytime (no 12-month commitment at the monthly rate); annual plan enforced for its term. State both honestly.
- **No "learning curve" row** — not a claim we can currently substantiate.

---

## Archetype A pages

### Page 1 — OS vs. MindBody (build first; it's the template)

| Row | **TeamBuildr OS** | **MindBody** |
|---|---|---|
| **Built for** | Strength & performance gyms and their coaches | Any wellness business — spas, salons, yoga, med-spas |
| **Member experience** | One app — booking, billing, *and* workouts | Ops only; members need a **second app** for programming |
| **What you pay for** | The features your staff use every day | A bundle of modules most gyms never open |
| **Pricing** | $200/mo or $2,000/yr — published, flat | Quote-only; tiers + per-feature add-ons ⚑ |
| **How we make money** | Only your subscription — 0% cut of Stripe fees | Verify their processing economics ⚑ |
| **Marketing & leads** | Bring the tools you already use — integrate, not bloat | Bundled CRM you pay for and wrestle with ⚑ |
| **Contracts** | Month-to-month, cancel anytime — or save with annual | Annual lock-in ⚑ |
| **Support** | Real people who understand gyms | Tiered ticket queue ⚑ |
| **Time to go live** | Days | Weeks, often with onboarding fees ⚑ |

**Hero:** *"One app for your members. Not two."* — MindBody runs your front desk. It doesn't run your workouts — so your members carry a second app for that. OS does both.

### Page 2 — OS vs. Walla
Newer boutique studio platform (yoga/pilates/barre-leaning), no native programming.

| Row | **TeamBuildr OS** | **Walla** |
|---|---|---|
| **Built for** | Strength & performance gyms and their coaches | Boutique studios — yoga, pilates, barre |
| **Member experience** | One app — booking, billing, *and* workouts | Ops only; second app needed for programming ⚑ |
| **What you pay for** | The features your staff use every day | Studio-class management; lighter fit for performance training ⚑ |
| **Pricing** | $200/mo or $2,000/yr — published, flat | Verify ⚑ |
| **How we make money** | Only your subscription — 0% cut of Stripe fees | Verify ⚑ |
| **Marketing & leads** | Integrate, not bloat | Built-in marketing/CRM ⚑ |
| **Contracts** | Month-to-month or annual | Verify ⚑ |
| **Support** | Real people who understand gyms | Verify ⚑ |
| **Time to go live** | Days | Verify ⚑ |

**Hero:** One-app hammer + "built for training, not just studios." Optional platform-maturity note only if verifiable and tasteful.

### Page 3 — OS vs. Glofox
Boutique studio management, now part of ABC Fitness (enterprise), no native programming.

| Row | **TeamBuildr OS** | **Glofox** |
|---|---|---|
| **Built for** | Strength & performance gyms and their coaches | Boutique fitness studios (now part of ABC Fitness) |
| **Member experience** | One app — booking, billing, *and* workouts | Ops only; second app needed for programming ⚑ |
| **What you pay for** | The features your staff use every day | Studio management + enterprise modules ⚑ |
| **Pricing** | $200/mo or $2,000/yr — published, flat | Quote-only ⚑ |
| **How we make money** | Only your subscription — 0% cut of Stripe fees | Verify ⚑ |
| **Marketing & leads** | Integrate, not bloat | Built-in marketing ⚑ |
| **Contracts** | Month-to-month or annual | Annual contract ⚑ |
| **Support** | Real people who understand gyms | Verify — post-acquisition support is fair if substantiated ⚑ |
| **Time to go live** | Days | Verify ⚑ |

**Hero:** One-app hammer + **"independent, not enterprise"** — built and supported by people who know gyms, vs. a product folded into a large corporate portfolio.

---

## Archetype B pages (design deliberately — no one-app-*existence* hero, no "built by gym people" claim)

These competitors have native programming, so lead with a *different* wedge. Shared skeleton applies **minus the Member-experience row** (except ZenPlanner — see below). Do not draft cells until each competitor's capabilities and pricing are verified.

**ZenPlanner** — gym/martial-arts/affiliate member management, owned by Daxko. Has native programming, but dated.
Wedge: **modern, coach-grade programming** + **"independent, not enterprise"** (Daxko). Keep a reframed member-experience row — "one modern app your members want to open," shown via OS screens/clip rather than asserting ZenPlanner is bad (defensible + on-brand). ⚑ Verify pricing, contracts, marketing/CRM scope.

| Row | **TeamBuildr OS** | **ZenPlanner** |
|---|---|---|
| **Built for** | Strength & performance gyms and their coaches | Membership management for gyms & martial arts ⚑ |
| **Member experience** | One modern app — booking, billing, *and* coach-grade workouts | Has programming, but a dated experience *(demonstrate, don't assert)* ⚑ |
| **What you pay for** | The features your staff use every day | Member-management modules ⚑ |
| **Pricing** | $200/mo or $2,000/yr — published, flat | Quote-only ⚑ |
| **How we make money** | Only your subscription — 0% cut of Stripe fees | Verify ⚑ |
| **Marketing & leads** | Integrate, not bloat | Verify (built-in?) ⚑ |
| **Contracts** | Month-to-month or annual | Verify ⚑ |
| **Support** | Real people who understand gyms | Verify ⚑ |
| **Time to go live** | Days | Verify ⚑ |

**PushPress** — gym-owner-built, has workout/programming.
Candidate wedge: **programming depth** (TeamBuildr's origin is a serious S&C programming platform vs. PushPress's lighter add-on) and/or **pricing model** contrast. ⚑ Verify PushPress programming depth + pricing (free tier / per-member?).

**Wodify** — CrossFit-native, has performance/WOD tracking.
Candidate wedge: **breadth beyond CrossFit** (strength & performance broadly, not box-specific) + **flat $200 vs. per-athlete pricing that scales with your roster.** ⚑ Verify Wodify pricing model and programming scope.

**exercise.com** — all-in-one "custom-branded app" with workout delivery + marketing.
Candidate wedge: **simplicity + transparent flat price, live in days** vs. custom-build complexity and quote-based pricing. "You don't need a custom app project and a big bill — $200/mo, live in days." ⚑ Verify exercise.com pricing and build/onboarding model.

---

## Reusable page components (all pages)

**1. Incentive-alignment callout band** (its own strip, not a cell — fully provable):
> *"We take zero cut of your payment processing. Our only revenue is your subscription — so we only make money if you stay happy. That's it."*

**2. "What OS leaves to the specialists" section** (below the table): a short, confident paragraph owning that OS has no built-in email marketing or lead CRM — framed as focus + integration — ideally with logos of the marketing tools OS plays well with. Answers the "you're missing marketing" objection on offense.

---

## ⚑ Verification legend — READ BEFORE PUBLISHING

Every ⚑ cell is a **competitor-specific factual claim** (pricing, contracts, processing economics, support model, onboarding, native-programming status). These are comparative-advertising claims that can draw legal challenge and erode trust if stale or wrong.

**Rule:** RevOps sources and dates every ⚑ cell before it goes public. Any ⚑ claim that can't be substantiated gets **cut, not softened** — the provable rows carry each page on their own.

**Stand-behind (provable today) — OS side:**
- One app (booking + billing + workouts) vs. platforms with no native programming
- Published flat price: $200/mo or $2,000/yr; ~17% annual savings; ~20% OS+Strength bundle
- Stripe-native, 0% cut of processing fees; subscription is the only OS revenue
- Month-to-month (cancel anytime) or annual
- No native marketing/lead CRM — by design; integrates instead

---

## Open items

1. **Verify native-programming status** for PushPress, Wodify, exercise.com — this decides archetype. (ZenPlanner confirmed: has native but dated programming → Archetype B.)
2. RevOps to source/date all ⚑ competitor cells; cut any that can't be substantiated.
3. Fill Archetype A competitor cells (Walla, Glofox, ZenPlanner) with sourced data.
4. Design the three Archetype B pages once capabilities/pricing are confirmed.
5. Confirm marketing-tool integration logos for the "specialists" section.
6. Decide whether hero lines (recommendations here) go through a final copy pass.

# Feature Requests → Accounts Backfill (one-time)

This is a one-time link of each existing Feature Request to the OS accounts that asked for it, using the new `Requesting Accounts` relation. It is plan Task 5 (`docs/superpowers/plans/2026-11-02-os-quarterly-checkins.md`).

**Status: APPLIED 2026-11-03.** 24 requests got `Requesting Accounts` links, and the 8 completed ones were also seeded in `Shipped notified`. Verified by a read-back. StoneAthletics has two duplicate account records (`3d124bca…81f4` linked; `3ea24bca…02e6` is the duplicate). Approved by Trent on 2026-11-03 in chat. Unmatched names are churned accounts or prospects that never converted: they stay plain text in `Requesting Account` and are not re-matched. "New Era" → `New Era Coaching Ltd` (not the Dunboyne account). "Change Inactive/Active to Public/Private" skipped: the project is finished.

## Rules
- **What gets written:** only the relation, and only for rows Trent approves. The backfill does **not** change `Amount of Requests` or the `Requesting Account` text, because those already reflect the historical asks.
- **How names were matched:** `scripts/checkins.py match` against the OS Accounts Database, using the first 100 rows (Active, plus 1 Churned). The rest of the accounts couldn't be pulled because the Notion SQL query allowance ran out on 2026-11-02. Many **Unmatched** names (Home of Yoga, Mass General Brigham, Off-Field, Kula, Mi-Yoga, Brock U, Straight Shot Training, …) are probably churned or legacy accounts. They get re-matched against the full account list before anything is written.
- **Shipped notified seeding:** for every request already `Completed/Closed?`, the same approved accounts are also written to `Shipped notified`. That stops the routine from sending "it's live" for things that shipped long ago.
- **Not account names:** "Multiple", "multiple" and "Several". These rows can't be backfilled unless you name the accounts.

## How to review
In the **Decision** column, write one of:
- `ok` to accept the Matched column as is;
- `ok + <name>` to accept it and also add one of the Uncertain/Unmatched names, written as the exact OS account name;
- `skip`;
- a corrected list of exact account names.

Then change Status above to **APPROVED**.

| Request | Requesting Account (raw) | Matched | Uncertain (confirm?) | Unmatched | Decision |
| --- | --- | --- | --- | --- | --- |
| Coach/Business version of GymStudio App | Madhouse Performance | Mad House Performance | — | — | ok |
| Limiting Coaches Access and Offerings with Multiple Locations | Ignition APG | — | — | Ignition APG | skip (churned/prospect or placeholder — text only) |
| Change Inactive/Active to Public/Private for Products | Multiple | — | — | Multiple | skip (project finished) |
| Update "Has been paid" toggle to change transaction status | Off-Field | — | — | Off-Field | skip (churned/prospect or placeholder — text only) |
| Edit quantity in POS | Ryan Boylen | Sthenos Athletics (Ryan Boylen) | — | — | ok |
| Track First Time Visits | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Add locations/rooms to appointments | Underdog Foundation | The Underdog Foundation | — | — | ok |
| Icons/Markers when viewing the roster for a class | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Report showing conversion rate of Intro Offers | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Automated emails for last sessions of a package | Full Throttle Fitness | Full Throttle Fitness & Performance, LLC | — | — | ok |
| Associating child account and spouse/partner account | Full Throttle Fitness | Full Throttle Fitness & Performance, LLC | — | — | ok |
| Automated email when liability waiver/cancellation policy is updated | Kavarsky | — | — | Kavarsky | skip (churned/prospect or placeholder — text only) |
| Ability to copy a days schedule to other days | Science Over Tradition | — | — | Science Over Tradition | skip (churned/prospect or placeholder — text only) |
| Restrict booking access upon failed payments | New Era, Full Throttle, StoneAthletics | Full Throttle Fitness & Performance, LLC, StoneAthletics | New Era → New Era Coaching Ltd - Dunboyne? | — | ok + New Era Coaching Ltd |
| Automated Emails for Credit/Package Expiration | IRG | IRG Physical & Hand Therapy | — | — | ok |
| Show Cancelled Bookings on Members Booking tab | BUILT S&C | — | — | BUILT S&C | skip (churned/prospect or placeholder — text only) |
| Display time of booking cancellation | BUILT. S&C | — | — | BUILT. S&C | skip (churned/prospect or placeholder — text only) |
| Include a Multi-select option to allow for bulk actions | SPR | SPR Conditioning | — | — | ok |
| Ability to send links for outstanding invoices manually | SPR, Full-Throttle | SPR Conditioning, Full Throttle Fitness & Performance, LLC | — | — | ok |
| Increased Attention/Highlight for Failed Payments | SPR, Full Throttle, New Era | SPR Conditioning, Full Throttle Fitness & Performance, LLC | New Era → New Era Coaching Ltd - Dunboyne? | — | ok + New Era Coaching Ltd |
| Accessible View to check session reservations/attendees | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Ability to change/edit a single invoice for a recurring membership | Juju Performance | — | Juju Performance → ORKA Performance? | — | skip (Juju Performance — churned, text only) |
| Ability to filter or categorize items on pricing page | Kaizen Athletics | — | — | Kaizen Athletics | skip (churned/prospect or placeholder — text only) |
| 24hr reminder email for members | Zen Athletic | Zen Athletic Performance | — | — | ok |
| Add more membership info within mobile app | Zen Athletic | Zen Athletic Performance | — | — | ok |
| Ability to Edit modules on Overview Page | Off-Field | — | — | Off-Field | skip (churned/prospect or placeholder — text only) |
| Editable Appointment Durations | ROI | ROI Physical Therapy & Sports Performance | — | — | ok |
| Limit Calendar View of Schedule to operating hours | ROI | ROI Physical Therapy & Sports Performance | — | — | ok |
| Appointment Scheduling Page Flow | ROI | ROI Physical Therapy & Sports Performance | — | — | ok |
| Specific Credit Allocations for Packages | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Allow classes to be scheduled across multiple days simultaneously | multiple | — | — | multiple | skip (churned/prospect or placeholder — text only) |
| Improved Cancellation Alerts for Members | UBUNTU, CARDS Performance, Strength House | Ubuntu MVMNT, Strength House Inc. | CARDS Performance → CARD Sports Performance? | — | ok + CARD Sports Performance |
| Upgrade members on waitlist to an active booking from Studio view | Symbiotic, 410 Fitness | Symbiotic Training Center, 410 Fitness | — | — | ok |
| Include Retention Metric in Reporting | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Conditional Promotions based on membership | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| POS Feature | Garret Snook; Ryan Boylen - Sthenos | Sthenos Athletics (Ryan Boylen) | — | Garret Snook | ok (Garret Snook — text only) |
| Re-order the Schedule + items | TIS | — | — | TIS | skip (churned/prospect or placeholder — text only) |
| Enhanced Filters on Member Page | Kula | — | — | Kula | skip (churned/prospect or placeholder — text only) |
| Remove need to add Live Stream link to individual sessions | Mi-Yoga | — | — | Mi-Yoga | skip (churned/prospect or placeholder — text only) |
| Resend Activation button for new/inactive members | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Bulk Booking for Members/Staff into Classes | Straight Shot Training; Mass General Brigham | — | — | Straight Shot Training, Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Include Member Notes in roster view | Mi-Yoga | — | — | Mi-Yoga | skip (churned/prospect or placeholder — text only) |
| Specific date range filter for viewing sales numbers | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Create a Waivers Section and assign them to memberships/members | Brock U | — | — | Brock U | skip (churned/prospect or placeholder — text only) |
| Allow for 10 Minute Classes | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Handling Classes with 0 attendance in Payroll | Gem Sessions | Gem Sessions | — | — | ok |
| Use saved card from member profile when performing a Sale | Ryan Boylen - Sthenos | Sthenos Athletics (Ryan Boylen) | — | — | ok |
| CSV Report Download | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Multiple Translations | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Expiring Membership Report | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Add credit expiration to Package Pricing squares | Kula | — | — | Kula | skip (churned/prospect or placeholder — text only) |
| Integrate with Calendar App | Several | — | — | Several | skip (churned/prospect or placeholder — text only) |
| Recurring Billing for Packages | Straight Shot Training | — | — | Straight Shot Training | skip (churned/prospect or placeholder — text only) |
| Notifications for Coaches when Appointment booked | Talented Tenth Athletics | Talented Tenth Athletics | — | — | ok |
| Kiosk/Check-in View for Members | Pivotal Sports Performance | — | Pivotal Sports Performance → CARD Sports Performance? | — | skip (Pivotal — prospect, text only) |
| Enhanced Cancellation/Booking Reporting | Jinte Kula; Mass General Brigham | — | — | Jinte Kula, Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Tracking of Promo Code Redemptions/Conversion | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Filter on Schedule Page to show Full/Not Full sessions | Mass General Brigham | — | — | Mass General Brigham | skip (churned/prospect or placeholder — text only) |
| Allow for Promo Codes to be set for more than one billing cycle | SPR | SPR Conditioning | — | — | ok |
| Ability to view attendees for classes in a report | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Ability to link/nest member profiles | Pivotal Sports Performance, Full Throttle Fitness | Full Throttle Fitness & Performance, LLC | Pivotal Sports Performance → CARD Sports Performance? | — | ok (Pivotal — prospect, text only) |
| At-Risk Member Report | Home of Yoga | — | — | Home of Yoga | skip (churned/prospect or placeholder — text only) |
| Allow for manual override of schedule conflicts | Lockeroom | — | — | Lockeroom | skip (churned/prospect or placeholder — text only) |
| Ability to Charge Cancellation Fee | Off-Field | — | — | Off-Field | skip (churned/prospect or placeholder — text only) |
| Custom Fields for Invoices | Youth Peak Performance, LPL, Youthlete Academy | Youth Peak Performance, LPL, Youthlete Academy | — | — | ok |

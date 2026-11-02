# Feature Requests → Accounts Backfill (one-time)

This is a one-time link of each existing Feature Request to the OS accounts that asked for it, using the new `Requesting Accounts` relation. It is plan Task 5 (`docs/superpowers/plans/2026-11-02-os-quarterly-checkins.md`).

**Status: AWAITING TRENT'S REVIEW.** Nothing has been written to Notion yet.

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
| Coach/Business version of GymStudio App | Madhouse Performance | Mad House Performance | — | — | |
| Limiting Coaches Access and Offerings with Multiple Locations | Ignition APG | — | — | Ignition APG | |
| Change Inactive/Active to Public/Private for Products | Multiple | — | — | Multiple | |
| Update "Has been paid" toggle to change transaction status | Off-Field | — | — | Off-Field | |
| Edit quantity in POS | Ryan Boylen | Sthenos Athletics (Ryan Boylen) | — | — | |
| Track First Time Visits | Home of Yoga | — | — | Home of Yoga | |
| Add locations/rooms to appointments | Underdog Foundation | The Underdog Foundation | — | — | |
| Icons/Markers when viewing the roster for a class | Home of Yoga | — | — | Home of Yoga | |
| Report showing conversion rate of Intro Offers | Home of Yoga | — | — | Home of Yoga | |
| Automated emails for last sessions of a package | Full Throttle Fitness | Full Throttle Fitness & Performance, LLC | — | — | |
| Associating child account and spouse/partner account | Full Throttle Fitness | Full Throttle Fitness & Performance, LLC | — | — | |
| Automated email when liability waiver/cancellation policy is updated | Kavarsky | — | — | Kavarsky | |
| Ability to copy a days schedule to other days | Science Over Tradition | — | — | Science Over Tradition | |
| Restrict booking access upon failed payments | New Era, Full Throttle, StoneAthletics | Full Throttle Fitness & Performance, LLC, StoneAthletics | New Era → New Era Coaching Ltd - Dunboyne? | — | |
| Automated Emails for Credit/Package Expiration | IRG | IRG Physical & Hand Therapy | — | — | |
| Show Cancelled Bookings on Members Booking tab | BUILT S&C | — | — | BUILT S&C | |
| Display time of booking cancellation | BUILT. S&C | — | — | BUILT. S&C | |
| Include a Multi-select option to allow for bulk actions | SPR | SPR Conditioning | — | — | |
| Ability to send links for outstanding invoices manually | SPR, Full-Throttle | SPR Conditioning, Full Throttle Fitness & Performance, LLC | — | — | |
| Increased Attention/Highlight for Failed Payments | SPR, Full Throttle, New Era | SPR Conditioning, Full Throttle Fitness & Performance, LLC | New Era → New Era Coaching Ltd - Dunboyne? | — | |
| Accessible View to check session reservations/attendees | Mass General Brigham | — | — | Mass General Brigham | |
| Ability to change/edit a single invoice for a recurring membership | Juju Performance | — | Juju Performance → ORKA Performance? | — | |
| Ability to filter or categorize items on pricing page | Kaizen Athletics | — | — | Kaizen Athletics | |
| 24hr reminder email for members | Zen Athletic | Zen Athletic Performance | — | — | |
| Add more membership info within mobile app | Zen Athletic | Zen Athletic Performance | — | — | |
| Ability to Edit modules on Overview Page | Off-Field | — | — | Off-Field | |
| Editable Appointment Durations | ROI | ROI Physical Therapy & Sports Performance | — | — | |
| Limit Calendar View of Schedule to operating hours | ROI | ROI Physical Therapy & Sports Performance | — | — | |
| Appointment Scheduling Page Flow | ROI | ROI Physical Therapy & Sports Performance | — | — | |
| Specific Credit Allocations for Packages | Mass General Brigham | — | — | Mass General Brigham | |
| Allow classes to be scheduled across multiple days simultaneously | multiple | — | — | multiple | |
| Improved Cancellation Alerts for Members | UBUNTU, CARDS Performance, Strength House | Ubuntu MVMNT, Strength House Inc. | CARDS Performance → CARD Sports Performance? | — | |
| Upgrade members on waitlist to an active booking from Studio view | Symbiotic, 410 Fitness | Symbiotic Training Center, 410 Fitness | — | — | |
| Include Retention Metric in Reporting | Home of Yoga | — | — | Home of Yoga | |
| Conditional Promotions based on membership | Mass General Brigham | — | — | Mass General Brigham | |
| POS Feature | Garret Snook; Ryan Boylen - Sthenos | Sthenos Athletics (Ryan Boylen) | — | Garret Snook | |
| Re-order the Schedule + items | TIS | — | — | TIS | |
| Enhanced Filters on Member Page | Kula | — | — | Kula | |
| Remove need to add Live Stream link to individual sessions | Mi-Yoga | — | — | Mi-Yoga | |
| Resend Activation button for new/inactive members | Mass General Brigham | — | — | Mass General Brigham | |
| Bulk Booking for Members/Staff into Classes | Straight Shot Training; Mass General Brigham | — | — | Straight Shot Training, Mass General Brigham | |
| Include Member Notes in roster view | Mi-Yoga | — | — | Mi-Yoga | |
| Specific date range filter for viewing sales numbers | Home of Yoga | — | — | Home of Yoga | |
| Create a Waivers Section and assign them to memberships/members | Brock U | — | — | Brock U | |
| Allow for 10 Minute Classes | Mass General Brigham | — | — | Mass General Brigham | |
| Handling Classes with 0 attendance in Payroll | Gem Sessions | Gem Sessions | — | — | |
| Use saved card from member profile when performing a Sale | Ryan Boylen - Sthenos | Sthenos Athletics (Ryan Boylen) | — | — | |
| CSV Report Download | Mass General Brigham | — | — | Mass General Brigham | |
| Multiple Translations | Home of Yoga | — | — | Home of Yoga | |
| Expiring Membership Report | Mass General Brigham | — | — | Mass General Brigham | |
| Add credit expiration to Package Pricing squares | Kula | — | — | Kula | |
| Integrate with Calendar App | Several | — | — | Several | |
| Recurring Billing for Packages | Straight Shot Training | — | — | Straight Shot Training | |
| Notifications for Coaches when Appointment booked | Talented Tenth Athletics | Talented Tenth Athletics | — | — | |
| Kiosk/Check-in View for Members | Pivotal Sports Performance | — | Pivotal Sports Performance → CARD Sports Performance? | — | |
| Enhanced Cancellation/Booking Reporting | Jinte Kula; Mass General Brigham | — | — | Jinte Kula, Mass General Brigham | |
| Tracking of Promo Code Redemptions/Conversion | Home of Yoga | — | — | Home of Yoga | |
| Filter on Schedule Page to show Full/Not Full sessions | Mass General Brigham | — | — | Mass General Brigham | |
| Allow for Promo Codes to be set for more than one billing cycle | SPR | SPR Conditioning | — | — | |
| Ability to view attendees for classes in a report | Home of Yoga | — | — | Home of Yoga | |
| Ability to link/nest member profiles | Pivotal Sports Performance, Full Throttle Fitness | Full Throttle Fitness & Performance, LLC | Pivotal Sports Performance → CARD Sports Performance? | — | |
| At-Risk Member Report | Home of Yoga | — | — | Home of Yoga | |
| Allow for manual override of schedule conflicts | Lockeroom | — | — | Lockeroom | |
| Ability to Charge Cancellation Fee | Off-Field | — | — | Off-Field | |
| Custom Fields for Invoices | Youth Peak Performance, LPL, Youthlete Academy | Youth Peak Performance, LPL, Youthlete Academy | — | — | |

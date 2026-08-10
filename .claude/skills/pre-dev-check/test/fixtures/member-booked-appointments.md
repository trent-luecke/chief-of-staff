# Shaping session — Member-booked appointments

_Transcript · Trent + Teofe · shaping call (post-shaping, ready for dev handoff)_

---

**Trent:** Okay, the one I want to lock down today is member-booked appointments. Right now if a member wants a session — a PT slot, an assessment, whatever appointment type the studio offers — they have to text the front desk or catch a coach in person, and then a staff member goes into the studio view and books it for them. That's the friction. Every studio owner I've talked to this quarter has asked for it: "why can't my clients just book themselves?"

**Teofe:** Right, so the ask is self-service booking. The member opens the client app, picks an appointment type, picks a time, and it's booked — no staff member in the loop.

**Trent:** Exactly. Today the only way an appointment gets on the calendar is a staff person doing it from the admin side. We want to flip that so the member can do it themselves from the client app.

**Teofe:** Let me make sure I've got the shape of it. The intent: reduce the manual back-and-forth, let members self-book appointments from the client app instead of a staff member booking it in the studio view. That's the feature.

**Trent:** That's the feature. Nail the flow and we ship it.

**Teofe:** So walk me through what actually changes. Today, who can create an appointment booking?

**Trent:** Staff only. Front desk, admins, owners — they're the ones in the studio view. The member has never been able to initiate it. They show up, they attend, that's the extent of it on the appointment side.

**Teofe:** And after this change?

**Trent:** The member initiates it. That's the whole point. So the actor doing the booking flips from a staff user to the member themselves.

**Teofe:** Okay, so that's the big one — actor change. It moves from staff-initiated to member-initiated. And the entry point moves too, right? Today it comes in through the studio/admin view. Now it needs to come in through the client app.

**Trent:** Yeah. New entry point on the client side. Member picks the appointment type from a list the studio has published as bookable, picks an open time, confirms. The studio-view path still exists for staff who want to book on someone's behalf — we're not removing that. We're adding the member path alongside it.

**Teofe:** Got it. So studios will need a way to mark which appointment types are member-bookable versus staff-only, and set the windows members are allowed to book into.

**Trent:** Right — a studio setting. Some appointment types they'll want open to self-booking, some they'll want to keep behind the desk. And they'll want to cap how far out a member can book, maybe a minimum notice window so nobody books a slot ten minutes from now.

**Teofe:** And availability — the member should only see times that are actually open. That's coming off the coach's existing calendar and the appointment type's duration?

**Trent:** Yes. Whatever slots are free on the coach's schedule for that appointment type. Same availability the front desk sees today, just exposed to the member. When they confirm, it lands on the calendar as a real booking, same as if the front desk had done it — the coach sees it, the member gets a confirmation.

**Teofe:** What about the member changing their mind — cancel or reschedule?

**Trent:** Let's keep v1 tight. Booking only. If they need to cancel they still go through the front desk for now. We can do member-side cancel as a fast follow, but I don't want to widen the scope today. Ship self-booking, prove the demand is real, then layer cancel on top.

**Teofe:** Reasonable. So v1 scope: member initiates an appointment booking from the client app; studio controls which appointment types are bookable and the notice/horizon windows; availability comes off the coach calendar; confirmation to member and coach. Cancel and reschedule stay staff-only for now.

**Trent:** That's it. This is the one studios keep asking for. I want to get it in front of the devs this week.

**Teofe:** I'll write it up. Should be a clean one — we already have appointment booking, we're basically opening a new door into it from the member side.

**Trent:** Exactly. Same destination, new door.

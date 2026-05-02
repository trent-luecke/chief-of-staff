# Chief of Staff Research

Five reference examples — a mix of deep technical builds and strategic frameworks.

---

## 1. "I Built an AI Chief of Staff That Runs My Life While I Sleep" — Doney Li
https://doneyli.substack.com/p/i-built-an-ai-chief-of-staff-that

Probably the closest to what you want. He built a multi-tenant system with tiered email processing — urgent scanning every 30 minutes using pure rules (no LLM, zero cost), full email triage with Claude at 5pm, daily briefing at 5:30pm, and a nightly memory reflection step. The key insight he landed on: separate urgency detection from deep analysis. He also has an interactive mode via Signal bot where he can text it natural language requests from his phone.

---

## 2. "My Whole Productivity System is Two Claude AI Skills" — Knowledge Work Substack
https://knowledgework.substack.com/p/my-whole-productivity-system-is-two

Focused and practical — the author built just two Claude Code skills (weekly planning + morning brief) and says it gave him the most focused quarter he's ever had in his business. Good example of keeping scope tight rather than over-engineering.

---

## 3. "Chief of Staff: A Local-First AI Assistant That Prepares Your Daily Workflow" — Ceaksan
https://ceaksan.com/en/chief-of-staff-local-ai-assistant/

Technical deep dive — built with Claude Code, Python, and SQLite. Collects Gmail, calendar, RSS feeds, and Obsidian tasks overnight, classifies them, and delivers a morning briefing as an Obsidian Daily Note. The architecture is clean: each layer works independently and delivers value on its own. Very similar to the gws CLI + local Python approach used here.

---

## 4. "I Made an AI My Chief of Staff" — Tess Posner (RESONANCE)
https://carbonandcode.substack.com/p/i-made-an-ai-my-chief-of-staff

More strategic than technical — she built a personal dashboard with schedule, active projects, and follow-ups, plus a daily AI news briefing and a CRM that tracks contacts and surfaces follow-ups automatically. Good for thinking about the "what" rather than the "how."

---

## 5. "#105: How I Built My AI Chief of Staff" — Michael Leibovich (Adobe GM), Supra Insider
https://suprainsider.substack.com/p/105-how-i-built-my-ai-chief-of-staff

Podcast/transcript but really valuable. He built his system on Claude Code using nothing but folders and markdown files — a people file that auto-updates from meeting transcripts, a knowledge graph that grows over time, and scheduled tasks for daily meeting processing and weekly competitive intel. His architecture is essentially managed markdown files as the source of truth, not a database.

---

## Notes

- **Most architecturally relevant:** Doney Li (#1) and Ceaksan (#3)
- **Best "keep it simple" counterweight:** Knowledge Work (#2) — good check against over-scoping
- **Strategic inspiration:** Tess Posner (#4) and Michael Leibovich (#5)

Feed Claude Code these URLs and tell it to read them with `web_fetch` before starting a planning interview.

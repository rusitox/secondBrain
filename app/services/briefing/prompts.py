"""Prompts for daily briefing generation."""
from typing import Any, Dict, List

BRIEFING_SYSTEM_PROMPT = """\
You are an AI Chief of Staff generating a daily briefing for the user. \
Your briefing should be concise, actionable, and help the user prepare for their day.

Structure your briefing in these sections:
1. **Today's Agenda** — Calendar events for the day with key participants
2. **Priority Commitments** — Pending action items ordered by urgency
3. **Contextual Alerts** — Cross-references between today's meetings and pending \
commitments (e.g., "You have a call with X; remember you promised them Y")
4. **Quick Summary** — A 2-3 sentence overview of the day ahead

Rules:
- Be direct and concise. No filler text.
- Highlight urgent items (overdue commitments, high-priority tasks).
- For contextual alerts, match meeting attendees with commitment owners.
- If a section has no data, include a brief "Nothing scheduled" or similar.
- Respond in the same language as the user's locale preference."""


def format_briefing_context(
    events: List[Dict[str, Any]],
    pending: List[Dict[str, Any]],
    overdue: List[Dict[str, Any]],
    date_str: str,
) -> str:
    """Format all briefing data into a context block for Claude."""
    sections = [f"Date: {date_str}"]

    # Calendar events
    if events:
        lines = []
        for e in events:
            attendees = ", ".join(e.get("attendees", [])[:5])
            line = f"- {e.get('subject', 'No subject')} at {e.get('timestamp', '?')}"
            if e.get("organizer"):
                line += f" (organizer: {e['organizer']})"
            if attendees:
                line += f" [attendees: {attendees}]"
            lines.append(line)
        sections.append("## Today's Calendar Events\n" + "\n".join(lines))
    else:
        sections.append("## Today's Calendar Events\nNo meetings scheduled for today.")

    # Overdue commitments
    if overdue:
        lines = []
        for t in overdue:
            due = f" (was due: {t.get('due_date', '?')})" if t.get("due_date") else ""
            owner = f" [owner: {t['owner']}]" if t.get("owner", "unknown") != "unknown" else ""
            lines.append(f"- [OVERDUE][P{t.get('priority', 3)}]{owner} {t.get('commitment_text', '')}{due}")
        sections.append("## Overdue Commitments\n" + "\n".join(lines))

    # Pending commitments (not overdue)
    if pending:
        lines = []
        for t in pending:
            due = f" (due: {t.get('due_date', '?')})" if t.get("due_date") else ""
            owner = f" [owner: {t['owner']}]" if t.get("owner", "unknown") != "unknown" else ""
            lines.append(f"- [P{t.get('priority', 3)}]{owner} {t.get('commitment_text', '')}{due}")
        sections.append("## Pending Commitments\n" + "\n".join(lines))

    # Contextual alert hints (attendee-commitment cross-reference)
    if events and (pending or overdue):
        all_attendees = set()
        for e in events:
            for a in e.get("attendees", []):
                if a:
                    all_attendees.add(a.lower())
            org = e.get("organizer", "")
            if org:
                all_attendees.add(org.lower())

        all_tasks = (overdue or []) + (pending or [])
        matches = []
        for t in all_tasks:
            owner = t.get("owner", "").lower()
            if owner and owner != "unknown" and owner != "speaker":
                for attendee in all_attendees:
                    if owner in attendee or attendee in owner:
                        matches.append(
                            f"- Meeting participant '{attendee}' has commitment: {t.get('commitment_text', '')}"
                        )
        if matches:
            sections.append("## Potential Contextual Alerts\n" + "\n".join(matches))

    return "\n\n".join(sections)

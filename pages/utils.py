from datetime import date
import os
import logging

from utils.festival_dates import get_all_events_for_year
from aa.llm_client import call_llm, LLMError, LIGHT_MODEL

logger = logging.getLogger(__name__)


def get_upcoming_events(days_ahead=30):
    """
    Get upcoming holidays and events within the specified days ahead.
    Uses verified year-specific festival dates (no hardcoded approximations).
    """
    today = date.today()
    upcoming_events = []

    # Gather events for this year and next (to cover year-end look-ahead)
    events = get_all_events_for_year(today.year)
    if days_ahead > 0:
        events += get_all_events_for_year(today.year + 1)

    for ev in events:
        ev_date = ev['date']
        days_until = (ev_date - today).days
        if 0 <= days_until <= days_ahead:
            upcoming_events.append({
                'name': ev['name'],
                'date': ev_date,
                'days_until': days_until,
                'type': ev['type'],
                'date_str': ev_date.strftime('%B %d, %Y'),
                'month_day': ev_date.strftime('%B %d'),
            })

    # De-duplicate (same date could appear from both years list)
    seen = set()
    unique = []
    for ev in upcoming_events:
        key = (ev['name'], ev['date'])
        if key not in seen:
            seen.add(key)
            unique.append(ev)

    unique.sort(key=lambda x: x['date'])
    return unique

def generate_ai_insight(upcoming_events):
    """Use AI to generate insights about upcoming events."""
    if not upcoming_events:
        return "No upcoming events detected."

    next_event = upcoming_events[0]
    days = next_event['days_until']

    # Build a human-readable urgency label
    if days == 0:
        urgency = "today"
    elif days == 1:
        urgency = "tomorrow"
    else:
        urgency = f"in {days} days"

    context = (
        f"The next holiday is {next_event['name']} on {next_event['date_str']} "
        f"({urgency}). Write a one-line insight about preparing a circular for it."
    )

    try:
        insight = get_ai_insight(context)
        prefix = f"{next_event['name']} ({next_event['month_day']}) — {urgency}."
        if insight:
            return f"{prefix} {insight}"
        return f"{prefix} Circular draft recommended."
    except Exception:
        prefix = f"{next_event['name']} ({next_event['month_day']}) — {urgency}."
        return f"{prefix} Circular draft recommended."

def get_ai_insight(context: str):
    """Get AI-generated insight using the light model (fast, low latency)."""
    try:
        insight = call_llm(
            prompt=f"Brief insight for circular: {context}",
            model=LIGHT_MODEL,
            temperature=0.3,
            max_tokens=40,
            timeout=5,
        )
        return (insight[:80] + '...') if len(insight) > 80 else insight
    except (LLMError, Exception):
        return None

def get_system_insight():
    """Main function to get system insight."""
    upcoming_events = get_upcoming_events(days_ahead=30)

    if upcoming_events:
        next_event = upcoming_events[0]
        insight_text = generate_ai_insight(upcoming_events)

        return {
            'has_insight': True,
            'event_name': next_event['name'],
            'event_date': next_event['date_str'],
            'days_until': next_event['days_until'],
            'event_type': next_event['type'],
            'insight_text': insight_text,
            'auto_holiday_param': next_event['name']
        }
    else:
        return {
            'has_insight': False,
            'insight_text': 'No upcoming events detected in the next 30 days.'
        }
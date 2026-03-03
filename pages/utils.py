from datetime import datetime, timedelta
import requests
import json
import os
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Common Indian holidays and events (can be expanded)
INDIAN_HOLIDAYS = {
    # National Holidays
    'Republic Day': {'month': 1, 'day': 26, 'type': 'national'},
    'Independence Day': {'month': 8, 'day': 15, 'type': 'national'},
    'Gandhi Jayanti': {'month': 10, 'day': 2, 'type': 'national'},

    # Festival Holidays (approximate dates - can be updated annually)
    'Pongal': {'month': 1, 'day': 14, 'type': 'festival'},
    'Maha Shivaratri': {'month': 2, 'day': 17, 'type': 'festival'},
    'Holi': {'month': 3, 'day': 14, 'type': 'festival'},
    'Ram Navami': {'month': 3, 'day': 30, 'type': 'festival'},
    'Mahavir Jayanti': {'month': 4, 'day': 10, 'type': 'festival'},
    'Good Friday': {'month': 4, 'day': 18, 'type': 'festival'},
    'Buddha Purnima': {'month': 5, 'day': 12, 'type': 'festival'},
    'Eid al-Fitr': {'month': 4, 'day': 11, 'type': 'festival'},
    'Raksha Bandhan': {'month': 8, 'day': 19, 'type': 'festival'},
    'Janmashtami': {'month': 8, 'day': 26, 'type': 'festival'},
    'Ganesh Chaturthi': {'month': 9, 'day': 7, 'type': 'festival'},
    'Dussehra': {'month': 10, 'day': 12, 'type': 'festival'},
    'Diwali': {'month': 11, 'day': 4, 'type': 'festival'},
    'Christmas': {'month': 12, 'day': 25, 'type': 'festival'},

    # Academic Events
    'Semester Start': {'month': 7, 'day': 1, 'type': 'academic'},
    'Semester End': {'month': 11, 'day': 30, 'type': 'academic'},
    'Exam Week': {'month': 11, 'day': 15, 'type': 'academic'},
}

def get_upcoming_events(days_ahead=30):
    """Get upcoming holidays and events within the specified days ahead."""
    today = datetime.now()
    upcoming_events = []

    for event_name, event_info in INDIAN_HOLIDAYS.items():
        current_year = today.year
        event_date = datetime(current_year, event_info['month'], event_info['day'])

        if event_date < today:
            event_date = datetime(current_year + 1, event_info['month'], event_info['day'])

        days_until = (event_date - today).days
        if days_until <= days_ahead and days_until >= 0:
            upcoming_events.append({
                'name': event_name,
                'date': event_date,
                'days_until': days_until,
                'type': event_info['type'],
                'date_str': event_date.strftime('%B %d, %Y'),
                'month_day': event_date.strftime('%B %d')
            })

    upcoming_events.sort(key=lambda x: x['date'])
    return upcoming_events

def generate_ai_insight(upcoming_events):
    """Use AI to generate insights about upcoming events."""
    if not upcoming_events:
        return "No upcoming events detected."

    next_event = upcoming_events[0]
    context = f"Analyze {next_event['name']} on {next_event['date_str']} for educational circular needs."

    try:
        insight = get_ai_insight(context)
        return f"{next_event['name']} ({next_event['month_day']}). {insight or 'Circular recommended.'}"
    except:
        return f"{next_event['name']} ({next_event['month_day']}). Circular draft recommended."

def get_ai_insight(context):
    """Get AI-generated insight."""
    try:
        backend = os.getenv('LLM_BACKEND', 'ollama')
        model = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')
        url = os.getenv('OLLAMA_URL', 'http://localhost:11434')

        if backend.lower() == 'ollama':
            response = requests.post(
                f"{url}/api/generate",
                json={
                    "model": model,
                    "prompt": f"Brief insight for circular: {context}",
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 30}
                },
                timeout=5
            )

            if response.status_code == 200:
                result = response.json()
                insight = result.get('response', '').strip()
                return insight[:80] + '...' if len(insight) > 80 else insight

        return None
    except:
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
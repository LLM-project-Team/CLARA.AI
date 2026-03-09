"""
Verified Indian festival & national holiday dates.
Shared lookup used by both the circular generator and the system-insight
notification on the dashboard.

Fixed-date holidays repeat every year.
Variable-date (lunar calendar) festivals are indexed by year (2024-2028).
"""

from datetime import date

# ── Fixed-date holidays (same every year) ──────────────────────────────
FIXED_HOLIDAYS = {
    'new year':              (1, 1),
    "new year's day":        (1, 1),
    'pongal':                (1, 14),
    'makar sankranti':       (1, 14),
    'republic day':          (1, 26),
    'tamil new year':        (4, 14),
    'puthandu':              (4, 14),
    'vishu':                 (4, 14),
    'ambedkar jayanti':      (4, 14),
    'may day':               (5, 1),
    'labour day':            (5, 1),
    'independence day':      (8, 15),
    'gandhi jayanti':        (10, 2),
    'christmas':             (12, 25),
    'christmas day':         (12, 25),
}

# ── Variable-date festivals (lunar calendar) ────────────────────────────
VARIABLE_FESTIVALS = {
    2024: {
        'maha shivaratri':       (3, 8),
        'holi':                  (3, 25),
        'holika dahan':          (3, 24),
        'ugadi':                 (4, 9),
        'gudi padwa':            (4, 9),
        'ram navami':            (4, 17),
        'good friday':           (3, 29),
        'easter':                (3, 31),
        'eid ul-fitr':           (4, 11),
        'eid':                   (4, 11),
        'eid al-fitr':           (4, 11),
        'buddha purnima':        (5, 23),
        'eid ul-adha':           (6, 17),
        'bakrid':                (6, 17),
        'muharram':              (7, 17),
        'raksha bandhan':        (8, 19),
        'janmashtami':           (8, 26),
        'ganesh chaturthi':      (9, 7),
        'onam':                  (9, 15),
        'milad un-nabi':         (9, 17),
        'dussehra':              (10, 12),
        'vijayadashami':         (10, 12),
        'diwali':                (11, 1),
        'deepavali':             (11, 1),
        'guru nanak jayanti':    (11, 15),
    },
    2025: {
        'maha shivaratri':       (2, 26),
        'holi':                  (3, 14),
        'holika dahan':          (3, 13),
        'ugadi':                 (3, 30),
        'gudi padwa':            (3, 30),
        'ram navami':            (4, 6),
        'good friday':           (4, 18),
        'easter':                (4, 20),
        'eid ul-fitr':           (3, 31),
        'eid':                   (3, 31),
        'eid al-fitr':           (3, 31),
        'buddha purnima':        (5, 12),
        'eid ul-adha':           (6, 7),
        'bakrid':                (6, 7),
        'muharram':              (7, 6),
        'raksha bandhan':        (8, 9),
        'janmashtami':           (8, 16),
        'ganesh chaturthi':      (8, 27),
        'onam':                  (9, 5),
        'milad un-nabi':         (9, 5),
        'dussehra':              (10, 2),
        'vijayadashami':         (10, 2),
        'diwali':                (10, 20),
        'deepavali':             (10, 20),
        'guru nanak jayanti':    (11, 5),
    },
    2026: {
        'maha shivaratri':       (2, 15),
        'holi':                  (3, 4),
        'holika dahan':          (3, 3),
        'ugadi':                 (3, 19),
        'gudi padwa':            (3, 19),
        'ram navami':            (3, 27),
        'good friday':           (4, 3),
        'easter':                (4, 5),
        'eid ul-fitr':           (3, 21),
        'eid':                   (3, 21),
        'eid al-fitr':           (3, 21),
        'buddha purnima':        (5, 1),
        'eid ul-adha':           (5, 27),
        'bakrid':                (5, 27),
        'muharram':              (6, 26),
        'raksha bandhan':        (8, 28),
        'janmashtami':           (9, 4),
        'ganesh chaturthi':      (9, 16),
        'onam':                  (8, 25),
        'milad un-nabi':         (8, 26),
        'dussehra':              (10, 20),
        'vijayadashami':         (10, 20),
        'diwali':                (11, 8),
        'deepavali':             (11, 8),
        'guru nanak jayanti':    (11, 24),
    },
    2027: {
        'maha shivaratri':       (2, 4),
        'holi':                  (3, 22),
        'holika dahan':          (3, 21),
        'ugadi':                 (3, 8),
        'gudi padwa':            (3, 8),
        'ram navami':            (3, 16),
        'good friday':           (3, 26),
        'easter':                (3, 28),
        'eid ul-fitr':           (3, 10),
        'eid':                   (3, 10),
        'eid al-fitr':           (3, 10),
        'buddha purnima':        (5, 20),
        'eid ul-adha':           (5, 16),
        'bakrid':                (5, 16),
        'muharram':              (6, 16),
        'raksha bandhan':        (8, 17),
        'janmashtami':           (8, 25),
        'ganesh chaturthi':      (9, 5),
        'onam':                  (9, 14),
        'milad un-nabi':         (8, 15),
        'dussehra':              (10, 9),
        'vijayadashami':         (10, 9),
        'diwali':                (10, 29),
        'deepavali':             (10, 29),
        'guru nanak jayanti':    (11, 14),
    },
    2028: {
        'maha shivaratri':       (2, 23),
        'holi':                  (3, 11),
        'holika dahan':          (3, 10),
        'ugadi':                 (3, 26),
        'gudi padwa':            (3, 26),
        'ram navami':            (4, 3),
        'good friday':           (4, 14),
        'easter':                (4, 16),
        'eid ul-fitr':           (2, 27),
        'eid':                   (2, 27),
        'eid al-fitr':           (2, 27),
        'buddha purnima':        (5, 9),
        'eid ul-adha':           (5, 6),
        'bakrid':                (5, 6),
        'muharram':              (6, 5),
        'raksha bandhan':        (8, 6),
        'janmashtami':           (8, 14),
        'ganesh chaturthi':      (8, 25),
        'onam':                  (9, 3),
        'milad un-nabi':         (8, 5),
        'dussehra':              (9, 28),
        'vijayadashami':         (9, 28),
        'diwali':                (10, 17),
        'deepavali':             (10, 17),
        'guru nanak jayanti':    (11, 2),
    },
}

# Canonical display names (avoid duplicates like eid/eid al-fitr/eid ul-fitr)
_DISPLAY_NAMES = {
    'new year':              'New Year',
    "new year's day":        "New Year's Day",
    'pongal':                'Pongal',
    'makar sankranti':       'Makar Sankranti',
    'republic day':          'Republic Day',
    'tamil new year':        'Tamil New Year',
    'puthandu':              'Puthandu',
    'vishu':                 'Vishu',
    'ambedkar jayanti':      'Ambedkar Jayanti',
    'may day':               'May Day',
    'labour day':            'Labour Day',
    'independence day':      'Independence Day',
    'gandhi jayanti':        'Gandhi Jayanti',
    'christmas':             'Christmas',
    'christmas day':         'Christmas Day',
    'maha shivaratri':       'Maha Shivaratri',
    'holi':                  'Holi',
    'holika dahan':          'Holika Dahan',
    'ugadi':                 'Ugadi',
    'gudi padwa':            'Gudi Padwa',
    'ram navami':            'Ram Navami',
    'good friday':           'Good Friday',
    'easter':                'Easter',
    'eid ul-fitr':           'Eid ul-Fitr',
    'eid':                   'Eid',
    'eid al-fitr':           'Eid al-Fitr',
    'buddha purnima':        'Buddha Purnima',
    'eid ul-adha':           'Eid ul-Adha',
    'bakrid':                'Bakrid',
    'muharram':              'Muharram',
    'raksha bandhan':        'Raksha Bandhan',
    'janmashtami':           'Janmashtami',
    'ganesh chaturthi':      'Ganesh Chaturthi',
    'onam':                  'Onam',
    'milad un-nabi':         'Milad un-Nabi',
    'dussehra':              'Dussehra',
    'vijayadashami':         'Vijayadashami',
    'diwali':                'Diwali',
    'deepavali':             'Deepavali',
    'guru nanak jayanti':    'Guru Nanak Jayanti',
}

# Keys that are aliases – skip to avoid duplicate entries in the list
_ALIAS_KEYS = {
    "new year's day", 'christmas day', 'eid', 'eid al-fitr',
    'deepavali', 'vijayadashami', 'bakrid', 'gudi padwa',
    'makar sankranti', 'puthandu', 'vishu', 'labour day',
}


def get_all_events_for_year(year):
    """
    Return a sorted list of **unique** events with their real dates for *year*.
    Each item: {'name': str, 'date': date, 'type': str}
    """
    events = []
    seen_dates: set[tuple[int, int]] = set()          # (month, day) de-dup

    # Fixed
    for key, (m, d) in FIXED_HOLIDAYS.items():
        if key in _ALIAS_KEYS:
            continue
        md = (m, d)
        if md in seen_dates:
            continue
        seen_dates.add(md)
        events.append({
            'name': _DISPLAY_NAMES.get(key, key.title()),
            'date': date(year, m, d),
            'type': 'national' if key in ('republic day', 'independence day', 'gandhi jayanti') else 'festival',
        })

    # Variable
    year_festivals = VARIABLE_FESTIVALS.get(year, {})
    for key, (m, d) in year_festivals.items():
        if key in _ALIAS_KEYS:
            continue
        md = (m, d)
        if md in seen_dates:
            continue
        seen_dates.add(md)
        events.append({
            'name': _DISPLAY_NAMES.get(key, key.title()),
            'date': date(year, m, d),
            'type': 'festival',
        })

    events.sort(key=lambda e: e['date'])
    return events


def resolve_festival_date(occasion, year=None):
    """
    Return the human-readable date string for *occasion* in *year*.
    Falls back to '[Enter Date]' if not found.
    """
    if year is None:
        year = date.today().year
    occasion_lower = occasion.strip().lower()

    # 1) Fixed holidays
    for key, (m, d) in FIXED_HOLIDAYS.items():
        if key in occasion_lower:
            return f"{date(year, m, d).strftime('%B')} {d}, {year}"

    # 2) Variable festivals for year
    year_festivals = VARIABLE_FESTIVALS.get(year, {})
    for key, (m, d) in year_festivals.items():
        if key in occasion_lower or occasion_lower in key:
            return f"{date(year, m, d).strftime('%B')} {d}, {year}"

    # 3) Partial / fuzzy match
    for key, (m, d) in year_festivals.items():
        key_words = key.split()
        if any(word in occasion_lower for word in key_words if len(word) > 3):
            return f"{date(year, m, d).strftime('%B')} {d}, {year}"

    return '[Enter Date]'

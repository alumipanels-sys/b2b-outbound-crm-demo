"""Holiday Calendar — skip sending during major holidays.

European, Middle East, and US holidays that affect B2B outreach timing.
Loaded by followup_engine._get_next_business_time() to auto-defer.
"""

from datetime import date, timedelta
from typing import Set, Tuple, Optional

# ── Annual fixed-date holidays (month, day) ──
FIXED_HOLIDAYS = {
    # --- Germany / DACH ---
    (1, 1): "New Year (DE/AT/CH)",
    (1, 6): "Epiphany (DE: BW/BY/ST)",  # partial
    (5, 1): "Labour Day (DE/AT/CH)",
    (8, 15): "Assumption Day (DE: BY/SL, AT)",  # partial
    (10, 3): "German Unity Day (DE)",
    (10, 26): "National Day (AT)",
    (10, 31): "Reformation Day (DE: BB/MV/SN/ST/TH)",  # partial
    (11, 1): "All Saints (DE: BW/BY/NW/RP/SL, AT)",
    (12, 24): "Christmas Eve (DE/AT/CH) — no business",
    (12, 25): "Christmas Day (DE/AT/CH)",
    (12, 26): "2nd Christmas Day (DE/AT/CH)",
    (12, 31): "New Year's Eve (DE/AT/CH) — no business",
    # --- France ---
    (7, 14): "Bastille Day (FR)",
    (8, 15): "Assumption Day (FR)",
    (11, 1): "All Saints (FR)",
    (11, 11): "Armistice Day (FR)",
    # --- UK ---
    (12, 25): "Christmas Day (UK)",
    (12, 26): "Boxing Day (UK)",
    # --- US ---
    (7, 4): "Independence Day (US)",
    (11, 27): "Thanksgiving (US, 4th Thu — approximate)",
    (11, 28): "Black Friday (US)",
    (12, 25): "Christmas Day (US)",
    # --- Middle East ---
    # (Ramadan/Eid are lunar — handled separately)
    # --- Japan ---
    (1, 1): "New Year (JP)",
    (12, 31): "New Year's Eve (JP)",
}

# ── Extended no-fly zones (month ranges) ──
# During these periods, cold outbound is skipped entirely.
# Warm replies are still handled (response is expected).
NO_FLY_ZONES = [
    # Christmas/New Year — all of Europe shuts down
    ("European Christmas Shutdown", (12, 18), (1, 6)),
    # Ramadan — vary by year. Rough window: Mar-May for 2026.
    # Actual dates: 2026-02-18 through 2026-03-19 (approximate)
    # For 2027: ~ 2027-02-08 through 2027-03-09
    # We use a fuzzy window that we update annually
    ("Ramadan 2026", (2, 18), (3, 19)),
    ("Ramadan 2027", (2, 8), (3, 9)),
    # Chinese New Year — factory closed, but prospecting can continue
    # 2026: Feb 17, 2027: Feb 6
    ("Chinese New Year 2026", (2, 14), (2, 22)),
    ("Chinese New Year 2027", (2, 3), (2, 11)),
]

# ── Country-specific no-fly zones ──
# For warm replies during summer, still respond — just don't initiate cold.
# But for certain countries, even warm replies can wait.
COUNTRY_SILENCE_WINDOWS = {
    # Germany: July 15 - August 31 = vacation. Many companies run skeleton crew.
    # Christmas shutdown is broader: Dec 18 - Jan 6
    "DE": [("Summer", (7, 15), (8, 31)), ("Christmas", (12, 18), (1, 6))],
    "AT": [("Summer", (7, 15), (8, 31)), ("Christmas", (12, 18), (1, 6))],
    "CH": [("Summer", (7, 15), (8, 31)), ("Christmas", (12, 18), (1, 6))],
    # Italy: August is dead
    "IT": [("Ferragosto", (8, 1), (8, 31)), ("Christmas", (12, 20), (1, 7))],
    # France: August
    "FR": [("Summer", (7, 25), (8, 25)), ("Christmas", (12, 20), (1, 5))],
    # Turkey: Ramadan + Eid (lunar — handled in NO_FLY_ZONES)
    # UAE/KSA: Ramadan + Eid
    "AE": [("Ramadan 2026", (2, 18), (3, 19))],
    "SA": [("Ramadan 2026", (2, 18), (3, 19))],
}


def is_fixed_holiday(d: date) -> Optional[str]:
    """Return holiday name if d is a fixed-date holiday, else None."""
    if hasattr(d, 'date'):
        d = d.date()
    key = (d.month, d.day)
    return FIXED_HOLIDAYS.get(key)


def is_in_no_fly_zone(d: date) -> Optional[str]:
    """Return zone name if d falls in a no-fly zone, else None."""
    if hasattr(d, 'date'):
        d = d.date()
    for name, start, end in NO_FLY_ZONES:
        start_date = date(d.year, start[0], start[1])
        end_date = date(d.year, end[0], end[1])
        # Handle year-crossing windows (e.g. Christmas: Dec 18 -> Jan 6 next year)
        if start_date > end_date:
            # Crosses year boundary
            if d >= start_date or d <= end_date:
                return name
        else:
            if start_date <= d <= end_date:
                return name
    return None


def is_country_silent(d: date, country_code: str) -> Optional[str]:
    """Return window name if country is in a silence window, else None."""
    if hasattr(d, 'date'):
        d = d.date()
    windows = COUNTRY_SILENCE_WINDOWS.get((country_code or "").strip().upper(), [])
    for name, start, end in windows:
        start_date = date(d.year, start[0], start[1])
        end_date = date(d.year, end[0], end[1])
        if start_date <= d <= end_date:
            return name
    return None


def should_skip_cold_outreach(d: date, country_code: str = None) -> Tuple[bool, str]:
    """Decide whether to skip cold outreach on this date.

    Returns (skip: bool, reason: str).

    Logic:
    1. Weekend → skip (handled by _get_next_business_time, not here)
    2. Fixed holiday → skip for cold, allow for warm
    3. No-fly zone → skip for cold
    4. Country silence window → skip for cold
    5. Otherwise → allow
    """
    # Check no-fly zones first (broadest)
    zone = is_in_no_fly_zone(d)
    if zone:
        return True, f"No-fly zone: {zone}"

    # Check country-specific silence
    country_silent = is_country_silent(d, country_code) if country_code else None
    if country_silent:
        return True, f"Country silence: {country_code} - {country_silent}"

    # Check fixed holiday
    holiday = is_fixed_holiday(d)
    if holiday:
        return True, f"Holiday: {holiday}"

    return False, ""


def get_holiday_context_for_country(country_code: str, d: date = None) -> str:
    """Return a brief note about upcoming holidays for AI context.

    Example: 'Germany (DE): Summer break until Aug 31. Next potential outreach: Sep 1.'"""
    if d is None:
        d = date.today()

    code = (country_code or "").strip().upper()
    parts = []

    # Check if currently in a no-fly zone
    zone = is_in_no_fly_zone(d)
    if zone:
        parts.append(f"Currently in {zone} — outreach may go unnoticed.")

    # Check country silence
    windows = COUNTRY_SILENCE_WINDOWS.get(code, [])
    for name, start, end in windows:
        start_date = date(d.year, start[0], start[1])
        end_date = date(d.year, end[0], end[1])
        if start_date <= d <= end_date:
            parts.append(
                f"{name}: {start_date.strftime('%b %d')} → {end_date.strftime('%b %d')}"
                f" — decision-makers likely out of office."
            )
        else:
            # Show upcoming windows within 30 days
            if d < start_date <= d + timedelta(days=30):
                parts.append(
                    f"Upcoming: {name} {start_date.strftime('%b %d')} → "
                    f"{end_date.strftime('%b %d')} — plan outreach before or after."
                )

    return "; ".join(parts) if parts else "No major holidays affecting outreach."

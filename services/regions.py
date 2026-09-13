"""Country -> region grouping for customer-list filtering."""

REGIONS = {
    "europe": {
        "label": "Europe",
        "countries": {
            "DE", "AT", "CH", "NL", "BE", "FR", "ES", "IT", "PT", "GB", "IE",
            "PL", "CZ", "SK", "HU", "RO", "BG", "HR", "SI", "EE", "LV", "LT",
            "GR", "SE", "NO", "FI", "DK", "UA",
        },
    },
    "middle_east": {
        "label": "Middle East",
        "countries": {"AE", "SA", "QA", "KW", "OM", "BH", "JO", "IL", "TR", "IQ"},
    },
    "asia": {
        "label": "Asia",
        "countries": {
            "CN", "HK", "TW", "JP", "KR", "IN", "PK", "BD", "LK", "SG",
            "MY", "TH", "VN", "ID", "PH",
        },
    },
    "americas": {
        "label": "Americas",
        "countries": {"US", "CA", "MX", "BR", "AR", "CL", "CO", "PE"},
    },
    "africa": {
        "label": "Africa",
        "countries": {"ZA", "NG", "KE", "EG", "MA", "TN"},
    },
    "oceania": {
        "label": "Oceania",
        "countries": {"AU", "NZ"},
    },
}

ALL_KNOWN_COUNTRIES = set()
for _info in REGIONS.values():
    ALL_KNOWN_COUNTRIES |= _info["countries"]


def region_countries(code: str):
    """Return the country set for a region code, or None if unknown."""
    info = REGIONS.get((code or "").strip().lower())
    return info["countries"] if info else None

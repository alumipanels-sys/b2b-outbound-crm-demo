"""Whois domain lookup service — queries domain registration data via raw whois protocol.

No external dependencies — uses plain sockets to whois servers.
"""

import logging
import re
import socket
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Known whois servers for common TLDs ──
WHOIS_SERVERS = {
    "com": "whois.verisign-grs.com",
    "net": "whois.verisign-grs.com",
    "org": "whois.pir.org",
    "de": "whois.denic.de",
    "co.uk": "whois.nic.uk",
    "eu": "whois.eu",
    "fr": "whois.nic.fr",
    "it": "whois.nic.it",
    "ch": "whois.nic.ch",
    "at": "whois.nic.at",
    "be": "whois.dns.be",
    "nl": "whois.domain-registry.nl",
    "es": "whois.nic.es",
    "pl": "whois.dns.pl",
    "ru": "whois.tcinet.ru",
    "cn": "whois.cnnic.cn",
    "jp": "whois.jprs.jp",
    "br": "whois.registro.br",
    "ca": "whois.cira.ca",
    "au": "whois.audns.net.au",
    "in": "whois.registry.in",
}

# Date patterns commonly found in whois output
DATE_PATTERNS = [
    # ISO formats
    (re.compile(r"(?:Creation\s*Date|created|Registered\s*on|Domain\s*Registration\s*Date)\s*:\s*(\d{4}[-/]\d{2}[-/]\d{2})", re.IGNORECASE), "created"),
    (re.compile(r"(?:Registry\s*Expiry\s*Date|Expiry\s*Date|Expiration\s*Date|expires)\s*:\s*(\d{4}[-/]\d{2}[-/]\d{2})", re.IGNORECASE), "expires"),
    # IANA-like format: Creation Date: 2020-01-15T00:00:00Z
    (re.compile(r"(?:Creation\s*Date|created)\s*:\s*(\d{4}-\d{2}-\d{2})T", re.IGNORECASE), "created"),
    (re.compile(r"(?:Registry\s*Expiry\s*Date|Expiry\s*Date)\s*:\s*(\d{4}-\d{2}-\d{2})T", re.IGNORECASE), "expires"),
    # Denic format: Changed/Updated
    (re.compile(r"(?:Created|Domain\s*created)\s*:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE), "created"),
    (re.compile(r"(?:Expires|Domain\s*expires)\s*:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE), "expires"),
]


def extract_domain(url: str) -> str | None:
    """Extract bare domain (e.g. example.com) from a URL."""
    if not url:
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        # Remove port if present
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain if "." in domain else None
    except Exception:
        return None


def _raw_whois(domain: str, server: str = None) -> str:
    """Perform a raw whois query via TCP socket on port 43."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(8)
        if server:
            s.connect((server, 43))
        else:
            # Query IANA first to find the right whois server
            s.connect(("whois.iana.org", 43))
        s.send(f"{domain}\r\n".encode())
        data = b""
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            except socket.timeout:
                break
        s.close()
        return data.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("Whois query failed for %s: %s", domain, e)
        return ""


def _find_referral_server(whois_text: str) -> str | None:
    """Find the 'refer:' or 'whois:' line that points to the actual whois server."""
    for pattern in [r"(?:refer|whois)\s*:\s*(\S+)", r"Registrar\s*WHOIS\s*Server\s*:\s*(\S+)"]:
        m = re.search(pattern, whois_text, re.IGNORECASE)
        if m:
            server = m.group(1).strip().lower()
            if server and server != "whois.iana.org":
                return server
    return None


def _parse_dates(text: str) -> dict:
    """Parse creation and expiry dates from whois text."""
    result = {"created": None, "expires": None}
    for pattern, field in DATE_PATTERNS:
        if result[field]:
            continue
        m = pattern.search(text)
        if m:
            date_str = m.group(1).replace("/", "-")
            try:
                result[field] = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except ValueError:
                pass
    return result


def _parse_registrar(text: str) -> str | None:
    """Extract registrar name from whois text."""
    patterns = [
        r"Registrar\s*:\s*(.+?)(?:\r?\n|$)",
        r"Sponsoring\s*Registrar\s*(?:IANA\s*)?ID\s*:\s*\d+\s+(.+?)(?:\r?\n|$)",
        r"registrar\s*:\s*(.+?)(?:\r?\n|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:200]
    return None


def lookup_whois(url: str, timeout: int = 10) -> dict:
    """Look up whois information for a domain.

    Returns dict with:
        domain: str
        registered_at: datetime or None
        expires_at: datetime or None
        registrar: str or None
        raw_text: str (first 2000 chars of whois response)
        error: str or None
    """
    domain = extract_domain(url)
    if not domain:
        return {"domain": url, "error": "Could not extract domain from URL"}

    result = {
        "domain": domain,
        "registered_at": None,
        "expires_at": None,
        "registrar": None,
        "raw_text": "",
        "error": None,
    }

    # Step 1: Query IANA to find the right whois server
    iana_response = _raw_whois(domain)
    if not iana_response.strip():
        result["error"] = "Whois query returned empty (network/timing out?)"
        return result

    referral = _find_referral_server(iana_response)

    # Step 2: Query the actual whois server
    if referral:
        whois_response = _raw_whois(domain, referral)
    else:
        # Fallback: try TLD-specific server
        tld = domain.rsplit(".", 1)[-1].lower()
        tld_server = WHOIS_SERVERS.get(tld)
        if tld_server:
            whois_response = _raw_whois(domain, tld_server)
        else:
            whois_response = iana_response  # use IANA response as best effort

    if not whois_response.strip():
        result["error"] = "Whois server returned empty response"
        return result

    # Step 3: Parse dates and registrar
    combined = iana_response + "\n" + whois_response
    dates = _parse_dates(combined)
    result["registered_at"] = dates["created"]
    result["expires_at"] = dates["expires"]
    result["registrar"] = _parse_registrar(combined)
    result["raw_text"] = whois_response[:2000]

    if dates["created"]:
        logger.info("Whois: %s registered %s, expires %s", domain, dates["created"].strftime("%Y-%m-%d"), dates["expires"].strftime("%Y-%m-%d") if dates["expires"] else "unknown")
    else:
        logger.info("Whois: %s — no creation date found in response", domain)

    return result


# ── Optional: python-whois based lookup (more reliable, but requires pip install) ──

def lookup_whois_python_whois(url: str) -> dict:
    """Lookup using python-whois library if available. Falls back to raw whois."""
    domain = extract_domain(url)
    if not domain:
        return {"domain": url, "error": "Could not extract domain"}

    result = {
        "domain": domain,
        "registered_at": None,
        "expires_at": None,
        "registrar": None,
        "raw_text": "",
        "error": None,
    }

    try:
        import whois
        w = whois.whois(domain)
        result["raw_text"] = str(w)[:2000]

        # Creation date — may be a list or single datetime
        cd = w.creation_date
        if isinstance(cd, list):
            cd = cd[0] if cd else None
        if cd:
            result["registered_at"] = cd if isinstance(cd, datetime) else None

        # Expiry date
        ed = w.expiration_date
        if isinstance(ed, list):
            ed = ed[0] if ed else None
        if ed:
            result["expires_at"] = ed if isinstance(ed, datetime) else None

        # Registrar
        result["registrar"] = w.registrar[:200] if w.registrar else None

        return result
    except ImportError:
        logger.debug("python-whois not installed, falling back to raw whois")
        return lookup_whois(url)
    except Exception as e:
        logger.warning("python-whois failed for %s: %s, trying raw whois", domain, e)
        return lookup_whois(url)

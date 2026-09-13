"""Email verification service — 4-layer checks.

1. Syntax — regex format check (instant)
2. Disposable/Role — known trash domains + generic role prefixes (instant)
3. MX record — DNS lookup for mail server (1-3s)
4. SMTP handshake — connect, HELO, MAIL FROM, RCPT TO (5-10s, optional)

Returns a verification score 0-100 and detailed breakdown.
"""
import json
import logging
import re
import socket
import smtplib
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Known disposable email domains ──
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "10minutemail.com",
    "yopmail.com", "throwaway.email", "sharklasers.com", "trashmail.com",
    "maildrop.cc", "getnada.com", "dispostable.com", "temp-mail.org",
    "fakeinbox.com", "moakt.com", "spamgourmet.com", "mytemp.email",
    "tempinbox.com", "emailondeck.com", "guerrillamail.info", "guerrillamail.biz",
    "guerrillamail.org", "guerrillamail.net", "mailnesia.com", "spam4.me",
    "spambox.us", "spambox.me", "dropmail.me", "tmpmail.org", "tmpbox.net",
    "recardopastor.com", "chacuo.net", "bccto.me", "incognitomail.com",
    "mailcatch.com", "0wnd.net", "0wnd.org", "mintemail.com", "mailfence.com",
    "owlymail.com", "gishpuppy.com", "anonbox.net", "hidemail.de",
    "deadaddress.com", "spamdecoy.net", "trashmail.de", "spam.la",
    "objectmail.com", "brennendesreich.de", "wegwerfemail.de",
    "jetable.org", "jetable.net", "nospam.ze.tc", "no-spam.hu", "mytrashmail.com",
}

# ── Generic/Role email prefixes that never belong to a real decision maker ──
ROLE_PREFIXES = {
    "info", "sales", "support", "admin", "contact", "hello", "office",
    "service", "help", "marketing", "webmaster", "postmaster", "abuse",
    "noreply", "no-reply", "noreply", "team", "careers", "jobs", "hr",
    "billing", "invoices", "orders", "enquiries", "enquiry", "mail",
    "general", "inquiry", "press", "media", "pr", "accounts", "finance",
    "customercare", "customerservice", "customer", "feedback", "complaints",
    "queries", "quotation", "purchase", "purchasing", "procure",
}


def _check_syntax(email: str) -> dict:
    """Basic syntax validation with detailed feedback."""
    if not email or not isinstance(email, str):
        return {"pass": False, "detail": "Email is empty or not a string", "score": 0}

    email = email.strip()
    if len(email) > 254:
        return {"pass": False, "detail": "Email address too long (>254 characters)", "score": 0}

    # Standard email regex
    pattern = r'^[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        # More specific checks
        if "@" not in email:
            return {"pass": False, "detail": "Missing @ symbol", "score": 0}
        local, _, domain = email.partition("@")
        if not local:
            return {"pass": False, "detail": "No username before @", "score": 0}
        if ".." in email:
            return {"pass": False, "detail": "Contains consecutive dots", "score": 0}
        if " " in email:
            return {"pass": False, "detail": "Contains spaces", "score": 0}
        return {"pass": False, "detail": "Does not match standard email format", "score": 0}

    return {"pass": True, "detail": "Format is valid", "score": 25}


def _check_disposable_role(email: str) -> dict:
    """Check if email domain is disposable or prefix is a generic role."""
    if "@" not in email:
        return {"pass": False, "detail": "Cannot parse domain", "score": 0}

    local, _, domain = email.partition("@")
    domain_lower = domain.lower().strip()
    local_lower = local.lower().strip()

    issues = []

    # Check disposable domains
    if domain_lower in DISPOSABLE_DOMAINS:
        issues.append(f"Disposable email domain: {domain_lower}")
        return {"pass": False, "detail": "; ".join(issues), "score": 0}

    # Check generic role prefixes
    if local_lower in ROLE_PREFIXES:
        issues.append(f"Generic role prefix: {local_lower}@ (not a personal mailbox)")
        # Role emails are not invalid, just low quality
        return {"pass": True, "detail": "; ".join(issues), "score": 10}

    # Check for role-like patterns (e.g. sales-ny, info_eu)
    for prefix in ROLE_PREFIXES:
        if local_lower == prefix or local_lower.startswith(prefix + ".") or local_lower.startswith(prefix + "-") or local_lower.startswith(prefix + "_"):
            issues.append(f"Likely role prefix: {local_lower}@ (starts with '{prefix}')")
            return {"pass": True, "detail": "; ".join(issues), "score": 10}

    if not issues:
        return {"pass": True, "detail": "Not a disposable email / generic role", "score": 25}

    return {"pass": True, "detail": "; ".join(issues), "score": 10}


def _check_mx(domain: str) -> dict:
    """Look up MX records for the domain. Returns highest priority mail server."""
    import dns.resolver

    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_records = []
        for rdata in answers:
            mx_records.append({
                "preference": rdata.preference,
                "exchange": str(rdata.exchange).rstrip("."),
            })
        mx_records.sort(key=lambda x: x["preference"])

        if mx_records:
            return {
                "pass": True,
                "detail": f"MX record: {mx_records[0]['exchange']}",
                "score": 25,
                "mx_records": mx_records,
            }

        # No MX, try A record (RFC 5321 fallback)
        try:
            a_answers = dns.resolver.resolve(domain, "A")
            a_records = [str(r) for r in a_answers]
            if a_records:
                return {
                    "pass": True,
                    "detail": f"No MX record; fell back to A record: {a_records[0]}",
                    "score": 10,
                    "mx_records": [{"preference": 0, "exchange": a_records[0]}],
                }
        except Exception:
            pass

        return {"pass": False, "detail": f"Domain {domain} has no mail server (MX/A)", "score": 0}

    except dns.resolver.NXDOMAIN:
        return {"pass": False, "detail": f"Domain {domain} does not exist", "score": 0}
    except dns.resolver.NoAnswer:
        return {"pass": False, "detail": f"Domain {domain} has no MX record", "score": 0}
    except dns.resolver.Timeout:
        return {"pass": False, "detail": f"DNS query timed out ({domain})", "score": 0}
    except Exception as e:
        logger.warning("MX lookup failed for %s: %s", domain, e)
        return {"pass": False, "detail": f"DNS query failed: {str(e)[:100]}", "score": 0}


def _smtp_handshake(email: str, mx_host: str, timeout: int = 10) -> dict:
    """Connect to mail server and verify RCPT TO without sending.

    Uses a dummy MAIL FROM to test if the server accepts the recipient.
    Does NOT send any actual email. Some servers will reject this probe.
    """
    try:
        # Get local hostname for HELO
        helo = "company.com"

        server = smtplib.SMTP(timeout=timeout)
        server.set_debuglevel(0)
        server.connect(mx_host, 25)

        code, msg = server.helo(helo)
        if code >= 400:
            try:
                server.ehlo(helo)
            except Exception:
                pass

        server.mail("verify@" + helo)

        code, msg = server.rcpt(email)
        server.quit()

        if code == 250:
            return {"pass": True, "detail": f"SMTP verification passed (code={code})", "score": 25}
        elif code == 550:
            return {"pass": False, "detail": f"Email does not exist: {msg.decode() if isinstance(msg, bytes) else msg}", "score": 0}
        elif code == 450 or code == 451:
            return {"pass": None, "detail": f"Server temporarily rejected (graylisting, code={code})", "score": 10}
        else:
            return {"pass": None, "detail": f"Uncertain SMTP response (code={code}): {msg.decode() if isinstance(msg, bytes) else msg}", "score": 10}

    except smtplib.SMTPServerDisconnected:
        return {"pass": None, "detail": "Server disconnected (may block verification probes)", "score": 10}
    except smtplib.SMTPConnectError:
        return {"pass": None, "detail": "Cannot connect to the mail server", "score": 10}
    except socket.timeout:
        return {"pass": None, "detail": f"Connection timed out ({timeout}s)", "score": 10}
    except socket.gaierror:
        return {"pass": None, "detail": "Mail server address could not be resolved", "score": 10}
    except Exception as e:
        msg = str(e)
        if "Connection refused" in msg:
            return {"pass": None, "detail": "Mail server refused the connection (Port 25 blocked)", "score": 10}
        if "timed out" in msg.lower():
            return {"pass": None, "detail": f"Connection timed out ({timeout}s)", "score": 10}
        return {"pass": None, "detail": f"SMTP verification error: {msg[:150]}", "score": 10}


def verify_email(email: str, smtp: bool = False, timeout: int = 10) -> dict:
    """Verify an email address. Returns detailed breakdown.

    Args:
        email: the address to verify
        smtp: whether to do SMTP handshake (slower, optional)
        timeout: SMTP timeout in seconds

    Returns:
        {
            "email": "x@y.com",
            "overall_score": 0-100,
            "verdict": "valid|risky|invalid|unknown",
            "checks": {"syntax": {...}, "role": {...}, "mx": {...}, "smtp": {...}},
            "recommendation": "English recommendation string"
        }
    """
    if not email or not isinstance(email, str):
        return {
            "email": str(email),
            "overall_score": 0,
            "verdict": "invalid",
            "checks": {"syntax": {"pass": False, "detail": "Email is empty"}},
            "recommendation": "Email is empty — cannot verify",
        }

    email = email.strip().lower()
    result = {"email": email, "checks": {}}
    total = 0
    max_possible = 50  # syntax(25) + role(25), mx and smtp add more

    # Layer 1: Syntax
    syntax = _check_syntax(email)
    result["checks"]["syntax"] = syntax
    total += syntax["score"]
    if not syntax["pass"]:
        result["overall_score"] = 0
        result["verdict"] = "invalid"
        result["recommendation"] = f"Email format error: {syntax['detail']}"
        return result

    # Layer 2: Disposable / Role
    role = _check_disposable_role(email)
    result["checks"]["role"] = role
    total += role["score"]
    if role["score"] == 0:
        result["overall_score"] = total
        result["verdict"] = "invalid"
        result["recommendation"] = f"Email not usable: {role['detail']}"
        return result

    # Layer 3: MX record
    max_possible = 75
    try:
        domain = email.split("@")[1]
        mx = _check_mx(domain)
        result["checks"]["mx"] = mx
        total += mx["score"]
    except Exception as e:
        result["checks"]["mx"] = {"pass": False, "detail": f"MX lookup error: {str(e)[:100]}", "score": 0}

    # Layer 4: SMTP (optional)
    if smtp:
        max_possible = 100
        mx_host = None
        if "mx" in result["checks"] and result["checks"]["mx"].get("mx_records"):
            mx_host = result["checks"]["mx"]["mx_records"][0]["exchange"]

        if mx_host:
            smtp_result = _smtp_handshake(email, mx_host, timeout)
            result["checks"]["smtp"] = smtp_result
            total += smtp_result["score"]
        else:
            result["checks"]["smtp"] = {"pass": None, "detail": "No usable mail server — skipped SMTP verification", "score": 0}

    # Final verdict
    result["overall_score"] = min(total, max_possible)

    if result["overall_score"] >= 75:
        result["verdict"] = "valid"
        result["recommendation"] = "Email verified — safe to use for outreach"
    elif result["overall_score"] >= 40:
        result["verdict"] = "risky"
        if role.get("score", 0) <= 10:
            result["recommendation"] = f"Email may be a generic role mailbox ({role.get('detail','')}) — look for a personal address instead"
        elif result["checks"].get("mx", {}).get("score", 25) < 15:
            result["recommendation"] = "Domain mail-server configuration looks abnormal; deliverability may be low"
        else:
            result["recommendation"] = "Email partially verified — medium risk; confirm manually before sending"
    else:
        result["verdict"] = "invalid"
        if "mx" in result["checks"] and not result["checks"]["mx"]["pass"]:
            result["recommendation"] = f"Email domain invalid: {result['checks']['mx']['detail']}"
        else:
            result["recommendation"] = "Email verification failed — try another address or source"

    return result


def verify_email_batch(emails: list[str], smtp: bool = False) -> list[dict]:
    """Verify multiple emails. Returns list of results in same order."""
    results = []
    for email in emails:
        try:
            result = verify_email(email, smtp=smtp)
            results.append(result)
        except Exception as e:
            results.append({
                "email": email,
                "overall_score": 0,
                "verdict": "error",
                "recommendation": f"验证异常: {str(e)[:200]}",
            })
    return results

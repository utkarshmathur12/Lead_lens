"""Parsing + validation helpers. Pure functions, no I/O."""
import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
GENERIC_LOCALS = {"info", "contact", "sales", "support", "hello", "admin", "office", "mail", "enquiries", "inquiries", "service", "team"}
DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "yopmail.com"}

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
STATE_CODES = set(US_STATES.values())


def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in {"n/a", "na", "none", "null", "-", "nan"} else None


def normalize_email(v):
    s = clean(v)
    return s.lower().replace("mailto:", "").strip() if s else None


def is_valid_email(e):
    if not e or not EMAIL_RE.match(e):
        return False
    return e.split("@")[1] not in DISPOSABLE


def is_generic_email(e):
    return bool(e) and e.split("@")[0] in GENERIC_LOCALS


def normalize_phone(v):
    s = clean(v)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def normalize_domain(v):
    s = clean(v)
    if not s:
        return None
    if "@" in s and "/" not in s:  # an email slipped into the website column
        s = s.split("@")[1]
    if "://" not in s:
        s = "http://" + s
    host = (urlparse(s).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host if "." in host else None


def normalize_state(v):
    s = clean(v)
    if not s:
        return None
    if s.upper() in STATE_CODES:
        return s.upper()
    return US_STATES.get(s.lower())


def parse_int(v):
    s = clean(v)
    if not s:
        return None
    m = re.findall(r"\d+", s.replace(",", ""))
    if not m:
        return None
    nums = [int(x) for x in m[:2]]
    return sum(nums) // len(nums)  # "11-50" -> 30 (midpoint)


def parse_float(v):
    s = clean(v)
    if not s:
        return None
    m = re.search(r"\d+(\.\d+)?", s.replace(",", ""))
    return float(m.group()) if m else None


def parse_money(v):
    """'$2.5M', '2,500,000', '$1M-$3M', '800k', '1-3M' -> number (midpoint for ranges)."""
    s = clean(v)
    if not s:
        return None
    s = s.lower().replace(",", "").replace("$", "")
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(b|m|k)?", s)
    if not parts:
        return None
    unit_of_last = parts[-1][1]
    vals = []
    for num, suffix in parts[:2]:
        suffix = suffix or unit_of_last  # "1-3M" -> both millions
        mult = {"b": 1e9, "m": 1e6, "k": 1e3, "": 1}[suffix]
        vals.append(float(num) * mult)
    return sum(vals) / len(vals)


def parse_year(v):
    s = clean(v)
    if not s:
        return None
    m = re.search(r"(18|19|20)\d{2}", s)
    return int(m.group()) if m else None

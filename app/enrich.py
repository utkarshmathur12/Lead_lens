"""Opt-in website enrichment with guardrails.

Ethics + safety: honours robots.txt, identifies itself, fetches at most the homepage and
one contact page, never follows redirects to private networks (SSRF protection), and only
extracts business contact info that the company itself publishes.
"""
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

UA = "LeadLensBot/1.0 (+business research; respects robots.txt)"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
SINCE_RE = re.compile(r"(?:since|established|est\.?|founded(?: in)?)\s*((?:18|19|20)\d{2})", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
META_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.I | re.S)
MAX_BYTES = 500_000


class BlockedURL(Exception):
    pass


def assert_public(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BlockedURL("Only http(s) URLs are allowed")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror as e:
        raise BlockedURL(f"DNS lookup failed: {e}")
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise BlockedURL("Refusing to fetch a non-public address")


def safe_get(url, client, max_redirects=3):
    for _ in range(max_redirects + 1):
        assert_public(url)
        r = client.get(url, follow_redirects=False)
        if r.is_redirect and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        return r
    raise BlockedURL("Too many redirects")


def allowed_by_robots(base, client):
    rp = RobotFileParser()
    try:
        r = safe_get(urljoin(base, "/robots.txt"), client)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except Exception:
        return True  # no usable robots.txt -> default allow
    return rp.can_fetch(UA, base)


def parse_page(html):
    junk = {"png", "jpg", "jpeg", "gif", "svg", "webp"}
    emails = sorted({e.lower() for e in EMAIL_RE.findall(html) if e.rsplit(".", 1)[-1].lower() not in junk})
    phones = sorted({re.sub(r"\D", "", p)[-10:] for p in PHONE_RE.findall(html)})
    title = TITLE_RE.search(html)
    meta = META_RE.search(html)
    since = SINCE_RE.search(html)
    return {
        "emails": emails[:5], "phones": phones[:3],
        "title": re.sub(r"\s+", " ", title.group(1)).strip()[:160] if title else None,
        "meta_description": re.sub(r"\s+", " ", meta.group(1)).strip()[:300] if meta else None,
        "since": int(since.group(1)) if since else None,
        "family_owned": bool(re.search(r"family[\s\-]owned|owner[\s\-]operated|locally owned", html, re.I)),
    }


def enrich_website(domain, client=None):
    own = client is None
    client = client or httpx.Client(timeout=8, headers={"User-Agent": UA}, max_redirects=0)
    base = f"https://{domain}/"
    out = {"domain": domain, "status": "ok", "pages": []}
    try:
        if not allowed_by_robots(base, client):
            return {**out, "status": "blocked_by_robots"}
        merged = {"emails": set(), "phones": set()}
        for path in ("", "contact", "contact-us", "about"):
            try:
                r = safe_get(urljoin(base, path), client)
            except (BlockedURL, httpx.HTTPError):
                if path == "":
                    return {**out, "status": "unreachable"}
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
                continue
            info = parse_page(r.text[:MAX_BYTES])
            out["pages"].append(urljoin(base, path))
            merged["emails"] |= set(info["emails"])
            merged["phones"] |= set(info["phones"])
            for k in ("title", "meta_description", "since", "family_owned"):
                if info[k] and not out.get(k):
                    out[k] = info[k]
            if len(out["pages"]) >= 2:
                break
        out["emails"], out["phones"] = sorted(merged["emails"]), sorted(merged["phones"])
        return out
    finally:
        if own:
            client.close()

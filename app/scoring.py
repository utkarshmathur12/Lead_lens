"""Explainable ICP-fit scoring for acquisition-style (search fund / ETA) lead lists.

Every point is traceable: score_lead() returns a per-category breakdown with human-readable
notes, so a user can see *why* a lead ranks where it does. That is the core product idea:
rank by likelihood of being a good, reachable, owner-led acquisition target, not by volume.
"""
import copy
import datetime

DEFAULT_ICP = {
    "industries": ["hvac", "plumbing", "landscaping", "roofing", "electrical", "pest control", "cleaning",
                   "auto repair", "dental", "veterinary", "accounting", "insurance agency", "logistics",
                   "manufacturing", "laundry"],
    "min_employees": 5, "max_employees": 100,
    "min_revenue": 1_000_000, "max_revenue": 20_000_000,
    "target_states": [],            # empty list = any state
    "min_years_in_business": 15,    # long-tenured owners are likelier to be thinking about succession
    "min_rating": 4.0, "min_reviews": 15,
    "exclude_keywords": ["franchise", "franchisee", "publicly traded", "nasdaq", "nyse", "subsidiary of", "a division of"],
    "weights": {"industry": 25, "size": 20, "succession": 20, "geography": 10, "reachability": 15, "reputation": 10},
}
TIERS = [(85, "A"), (70, "B"), (50, "C"), (0, "D")]
CONF_FIELDS = ["industry", "employees", "revenue", "state", "email", "phone", "website", "owner_name",
               "year_founded", "rating"]
SUCCESSION_WORDS = ["family owned", "family-owned", "family business", "owner-operated", "owner operated",
                    "founded by", "locally owned", "third generation", "second generation", "since 19"]


def merged_icp(custom=None):
    icp = copy.deepcopy(DEFAULT_ICP)
    for k, v in (custom or {}).items():
        if k == "weights" and isinstance(v, dict):
            icp["weights"].update(v)
        elif k in icp:
            icp[k] = v
    return icp


def _range_fit(v, lo, hi):
    if v is None:
        return None
    if lo <= v <= hi:
        return 1.0
    if v < lo:
        return 0.5 if v >= lo * 0.5 else 0.0
    return 0.5 if v <= hi * 1.5 else 0.0


def _tier(score):
    return next(t for cut, t in TIERS if score >= cut)


def score_lead(lead, icp=None, now_year=None):
    icp = icp or DEFAULT_ICP
    now_year = now_year or datetime.date.today().year
    w = icp["weights"]
    text = " ".join(str(lead.get(k) or "") for k in ("company", "industry", "description")).lower()
    bd = {}

    def put(cat, frac, notes):
        pts = round(max(0.0, min(1.0, frac)) * w[cat], 1)
        bd[cat] = {"points": pts, "max": w[cat], "notes": notes}

    # industry fit
    ind = (lead.get("industry") or "").lower()
    targets = [t.lower() for t in icp["industries"]]
    if ind and any(t in ind or ind in t for t in targets):
        put("industry", 1.0, [f"Industry '{lead['industry']}' is a target"])
    elif any(t in text for t in targets):
        hit = next(t for t in targets if t in text)
        put("industry", 0.6, [f"Mentions target industry '{hit}'"])
    elif not ind:
        put("industry", 0.2, ["Industry unknown"])
    else:
        put("industry", 0.0, [f"Industry '{lead['industry']}' not in ICP"])

    # size fit (employees + revenue)
    parts, notes = [], []
    e = _range_fit(lead.get("employees"), icp["min_employees"], icp["max_employees"])
    r = _range_fit(lead.get("revenue"), icp["min_revenue"], icp["max_revenue"])
    for label, f, val in (("employees", e, lead.get("employees")), ("revenue", r, lead.get("revenue"))):
        if f is None:
            notes.append(f"{label.capitalize()} unknown")
        else:
            parts.append(f)
            notes.append(f"{label.capitalize()} {'in' if f == 1 else 'near/outside'} target range ({val:,.0f})")
    put("size", sum(parts) / len(parts) if parts else 0.4, notes)

    # succession / owner-led signals
    s, notes = 0.0, []
    if lead.get("owner_name"):
        s += 0.35
        notes.append(f"Owner identified ({lead['owner_name']})")
    yr = lead.get("year_founded")
    if yr:
        age = now_year - yr
        if age >= icp["min_years_in_business"]:
            s += 0.4
            notes.append(f"{age} years in business (long-tenured owner)")
        else:
            s += 0.4 * max(0, age) / icp["min_years_in_business"] * 0.5
            notes.append(f"Only {age} years in business")
    if any(k in text for k in SUCCESSION_WORDS):
        s += 0.25
        notes.append("Owner-operated / family language in description")
    put("succession", s, notes or ["No ownership signals"])

    # geography
    st = icp["target_states"]
    if not st:
        put("geography", 1.0, ["No geographic restriction"])
    elif lead.get("state") in st:
        put("geography", 1.0, [f"In target state {lead['state']}"])
    else:
        put("geography", 0.0, [f"{lead.get('state') or 'Unknown state'} outside target states"])

    # reachability
    reach, notes = 0.0, []
    if lead.get("email_valid"):
        generic = lead.get("email_generic")
        reach += 0.25 if generic else 0.4
        notes.append("Generic mailbox (info@/sales@)" if generic else "Direct email present")
    elif lead.get("email"):
        notes.append("Email looks invalid")
    if lead.get("phone"):
        reach += 0.2
        notes.append("Valid phone")
    if lead.get("domain"):
        reach += 0.2
        notes.append("Website known")
    if lead.get("owner_name"):
        reach += 0.2
    put("reachability", reach, notes or ["No contact data"])

    # reputation / stability
    rt, rv = lead.get("rating"), lead.get("review_count")
    if rt is None:
        put("reputation", 0.3, ["No rating data"])
    elif rt >= icp["min_rating"] and (rv or 0) >= icp["min_reviews"]:
        put("reputation", 1.0, [f"{rt}★ across {rv} reviews"])
    elif rt >= icp["min_rating"]:
        put("reputation", 0.5, [f"{rt}★ but few reviews ({rv or 0})"])
    else:
        put("reputation", 0.2, [f"Low rating ({rt}★)"])

    total = sum(b["points"] for b in bd.values()) / (sum(w.values()) or 1) * 100
    flags = []
    hit = next((k for k in icp["exclude_keywords"] if k in text), None)
    if hit:
        total *= 0.5
        flags.append(f"Excluded signal: '{hit}'")
    if lead.get("email") and not lead.get("email_valid"):
        flags.append("Invalid email")
    if lead.get("email_generic"):
        flags.append("Generic email only")
    total = round(total, 1)
    conf = round(sum(1 for f in CONF_FIELDS if lead.get(f) not in (None, "")) / len(CONF_FIELDS), 2)
    return {"score": total, "tier": _tier(total), "confidence": conf, "breakdown": bd, "flags": flags}

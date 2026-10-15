import csv
import io
import json
import re
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, enrich, outreach, validate as v
from .dedupe import dedupe, normalize_name
from .scoring import DEFAULT_ICP, merged_icp, score_lead

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
STATUSES = {"new", "contacted", "qualified", "rejected"}
SORTS = {"score": "score", "company": "company", "revenue": "revenue", "employees": "employees", "confidence": "confidence"}
FIELDS = ["company", "website", "domain", "industry", "city", "state", "employees", "revenue", "phone",
          "email", "owner_name", "year_founded", "rating", "review_count", "description"]

ALIASES = {
    "company": ["company", "companyname", "name", "businessname", "organization", "account"],
    "website": ["website", "url", "domain", "site", "companywebsite", "websiteurl"],
    "industry": ["industry", "category", "sector", "type"],
    "city": ["city", "town"],
    "state": ["state", "region", "stateprovince", "st"],
    "employees": ["employees", "employeecount", "numberofemployees", "headcount", "size", "employeesrange"],
    "revenue": ["revenue", "annualrevenue", "estimatedrevenue", "revenueestimate", "estrevenue"],
    "phone": ["phone", "phonenumber", "telephone", "tel"],
    "email": ["email", "emailaddress", "contactemail"],
    "owner_name": ["owner", "ownername", "contact", "contactname", "ceo", "founder", "decisionmaker"],
    "year_founded": ["yearfounded", "founded", "foundedyear", "established", "since"],
    "rating": ["rating", "stars", "googlerating"],
    "review_count": ["reviews", "reviewcount", "numreviews", "ratingscount"],
    "description": ["description", "about", "summary", "notes", "shortdescription"],
}

app = FastAPI(title="LeadLens", version="1.0.0")
db.init()
_cache, _lock = {}, threading.Lock()


def _invalidate():
    with _lock:
        _cache.clear()


# ---------- helpers ----------
def normalize_row(raw):
    keymap = {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in raw if k}
    pick = {}
    for field, names in ALIASES.items():
        for n in names:
            if n in keymap:
                pick[field] = raw[keymap[n]]
                break
    company = v.clean(pick.get("company"))
    if not company:
        return None
    website = v.clean(pick.get("website"))
    domain = v.normalize_domain(website)
    return {
        "company": company, "name_norm": normalize_name(company), "website": website, "domain": domain,
        "industry": v.clean(pick.get("industry")), "city": v.clean(pick.get("city")),
        "state": v.normalize_state(pick.get("state")), "employees": v.parse_int(pick.get("employees")),
        "revenue": v.parse_money(pick.get("revenue")), "phone": v.normalize_phone(pick.get("phone")),
        "email": v.normalize_email(pick.get("email")), "owner_name": v.clean(pick.get("owner_name")),
        "year_founded": v.parse_year(pick.get("year_founded")), "rating": v.parse_float(pick.get("rating")),
        "review_count": v.parse_int(pick.get("review_count")), "description": v.clean(pick.get("description")),
    }


def with_flags(lead):
    d = dict(lead)
    d["email_valid"] = v.is_valid_email(d.get("email"))
    d["email_generic"] = d["email_valid"] and v.is_generic_email(d["email"])
    return d


def score_values(lead, icp):
    r = score_lead(with_flags(lead), icp)
    return (r["score"], r["tier"], r["confidence"], json.dumps(r["breakdown"]), json.dumps(r["flags"]))


def row_to_dict(row):
    d = dict(row)
    d["breakdown"] = json.loads(d.get("breakdown") or "{}")
    d["flags"] = json.loads(d.get("flags") or "[]")
    d["enrichment"] = json.loads(d["enrichment"]) if d.get("enrichment") else None
    d.pop("name_norm", None)
    return d


def current_icp(conn):
    return merged_icp(db.get_setting(conn, "icp", {}))


def ingest(conn, rows):
    """Normalize -> dedupe within file -> merge into existing -> score -> persist."""
    parsed = [r for r in (normalize_row(x) for x in rows) if r]
    unique, dups_in_file = dedupe(parsed)
    icp = current_icp(conn)
    added = merged = 0
    for rec in unique:
        existing = None
        if rec.get("domain"):
            existing = conn.execute("SELECT * FROM leads WHERE domain=?", (rec["domain"],)).fetchone()
        if not existing:
            existing = conn.execute("SELECT * FROM leads WHERE name_norm=? AND IFNULL(state,'')=IFNULL(?,'')",
                                    (rec["name_norm"], rec.get("state"))).fetchone()
        if existing:
            cur = dict(existing)
            for f in FIELDS:
                if cur.get(f) in (None, "") and rec.get(f) not in (None, ""):
                    cur[f] = rec[f]
            sets = ", ".join(f"{f}=?" for f in FIELDS) + ", score=?, tier=?, confidence=?, breakdown=?, flags=?"
            conn.execute(f"UPDATE leads SET {sets} WHERE id=?",
                         [cur[f] for f in FIELDS] + list(score_values(cur, icp)) + [existing["id"]])
            merged += 1
        else:
            cols = ["company", "name_norm"] + FIELDS[1:] + ["score", "tier", "confidence", "breakdown", "flags"]
            vals = [rec["company"], rec["name_norm"]] + [rec.get(f) for f in FIELDS[1:]] + list(score_values(rec, icp))
            conn.execute(f"INSERT INTO leads({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
            added += 1
    conn.commit()
    _invalidate()
    return {"rows_read": len(rows), "invalid_rows": len(rows) - len(parsed), "duplicates_removed_in_file": dups_in_file,
            "merged_into_existing": merged, "new_leads": added}


def rescore_all(conn):
    icp = current_icp(conn)
    for row in conn.execute("SELECT * FROM leads").fetchall():
        conn.execute("UPDATE leads SET score=?, tier=?, confidence=?, breakdown=?, flags=? WHERE id=?",
                     list(score_values(dict(row), icp)) + [row["id"]])
    conn.commit()
    _invalidate()


def build_filters(q, tier, min_score, state, industry, status, has_email):
    where, args = [], []
    if q:
        where.append("(company LIKE ? OR owner_name LIKE ? OR city LIKE ? OR industry LIKE ?)")
        args += [f"%{q}%"] * 4
    if tier:
        tiers = [t for t in tier.upper().split(",") if t in "ABCD" and t]
        if tiers:
            where.append(f"tier IN ({','.join('?' * len(tiers))})")
            args += tiers
    if min_score:
        where.append("score >= ?")
        args.append(min_score)
    if state:
        where.append("state = ?")
        args.append(state.upper())
    if industry:
        where.append("industry LIKE ?")
        args.append(f"%{industry}%")
    if status:
        where.append("status = ?")
        args.append(status)
    if has_email:
        where.append("email IS NOT NULL AND email != ''")
    return (" WHERE " + " AND ".join(where)) if where else "", args


# ---------- API ----------
@app.post("/api/import")
async def import_csv(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 10_000_000:
        raise HTTPException(413, "File too large (10 MB max)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise HTTPException(400, "CSV has no data rows")
    with db.connect() as conn:
        return ingest(conn, rows)


@app.post("/api/sample")
def load_sample():
    path = ROOT / "data" / "sample_leads.csv"
    if not path.exists():
        raise HTTPException(404, "Run scripts/generate_sample_data.py first")
    with db.connect() as conn, open(path, newline="", encoding="utf-8") as f:
        return ingest(conn, list(csv.DictReader(f)))


@app.get("/api/leads")
def list_leads(q: str = "", tier: str = "", min_score: float = 0, state: str = "", industry: str = "",
               status: str = "", has_email: bool = False, sort: str = "score", dir: str = "desc",
               limit: int = Query(50, le=500), offset: int = 0):
    where, args = build_filters(q, tier, min_score, state, industry, status, has_email)
    order = f"{SORTS.get(sort, 'score')} {'ASC' if dir == 'asc' else 'DESC'}, id ASC"
    with db.connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM leads{where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM leads{where} ORDER BY {order} LIMIT ? OFFSET ?",
                            args + [limit, offset]).fetchall()
    return {"total": total, "items": [row_to_dict(r) for r in rows]}


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Lead not found")
    return row_to_dict(row)


class StatusIn(BaseModel):
    status: str


@app.post("/api/leads/{lead_id}/status")
def set_status(lead_id: int, body: StatusIn):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(STATUSES)}")
    with db.connect() as conn:
        cur = conn.execute("UPDATE leads SET status=? WHERE id=?", (body.status, lead_id))
        conn.commit()
    if not cur.rowcount:
        raise HTTPException(404, "Lead not found")
    _invalidate()
    return {"ok": True}


@app.post("/api/leads/{lead_id}/enrich")
def enrich_lead(lead_id: int):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Lead not found")
        lead = dict(row)
        if not lead["domain"]:
            raise HTTPException(400, "Lead has no website to enrich from")
        result = enrich.enrich_website(lead["domain"])
        if result["status"] == "ok":
            emails = [e for e in result.get("emails", []) if v.is_valid_email(e)]
            emails.sort(key=lambda e: (not e.endswith("@" + lead["domain"]), v.is_generic_email(e)))
            if not lead["email"] and emails:
                lead["email"] = emails[0]
            if not lead["phone"] and result.get("phones"):
                lead["phone"] = v.normalize_phone(result["phones"][0])
            if not lead["year_founded"] and result.get("since"):
                lead["year_founded"] = result["since"]
            if result.get("family_owned") and "owner-operated" not in (lead["description"] or ""):
                lead["description"] = ((lead["description"] or "") + " Owner-operated (per website).").strip()
        conn.execute(
            "UPDATE leads SET email=?, phone=?, year_founded=?, description=?, enrichment=?, "
            "score=?, tier=?, confidence=?, breakdown=?, flags=? WHERE id=?",
            [lead["email"], lead["phone"], lead["year_founded"], lead["description"], json.dumps(result)]
            + list(score_values(lead, current_icp(conn))) + [lead_id])
        conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    _invalidate()
    return row_to_dict(row)


@app.post("/api/leads/{lead_id}/outreach")
def make_outreach(lead_id: int):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Lead not found")
    return outreach.draft(dict(row))


@app.get("/api/export.csv")
def export_csv(q: str = "", tier: str = "", min_score: float = 0, state: str = "", industry: str = "",
               status: str = "", has_email: bool = False):
    where, args = build_filters(q, tier, min_score, state, industry, status, has_email)
    with db.connect() as conn:
        rows = conn.execute(f"SELECT * FROM leads{where} ORDER BY score DESC, id ASC", args).fetchall()
    buf = io.StringIO()
    cols = ["company", "score", "tier", "confidence", "status", "owner_name", "email", "phone", "website",
            "industry", "city", "state", "employees", "revenue", "year_founded", "rating", "review_count",
            "why", "flags"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        d = row_to_dict(r)
        d["why"] = "; ".join(n for b in d["breakdown"].values() for n in b["notes"][:1])
        d["flags"] = "; ".join(d["flags"])
        w.writerow({c: d.get(c) for c in cols})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=leadlens_export.csv"})


@app.get("/api/icp")
def get_icp():
    with db.connect() as conn:
        return {"icp": current_icp(conn), "defaults": DEFAULT_ICP}


@app.put("/api/icp")
def put_icp(icp: dict):
    unknown = set(icp) - set(DEFAULT_ICP)
    if unknown:
        raise HTTPException(400, f"Unknown ICP keys: {sorted(unknown)}")
    with db.connect() as conn:
        db.set_setting(conn, "icp", icp)
        conn.commit()
        rescore_all(conn)
        return {"icp": current_icp(conn)}


@app.get("/api/stats")
def stats():
    with _lock:
        if "stats" in _cache:
            return _cache["stats"]
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        tiers = {r[0]: r[1] for r in conn.execute("SELECT tier, COUNT(*) FROM leads GROUP BY tier")}
        statuses = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM leads GROUP BY status")}
        avg = conn.execute("SELECT ROUND(AVG(score),1) FROM leads").fetchone()[0] or 0
        with_email = conn.execute("SELECT COUNT(*) FROM leads WHERE email IS NOT NULL AND email != ''").fetchone()[0]
        states = [r[0] for r in conn.execute("SELECT DISTINCT state FROM leads WHERE state IS NOT NULL ORDER BY state")]
    out = {"total": total, "tiers": tiers, "statuses": statuses, "avg_score": avg, "with_email": with_email,
           "states": states}
    with _lock:
        _cache["stats"] = out
    return out


@app.delete("/api/leads")
def clear_all():
    with db.connect() as conn:
        conn.execute("DELETE FROM leads")
        conn.commit()
    _invalidate()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

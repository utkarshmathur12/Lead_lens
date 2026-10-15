import os
import tempfile

os.environ["LEADLENS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest
from fastapi.testclient import TestClient

from app import enrich, validate as v
from app.dedupe import dedupe, normalize_name
from app.main import app
from app.scoring import merged_icp, score_lead

client = TestClient(app)


def test_parsers():
    assert v.parse_money("$2.5M") == 2_500_000
    assert v.parse_money("1-3M") == 2_000_000
    assert v.parse_money("800k") == 800_000
    assert v.parse_money("$1,400,000") == 1_400_000
    assert v.parse_int("11-50") == 30
    assert v.normalize_phone("+1 512 555 0147") == "(512) 555-0147"
    assert v.normalize_phone("12345") is None
    assert v.normalize_state("Texas") == "TX" and v.normalize_state("tx") == "TX"
    assert v.normalize_domain("https://www.Acme.com/about") == "acme.com"
    assert v.is_valid_email("a@b.com") and not v.is_valid_email("ab.com")
    assert v.is_generic_email("info@x.com") and not v.is_generic_email("tom@x.com")


def test_dedupe_merges_variants():
    recs = [
        {"company": "Miller Air LLC", "name_norm": normalize_name("Miller Air LLC"), "domain": "milleair.com", "state": "TX", "email": None, "phone": "(1)"},
        {"company": "Miller Air, Inc", "name_norm": normalize_name("Miller Air, Inc"), "domain": None, "state": "TX", "email": "a@b.com"},
        {"company": "Other Co", "name_norm": normalize_name("Other Co"), "domain": "other.com", "state": "TX"},
    ]
    out, removed = dedupe(recs)
    assert removed == 1 and len(out) == 2
    merged = next(r for r in out if "miller" in r["name_norm"])
    assert merged["email"] == "a@b.com" and merged["phone"] == "(1)"  # gaps back-filled


def test_numbered_locations_not_merged():
    recs = [{"company": f"Acme Plumbing {n}", "name_norm": normalize_name(f"Acme Plumbing {n}"), "domain": None, "state": "TX"}
            for n in (1, 2)]
    assert dedupe(recs)[1] == 0


def good_lead(**kw):
    base = dict(company="Ace HVAC", industry="HVAC", employees=25, revenue=4e6, state="TX", owner_name="Tom Ace",
                year_founded=1990, rating=4.8, review_count=120, email="tom@ace.com", email_valid=True,
                email_generic=False, phone="(512) 555-0147", domain="ace.com", description="Family owned HVAC.")
    base.update(kw)
    return base


def test_scoring_ranks_and_explains():
    good = score_lead(good_lead(), now_year=2026)
    bad = score_lead(good_lead(industry="Software", employees=2, revenue=1e5, owner_name=None, year_founded=2022,
                               rating=2.9, email=None, email_valid=False, phone=None, domain=None,
                               description="Startup"), now_year=2026)
    assert good["tier"] == "A" and good["score"] > 85
    assert bad["tier"] == "D" and bad["score"] < good["score"] - 50
    assert all(b["notes"] for b in good["breakdown"].values())  # explainable


def test_franchise_penalty_and_geography():
    f = score_lead(good_lead(description="Proud franchisee of a national brand"), now_year=2026)
    assert f["score"] < 55 and any("franchise" in x for x in f["flags"])
    icp = merged_icp({"target_states": ["OH"]})
    assert score_lead(good_lead(), icp, 2026)["breakdown"]["geography"]["points"] == 0


def test_end_to_end_api():
    r = client.post("/api/sample")
    assert r.status_code == 200
    s = r.json()
    assert s["duplicates_removed_in_file"] >= 30 and s["new_leads"] > 200
    # re-import is idempotent: everything merges into existing rows
    again = client.post("/api/sample").json()
    assert again["new_leads"] == 0
    top = client.get("/api/leads?limit=5").json()
    scores = [x["score"] for x in top["items"]]
    assert scores == sorted(scores, reverse=True) and top["total"] > 200
    assert client.get("/api/leads?tier=A&has_email=true").json()["total"] >= 0
    lid = top["items"][0]["id"]
    assert client.post(f"/api/leads/{lid}/status", json={"status": "contacted"}).status_code == 200
    assert client.post(f"/api/leads/{lid}/status", json={"status": "bogus"}).status_code == 400
    o = client.post(f"/api/leads/{lid}/outreach").json()
    assert top["items"][0]["company"] in o["email"]
    csv_text = client.get("/api/export.csv?min_score=60").text
    assert csv_text.splitlines()[0].startswith("company,score,tier")
    # changing the ICP re-scores everything
    before = client.get("/api/stats").json()["avg_score"]
    client.put("/api/icp", json={"target_states": ["TX"]})
    after = client.get("/api/stats").json()["avg_score"]
    assert after < before
    assert client.put("/api/icp", json={"nonsense": 1}).status_code == 400


def test_enrichment_blocks_private_hosts():
    for url in ("http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(enrich.BlockedURL):
            enrich.assert_public(url)
    with pytest.raises(enrich.BlockedURL):
        enrich.assert_public("file:///etc/passwd")


def test_parse_page():
    html = ('<title> Ace  HVAC </title><meta name="description" content="Heating since 1988">'
            "Call (512) 555-0147 or mail tom@ace.com. Family-owned since 1988. logo@2x.png")
    p = enrich.parse_page(html)
    assert p["emails"] == ["tom@ace.com"] and p["since"] == 1988 and p["family_owned"]
    assert p["title"] == "Ace HVAC" and p["phones"] == ["5125550147"]

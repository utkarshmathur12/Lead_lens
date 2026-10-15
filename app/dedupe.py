"""Duplicate detection with blocking, so it stays near-linear on large imports.

Leads that share a website domain, or the same normalized name + state, are duplicates.
Remaining candidates are compared fuzzily, but only inside a block (same state + same
first name token), which avoids the O(n^2) all-pairs comparison.
"""
import re
from collections import defaultdict
from difflib import SequenceMatcher

SUFFIXES = {"llc", "inc", "incorporated", "co", "corp", "corporation", "company", "ltd", "lp", "llp", "pllc", "the"}


def normalize_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and "))
    return " ".join(t for t in s.split() if t not in SUFFIXES)


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


FIELDS = ["website", "domain", "industry", "city", "state", "employees", "revenue", "phone", "email",
          "owner_name", "year_founded", "rating", "review_count", "description"]


def _filled(rec):
    return sum(1 for f in FIELDS if rec.get(f) not in (None, ""))


def merge(records):
    """Keep the most complete record and back-fill its gaps from the others."""
    records = sorted(records, key=_filled, reverse=True)
    base = dict(records[0])
    for other in records[1:]:
        for f in FIELDS:
            if base.get(f) in (None, "") and other.get(f) not in (None, ""):
                base[f] = other[f]
    return base


def dedupe(records, fuzzy_threshold=0.9):
    """records: dicts with company, name_norm, domain, state. Returns (unique, removed_count)."""
    n = len(records)
    uf = _UF(n)
    by_domain, by_name_state, blocks = {}, {}, defaultdict(list)
    for i, r in enumerate(records):
        d = r.get("domain")
        if d:
            if d in by_domain:
                uf.union(i, by_domain[d])
            else:
                by_domain[d] = i
        if r["name_norm"]:
            key = (r["name_norm"], r.get("state"))
            if key in by_name_state:
                uf.union(i, by_name_state[key])
            else:
                by_name_state[key] = i
            blocks[(r["name_norm"].split()[0], r.get("state"))].append(i)
    for idxs in blocks.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if uf.find(i) == uf.find(j):
                    continue
                a_name, b_name = records[i]["name_norm"], records[j]["name_norm"]
                # "Acme Plumbing 1" vs "Acme Plumbing 2" are different locations, never fuzzy-merge them
                if re.findall(r"\d+", a_name) != re.findall(r"\d+", b_name):
                    continue
                if SequenceMatcher(None, a_name, b_name).ratio() >= fuzzy_threshold:
                    uf.union(i, j)
    groups = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(records[i])
    unique = [merge(g) if len(g) > 1 else g[0] for g in groups.values()]
    return unique, n - len(unique)

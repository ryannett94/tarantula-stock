"""Species info and photo gallery for each species card -> docs/species.json

Source: iNaturalist (api.inaturalist.org).
  - The species' current name, family and subfamily (iNaturalist's taxonomy).
  - Openly licensed photos only (CC0 / CC BY variants), each with its photographer credit:
    the taxon's curated photos first, then research-grade wild observations.
  - Where it has been recorded in the wild (countries of research-grade, non-captive records).
  - A short summary from Wikipedia (as served by iNaturalist), with the link.

Hobby forms with no formal name ("Genus sp. Locality") get the genus record, clearly
marked as genus-level, so the page never pretends a genus photo is that exact form.

Results are cached: a species is only looked up again after REFRESH_DAYS, and each run
looks up at most MAX_LOOKUPS new species so a scheduled check stays quick.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STOCK = ROOT / "docs" / "stock.json"
OUT = ROOT / "docs" / "species.json"
API = "https://api.inaturalist.org/v1"
UA = {"User-Agent": "tarantula-stock (github.com/ryannett94/tarantula-stock)"}
REFRESH_DAYS = 60
MAX_LOOKUPS = int(os.environ.get("MAX_LOOKUPS", "40"))
OPEN = {"cc0", "cc-by", "cc-by-nc", "cc-by-sa", "cc-by-nc-sa", "cc-by-nd", "cc-by-nc-nd"}
GENERIC = {"sp.", "sp", "cf.", "aff."}

_last = [0.0]


def get(path: str, **params) -> dict:
    """iNaturalist asks for about one request a second."""
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        _last[0] = time.time()
        try:
            r = requests.get(API + path, params=params, headers=UA, timeout=40)
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    return {}


def get2(path: str, **params) -> dict:
    """iNaturalist API v2 (lets us ask for only the fields we need)."""
    global API
    v1, API = API, API.replace("/v1", "/v2")
    try:
        return get(path, **params)
    finally:
        API = v1


ARANEAE = 47118  # iNaturalist's id for spiders: rules out a cactus or wasp with the same genus name
# Names iNaturalist files differently from the World Spider Catalog
LOOKUP_AS = {}


def find_taxon(name: str, rank: str) -> dict | None:
    """Exact match on the name, or on a synonym iNaturalist knows (matched_term).
    For a genus iNaturalist doesn't keep (e.g. Cyriopagopus), take the group it files it under."""
    res = get("/taxa", q=name, per_page=20, is_active="true").get("results", [])
    ranks = ("genus", "subgenus", "tribe", "subfamily", "family") if rank == "genus" else ("species", "subspecies")
    best = None
    for t in res:
        if t.get("rank") not in ranks or ARANEAE not in (t.get("ancestor_ids") or []):
            continue
        if name in (t["name"].lower(), (t.get("matched_term") or "").lower()):
            if t["rank"] in ("genus", "species"):
                return t
            best = best or t
    return best


def photo(p: dict, source: str) -> dict | None:
    if (p.get("license_code") or "").lower() not in OPEN or not p.get("url"):
        return None
    url = p["url"]
    return {"src": re.sub(r"/(square|small|thumb)\.", "/medium.", url),
            "big": re.sub(r"/(square|small|thumb|medium)\.", "/large.", url),
            "credit": p.get("attribution") or "", "license": p["license_code"].upper(), "from": source}


COUNTRY: dict[int, str | None] = {}


def load_places(ids: set[int]) -> None:
    unknown = sorted(i for i in ids if i not in COUNTRY)
    for n in range(0, len(unknown), 100):
        batch = unknown[n:n + 100]
        for pl in get2("/places/" + ",".join(map(str, batch)), fields="id,name,display_name,admin_level").get("results", []):
            COUNTRY[pl["id"]] = pl.get("display_name") or pl.get("name") if pl.get("admin_level") == 0 else None
        for i in batch:
            COUNTRY.setdefault(i, None)


def countries(ids: list[int]) -> list[str]:
    """Country names among an observation's places (iNaturalist admin level 0)."""
    return [COUNTRY[i] for i in ids if COUNTRY.get(i)]


def clean_summary(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()
    if len(s) < 30:  # iNaturalist sometimes has just "..."
        return ""
    if len(s) > 650:  # cut at a sentence end
        cut = s[:650].rfind(". ")
        s = s[:cut + 1] if cut > 200 else s[:650] + "…"
    return s


def lookup(key: str) -> dict:
    words = key.split()
    genus = words[0]
    formal = len(words) >= 2 and words[1] not in GENERIC and not words[1].startswith("sp")
    info: dict = {"fetched": date.today().isoformat(), "level": None}
    t = None
    if formal:
        if len(words) >= 3:
            t = find_taxon(" ".join(words[:3]), "species")
        t = t or find_taxon(" ".join(words[:2]), "species")
    if t:
        info["level"] = "species"
    else:
        t = find_taxon(genus, "genus")
        if t:
            info["level"] = "genus"
    if not t:
        return info
    if info["level"] == "genus" and t["rank"] != "genus":
        info["level"] = t["rank"]  # e.g. subfamily, for genera iNaturalist has merged
    full = (get(f"/taxa/{t['id']}").get("results") or [{}])[0]
    anc = {a.get("rank"): a.get("name") for a in full.get("ancestors", [])}
    info.update({
        "inat_id": t["id"], "inat_name": full.get("name") or t["name"],
        "family": anc.get("family"), "subfamily": anc.get("subfamily"),
        "summary": clean_summary(full.get("wikipedia_summary")), "wiki": full.get("wikipedia_url"),
        "common_en": full.get("preferred_common_name"),
    })
    photos, seen = [], set()
    for tp in full.get("taxon_photos", []):
        ph = photo(tp.get("photo") or {}, "inat")
        if ph and ph["src"] not in seen:
            seen.add(ph["src"]); photos.append(ph)
    obs = get("/observations", taxon_id=t["id"], quality_grade="research", captive="false",
              photo_license=",".join(sorted(OPEN)), order_by="votes", per_page=30).get("results", [])
    load_places({i for o in obs for i in (o.get("place_ids") or [])})
    places = Counter()
    for o in obs:
        places.update(set(countries(o.get("place_ids") or [])))
        for p in (o.get("photos") or [])[:1]:
            ph = photo(p, "inat")
            if ph and ph["src"] not in seen and len(photos) < 10:
                seen.add(ph["src"]); ph["obs"] = o["id"]; photos.append(ph)
    # A real species with no openly licensed photos: show its genus, labelled as such.
    if not photos and info["level"] == "species" and full.get("parent_id"):
        g = (get(f"/taxa/{full['parent_id']}").get("results") or [{}])[0]
        for tp in g.get("taxon_photos", [])[:6]:
            ph = photo(tp.get("photo") or {}, "inat")
            if ph:
                ph["genus"] = g.get("name")
                photos.append(ph)
    info["photos"] = photos[:10]
    # one stray record (an escapee, a wrong pin) shouldn't add a country
    common = [c for c, n in places.most_common(5) if n >= 2]
    info["wild_in"] = common or [c for c, _ in places.most_common(2)]
    return info


def main():
    stock = json.loads(STOCK.read_text())
    keys = sorted({i["species"] for i in stock["items"].values() if i.get("species") and not i.get("gone")})
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    stale = (date.today() - timedelta(days=REFRESH_DAYS)).isoformat()
    todo = [k for k in keys if k not in cache] + [k for k in keys if k in cache and cache[k].get("fetched", "") < stale]
    limit = MAX_LOOKUPS if MAX_LOOKUPS > 0 else len(todo)
    done = 0
    for k in todo[:limit]:
        try:
            cache[k] = lookup(k)
            done += 1
            print(f"{k}: {cache[k].get('level')} {len(cache[k].get('photos', []))} photos", flush=True)
        except Exception as e:  # noqa: BLE001 - one failure shouldn't stop the rest
            print(f"{k}: failed {e}", file=sys.stderr)
        if done % 20 == 0:
            OUT.write_text(json.dumps(cache, indent=1, sort_keys=True, ensure_ascii=False))
    OUT.write_text(json.dumps(cache, indent=1, sort_keys=True, ensure_ascii=False))
    print(f"looked up {done}, {len(todo) - done} left for later runs")


if __name__ == "__main__":
    main()

"""UK tarantula stock tracker.

Reads every vendor in vendors.yml, merges the results into docs/stock.json,
and sends a phone alert (ntfy) for new listings and restocks.

Env vars:
  NTFY_TOPIC  ntfy topic to push alerts to (no alerts if unset)
  PAGE_URL    link opened when you tap an alert (optional)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "docs" / "stock.json"
VENDORS_FILE = ROOT / "vendors.yml"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 (personal stock tracker)")
HEADERS = {"User-Agent": UA, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
TIMEOUT = 30
GONE_RETENTION_DAYS = 60

# Genera so listings without the word "tarantula" are still picked up.
GENERA = """acanthoscurria aphonopelma avicularia brachypelma bumba caribena ceratogyrus
chilobrachys chromatopelma cyriocosmus cyriopagopus davus ephebopus euathlus eupalaestrus
grammostola hapalopus harpactira heteroscodra heterothele homoeomma hysterocrates idiothele
iridopelma lasiodora lasiodorides megaphobema monocentropus neoholothele nhandu omothymus
ornithoctonus pamphobeteus phormictopus phormingochilus poecilotheria psalmopoeus
pterinochilus pterinopelma selenocosmia stromatopelma tapinauchenius theraphosa thrixopelma
tliltocatl tlitocatl typhochlaena xenesthis haplopelma melopoeus birupes ybyrapora
pseudhapalopus kochiana orphnaecus encyocratella dolichothele sericopelma cotztetlana
vitalius proshapalopus magulla holothele cyclosternum pelinobius haploclastus lampropelma
annandaliella thrigmopoeus cyrtopholis citharacanthus""".split()
GENUS_RE = re.compile(r"\b(" + "|".join(GENERA) + r")\b", re.I)
NOT_LIVESTOCK = re.compile(
    r"\b(enclosure|substrate|tub|hide|cork|bowl|heat ?mat|thermostat|book|poster|"
    r"t-shirt|tshirt|mug|tongs|tweezers|gift card|voucher|feeder|crickets|locusts|"
    r"roaches|mealworms|dubia|faunarium|kit only|just kit|exo terra|decor)\b", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_tarantula(text: str) -> bool:
    return bool(re.search(r"tarantula", text, re.I) or GENUS_RE.search(text))


def looks_like_livestock(name: str) -> bool:
    return not NOT_LIVESTOCK.search(name)


def clean(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or ""))).strip()


# ---------------------------------------------------------------- Shopify
def try_shopify(base: str, collection: str | None = None) -> list[dict] | None:
    feed = f"{base}{collection}/products.json" if collection else f"{base}/products.json"
    items, page = [], 1
    while page <= 20:
        r = requests.get(feed, params={"limit": 250, "page": page},
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            return None if page == 1 else items
        products = r.json().get("products", [])
        if not products:
            break
        for p in products:
            meta = " ".join([p.get("title", ""), p.get("product_type", ""),
                             " ".join(p.get("tags", []) if isinstance(p.get("tags"), list)
                                      else [str(p.get("tags", ""))])])
            # A tarantula collection is trusted as-is; the whole shop feed is filtered.
            if (not collection and not is_tarantula(meta)) or not looks_like_livestock(p.get("title", "")):
                continue
            variants = p.get("variants", [])
            prices = [float(v["price"]) for v in variants if v.get("price")]
            items.append({
                "id": f"shopify:{p['id']}",
                "name": clean(p.get("title")),
                "price": min(prices) if prices else None,
                "in_stock": any(v.get("available") for v in variants),
                "url": f"{base}/products/{p.get('handle')}",
                "listed": p.get("published_at") or p.get("created_at"),
            })
        page += 1
        time.sleep(1)
    return items


# ------------------------------------------------------------ WooCommerce
def try_woo(base: str) -> list[dict] | None:
    items, page = [], 1
    while page <= 30:
        r = requests.get(f"{base}/wp-json/wc/store/v1/products",
                         params={"per_page": 100, "page": page},
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            return None if page == 1 else items
        products = r.json()
        if not isinstance(products, list):
            return None if page == 1 else items
        if not products:
            break
        for p in products:
            cats = " ".join(c.get("name", "") + " " + c.get("slug", "")
                            for c in p.get("categories", []))
            name = clean(p.get("name"))
            if not is_tarantula(name + " " + cats) or not looks_like_livestock(name):
                continue
            pr = p.get("prices") or {}
            price = None
            if pr.get("price"):
                price = int(pr["price"]) / (10 ** int(pr.get("currency_minor_unit", 2)))
            items.append({
                "id": f"woo:{p['id']}",
                "name": name,
                "price": price,
                "in_stock": bool(p.get("is_in_stock")),
                "url": p.get("permalink"),
                "listed": None,
            })
        if len(products) < 100:
            break
        page += 1
        time.sleep(1)
    return items


# --------------------------------------------------- Browser (any website)
EXTRACT_JS = r"""
() => {
  const priceRe = /[£$]\s?\d[\d,]*(?:\.\d{1,2})?/;
  const skip = /add-to-cart|\/cart|\/basket|\/account|\/login|\/checkout|wishlist|#|mailto:|tel:/i;
  const cards = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    let href;
    try { href = new URL(a.href); } catch { continue; }
    if (href.origin !== location.origin || skip.test(a.href)) continue;
    if (a.rel === 'next' || a.rel === 'prev' || /^(next|prev|previous|\d+|›|»|←|→)$/i.test((a.innerText || '').trim())) continue;
    if (href.pathname === location.pathname || href.pathname === '/') continue;
    let el = a, card = null;
    for (let i = 0; i < 7 && el; i++) {
      el = el.parentElement;
      if (!el || el === document.body) break;
      const t = el.innerText || '';
      if (t.length > 700) break;
      if (priceRe.test(t)) { card = el; break; }
    }
    if (!card) continue;
    // A container holding several products is not a single product card.
    if (card.querySelectorAll('h1,h2,h3,h4,h5').length > 1) continue;
    const prices = (card.innerText.match(new RegExp(priceRe.source, 'g')) || []);
    if (new Set(prices).size > 3) continue;
    const head = card.querySelector('h1,h2,h3,h4,h5,[class*="title" i],[class*="name" i],[data-hook*="name"]');
    let name = (head && head.innerText) || a.innerText || a.title ||
               (a.querySelector('img') && a.querySelector('img').alt) || '';
    name = name.replace(/\s+/g, ' ').trim();
    const text = card.innerText || '';
    const url = href.origin + href.pathname;
    const prev = cards.get(card);
    if (prev && prev.name.length >= name.length) continue;
    cards.set(card, {
      name, url,
      price: (text.match(priceRe) || [null])[0],
      out: /out of stock|sold out|unavailable|currently unavailable|notify me/i.test(text),
    });
  }
  let items = [...cards.values()].filter(i => i.name && i.name.length > 2);
  // Fallback for plain stock-list pages (tables or lists of "Species ... £price").
  if (items.length === 0) {
    const seen = new Set();
    for (const el of document.querySelectorAll('tr, li, p, div')) {
      if (el.querySelector('tr, li, p, div')) continue;  // innermost blocks only
      const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
      if (t.length < 4 || t.length > 220 || !priceRe.test(t)) continue;
      const name = t.split(priceRe)[0].replace(/[-–:|]+\s*$/, '').trim() || t;
      if (name.length < 3 || seen.has(name)) continue;
      seen.add(name);
      const a = el.querySelector('a[href]');
      items.push({ name, url: a ? a.href : location.href + '#' + encodeURIComponent(name),
                   price: (t.match(priceRe) || [null])[0],
                   out: /out of stock|sold out|unavailable/i.test(t) });
    }
  }
  const next = document.querySelector('a[rel="next"], a.next, .pagination a.next, a[aria-label*="next" i]');
  return { items, next: next ? next.href : null };
}
"""


def try_browser(listings: list[str], vendor_slug: str, filter_names: bool) -> list[dict] | None:
    if not listings:
        return None
    from playwright.sync_api import sync_playwright

    found: dict[str, dict] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(user_agent=UA, locale="en-GB")
        for start in listings:
            url, hops = start, 0
            while url and hops < 15:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3500)
                    for _ in range(12):  # lazy loading + "load more" buttons
                        page.mouse.wheel(0, 20000)
                        page.wait_for_timeout(700)
                        btn = page.locator("button:has-text('Load More'), button:has-text('Show more'), a:has-text('Load more')")
                        if btn.count() and btn.first.is_visible():
                            btn.first.click()
                            page.wait_for_timeout(1500)
                    result = page.evaluate(EXTRACT_JS)
                except Exception as e:  # noqa: BLE001
                    print(f"    browser error on {url}: {e}")
                    break
                for it in result["items"]:
                    if filter_names and not is_tarantula(it["name"] + " " + it["url"]):
                        continue
                    if not looks_like_livestock(it["name"]):
                        continue
                    found.setdefault(it["url"], it)
                nxt = result.get("next")
                url = nxt if nxt and nxt != url else None
                hops += 1
            if found:
                break  # first listing that works is enough
        browser.close()
    if not found:
        return None
    out = []
    for it in found.values():
        price = None
        if it["price"]:
            try:
                price = float(re.sub(r"[£$,\s]", "", it["price"]))
            except ValueError:
                pass
        out.append({
            "id": "web:" + urlparse(it["url"]).path.rstrip("/")
                  + ("#" + urlparse(it["url"]).fragment if urlparse(it["url"]).fragment else ""),
            "name": it["name"][:160],
            "price": price,
            "in_stock": not it["out"],
            "url": it["url"],
            "listed": None,
        })
    return out


# ------------------------------------------------------------------ main
def scrape_vendor(v: dict) -> tuple[list[dict] | None, str, str]:
    base = v["base"].rstrip("/")
    # Drop tracking junk like ?srsltid=... from pasted links.
    listings = [u.split("?")[0] for u in v.get("listings", [])]
    collection = next((urlparse(u).path.rstrip("/") for u in listings
                       if "/collections/" in u), None)
    errors = []
    attempts = []
    if collection:
        attempts.append(("shopify", lambda: try_shopify(base, collection)))
    attempts += [("shopify", lambda: try_shopify(base)),
                 ("woocommerce", lambda: try_woo(base))]
    for method, fn in attempts:
        try:
            items = fn()
            if items is not None and len(items) > 0:
                return items, method, ""
        except Exception as e:  # noqa: BLE001
            errors.append(f"{method}: {e}")
    try:
        items = try_browser(listings, v["name"], v.get("filter", False))
        if items:
            return items, "browser", ""
        errors.append("browser: no products found on listing pages")
    except Exception as e:  # noqa: BLE001
        errors.append(f"browser: {e}")
    return None, "", "; ".join(errors)[:400]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"items": {}, "vendors": {}, "checked": None}


def notify(alerts: list[dict]):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic or not alerts:
        return
    new = [a for a in alerts if a["kind"] == "new"]
    back = [a for a in alerts if a["kind"] == "restock"]
    title = []
    if new:
        title.append(f"{len(new)} new")
    if back:
        title.append(f"{len(back)} back in stock")
    lines = []
    for a in (new + back)[:20]:
        sym = "$" if a.get("currency") == "USD" else "£"
        price = f" {sym}{a['price']:.2f}" if a.get("price") else ""
        tag = "NEW" if a["kind"] == "new" else "BACK"
        lines.append(f"{tag} {a['name']}{price} ({a['vendor']})")
    if len(alerts) > 20:
        lines.append(f"…and {len(alerts) - 20} more")
    headers = {"Title": "Tarantula stock: " + ", ".join(title), "Tags": "spider"}
    if os.environ.get("PAGE_URL"):
        headers["Click"] = os.environ["PAGE_URL"]
    try:
        requests.post(f"https://ntfy.sh/{topic}", data="\n".join(lines).encode("utf-8"),
                      headers=headers, timeout=TIMEOUT)
    except Exception as e:  # noqa: BLE001
        print(f"ntfy failed: {e}")


def main():
    cfg = yaml.safe_load(VENDORS_FILE.read_text())
    state = load_state()
    items, vendors = state["items"], state["vendors"]
    stamp = now_iso()
    alerts = []

    for v in cfg["vendors"]:
        if v.get("enabled", True) is False:
            continue
        name = v["name"]
        print(f"- {name}")
        found, method, err = scrape_vendor(v)
        vs = vendors.setdefault(name, {"first_ok": None})
        prev_ids = {k for k, it in items.items() if it["vendor"] == name and not it.get("gone")}

        if found is None or (len(found) < 3 and len(prev_ids) > 15):
            vs.update(status="failed", error=err or "suspiciously few items", checked=stamp)
            print(f"    FAILED {vs['error']}")
            continue

        seeding = vs.get("first_ok") is None
        vs.update(status="ok", method=method, error="", checked=stamp,
                  count=len(found), in_stock=sum(1 for f in found if f["in_stock"]))
        if seeding:
            vs["first_ok"] = stamp
        print(f"    ok via {method}: {len(found)} tarantulas ({vs['in_stock']} in stock)"
              + (" [first run, no alerts]" if seeding else ""))

        seen = set()
        for f in found:
            f["currency"] = v.get("currency", "GBP")
            key = f"{name}|{f['id']}"
            seen.add(key)
            old = items.get(key)
            rec = {**(old or {}), **f, "vendor": name, "last_seen": stamp, "gone": False}
            if old is None:
                rec["first_seen"] = stamp
                rec["new_at"] = None if seeding else (stamp if f["in_stock"] else None)
                if f["in_stock"] and not seeding:
                    alerts.append({**rec, "kind": "new"})
            else:
                was_in = old.get("in_stock") and not old.get("gone")
                if f["in_stock"] and not was_in and not seeding:
                    rec["restocked_at"] = stamp
                    alerts.append({**rec, "kind": "restock"})
            items[key] = rec
        for key in list(items):
            if items[key]["vendor"] == name and key not in seen and not items[key].get("gone"):
                items[key].update(gone=True, in_stock=False)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=GONE_RETENTION_DAYS)).isoformat()
    for key in [k for k, it in items.items() if it.get("gone") and it["last_seen"] < cutoff]:
        del items[key]

    state["checked"] = stamp
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))
    print(f"{len(alerts)} alerts")
    notify(alerts)


if __name__ == "__main__":
    sys.exit(main())

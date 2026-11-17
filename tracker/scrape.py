"""UK tarantula stock tracker.

Reads every vendor in vendors.yml, merges the results into docs/stock.json,
and sends a phone alert (ntfy) for new listings and restocks.

Env vars:
  NTFY_TOPIC  ntfy topic to push alerts to (no alerts if unset)
  PAGE_URL    link opened when you tap an alert (optional)
"""
from __future__ import annotations

import html
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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import species

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "docs" / "stock.json"
VENDORS_FILE = ROOT / "vendors.yml"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 (personal stock tracker)")
HEADERS = {"User-Agent": UA, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
TIMEOUT = 30
GONE_RETENTION_DAYS = 60
APPAREL = re.compile(r"^(xxs|xs|s|m|l|xl|xxl|[2-5]xl|small|medium|large|x-large)$", re.I)
SHAPE = "spiders-2"

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
SPIDER_GENUS_RE = re.compile(r"\b(" + "|".join(sorted(species.JUMPING_GENERA | species.OTHER_SPIDER_GENERA)) + r")\b", re.I)
SPIDER_WORDS = re.compile(r"\b(spiders?|spiderlings?|slings?|salticid\w*|jumpers?|widows?|huntsman|orb ?weavers?)\b", re.I)
ANIMAL_WORDS = re.compile(r"tarantula|spider|\bslings?\b|jumper|widow|huntsman|\bT\.|\bsp\.", re.I)
LIVE_CAT = re.compile(r"tarantula|spiderling|spiders|livestock|live inverts|invertebrates", re.I)
# Care-sheet text like "ADULT SIZE 18-20cm" describes the species, not the spider for sale.
ADULT_SIZE = re.compile(r"(adult|max(imum)?|full[- ]grown)\s*(size|leg ?span)\s*:?\s*(around|approx\.?|about|up to|c\.)?\s*"
                        r"[\d.\s\-–to]+(cm|\")?(\s*leg ?span)?", re.I)
SUPPLY_CAT = re.compile(r"starter|kits?\b|books?|media|suppl|setup|set-up|enclosure|equipment|food|feeder|accessor|decor|substrate|"
                        r"hardware|lighting|heating|book|merch|apparel|clothing|gift|plant|hygrom|tools?", re.I)
# Not spiders: other inverts, reptiles, mixed boxes, and non-spider arachnids.
NOT_SPIDER = re.compile(
    r"\b(mantis|mantids?|isopods?|scorpions?|whip ?(spider|scorpion)s?|amblypyg\w*|vinegaroons?|"
    r"solifug\w*|camel spiders?|centipedes?|millipedes?|roach(es)?|beetles?|snails?|geckos?|frogs?|toads?|"
    r"snakes?|lizards?|skinks?|dragons?|mystery|assassin|stick insects?|leaf insects?|tarantula hawk|"
    r"crickets?|locusts?|mealworms?|springtails?|ticks?|mites?|crabs?(?!\s*spider)|shrimps?|moths?|butterfl\w+|"
    r"scarab|ants?(?![- ]?(mimic|like))|ant colony|termites?|axolotl|chameleon|tortoise|pede)\b", re.I)
BULK = re.compile(r"\(\s*(bulk|bundle|x\s*\d+)|\b\d+\s*x\s+(sling|spiderling)|\bx\s*([2-9]|[1-5]\d)\b|"
                  r"\b([2-9]|[1-5]\d)\s*(slings|spiderlings)\b", re.I)
NOT_LIVESTOCK = re.compile(
    r"\b(enclosure|substrate|tub|hide|cork|bowls?|wood|heat ?mat|thermostat|book|poster|"
    r"t-shirt|tshirt|mug|tongs|tweezers|gift card|voucher|feeder|crickets|locusts|"
    r"roaches|mealworms|dubia|faunarium|kit only|just kit|exo terra|decor|set ?ups?|"
    r"complete setups?|minimum order|postage|delivery|gift|donation|review|video|competition|raffle|win the|spiderling box|pots?|caves?|burrow|nest|vouchers?|lamps?|bulbs?|heat\w*|cables?|thermo\w*|hygro\w*|terrarium|invertarium|moss|misting|spray|supplements?|grub|gel|coir|nutrobal|projector|kits?|fittings?|bedding|backing|t-?shirt|tee|hoodie|sweatshirt|sticker|keyring|mug|print|poster|plush\w*|soft toy|from only|bulk|bundle|pack of|lot of|multi ?buy)\b", re.I)


# Retry flaky connections (resets, timeouts, 5xx) a few times with backoff.
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=4, connect=4, read=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST"]))))
requests.get = _session.get  # type: ignore[assignment]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_tarantula(text: str) -> bool:
    return bool(re.search(r"tarantula", text, re.I) or GENUS_RE.search(text))


def is_spider(text: str) -> bool:
    """Tarantulas, jumping spiders and other spiders; nothing else."""
    return bool(is_tarantula(text) or SPIDER_GENUS_RE.search(text) or SPIDER_WORDS.search(text))


JUNK_URL = re.compile(r"(mystery|lucky[-_]?dip|surprise|[-_/]box([-_/]|\d|$)|bundle|bulk|plush)", re.I)


def looks_like_livestock(name: str, url: str = "") -> bool:
    if url and JUNK_URL.search(urlparse(url).path):
        return False  # e.g. "Phormictopus of" whose page is /product/birdeater-box-2/
    return not NOT_LIVESTOCK.search(name) and not BULK.search(name) and not NOT_SPIDER.search(name)


def clean(s) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


def _sized(src):
    if not src:
        return None
    src = "https:" + src if src.startswith("//") else src
    return src + ("&" if "?" in src else "?") + "width=240"


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
            if (not collection and not is_spider(meta)) or not looks_like_livestock(p.get("title", "")):
                continue
            variants = p.get("variants", [])
            hint = clean(" ".join([p.get("product_type", ""), " ".join(map(str, p.get("tags", []) or []))]))[:200]
            url = f"{base}/products/{p.get('handle')}"
            imgs = p.get("images") or []
            image = _sized(imgs[0].get("src")) if imgs else None
            real = [v for v in variants if (v.get("title") or "").lower() != "default title"]
            if any(APPAREL.match(o.strip()) for v in variants for o in (v.get("title") or "").split("/")):
                continue  # clothing
            if len(real) >= 1 and len(variants) > 1 or (real and len(variants) == 1):
                # One row per size/option, each with its own price and stock.
                for v in variants:
                    items.append({
                        "id": f"shopify:{v['id']}",
                        "name": f"{clean(p.get('title'))} – {clean(v.get('title'))}",
                        "price": float(v["price"]) if v.get("price") else None,
                        "in_stock": bool(v.get("available")),
                        "url": f"{url}?variant={v['id']}",
                        "image": _sized((v.get("featured_image") or {}).get("src")) or image,
                        "hint": hint,
                        "listed": p.get("published_at") or p.get("created_at"),
                    })
                continue
            prices = [float(v["price"]) for v in variants if v.get("price")]
            items.append({
                "id": f"shopify:{p['id']}",
                "name": clean(p.get("title")),
                "price": min(prices) if prices else None,
                "in_stock": any(v.get("available") for v in variants),
                "url": url,
                "image": image,
                "hint": hint,
                "listed": p.get("published_at") or p.get("created_at"),
            })
        page += 1
        time.sleep(1)
    return items


# ------------------------------------------------------------ WooCommerce
def _woo_price(p: dict) -> float | None:
    pr = p.get("prices") or {}
    if pr.get("price"):
        return int(pr["price"]) / (10 ** int(pr.get("currency_minor_unit", 2)))
    return None


def _pretty_option(value: str) -> str:
    value = clean(value)
    if " " not in value and re.search(r"[a-z]-|-[a-z]", value, re.I):
        value = re.sub(r"(?<=[A-Za-z])-|-(?=[A-Za-z])", " ", value)
    return value


MAX_VARIATIONS = 3000


def _option_url(permalink: str, attrs: list[dict]) -> str:
    """Link that opens the product with this size/option already selected."""
    base = (permalink or "").split("?")[0]
    q = [f"attribute_pa_{re.sub(r'[^a-z0-9]+', '-', a.get('name', '').lower()).strip('-')}={a.get('value')}"
         for a in attrs if a.get("name") and a.get("value")]
    return base + ("?" + "&".join(q) if q else "")


def _woo_variations(api: str, ids: list[int]) -> dict[int, dict]:
    """Price/stock for many variation ids: batched where the shop allows, else in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    out: dict[int, dict] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            r = requests.get(api, params={"include": ",".join(map(str, chunk)), "per_page": 100,
                                          "type": "variation"}, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and isinstance(r.json(), list):
                for v in r.json():
                    out[v["id"]] = v
        except Exception:  # noqa: BLE001
            pass
    missing = [i for i in ids if i not in out]

    def one(vid):
        try:
            r = requests.get(f"{api}/{vid}", headers=HEADERS, timeout=20)
            return vid, (r.json() if r.status_code == 200 else None)
        except Exception:  # noqa: BLE001
            return vid, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        for vid, v in pool.map(one, missing):
            if v:
                out[vid] = v
    return out


def try_woo(base: str) -> list[dict] | None:
    api = f"{base}/wp-json/wc/store/v1/products"
    products_all, page = [], 1
    while page <= 30:
        r = requests.get(api, params={"per_page": 100, "page": page}, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            if page == 1:
                return None
            break
        products = r.json()
        if not isinstance(products, list):
            if page == 1:
                return None
            break
        products_all += products
        if len(products) < 100:
            break
        page += 1
        time.sleep(1)

    keep = []
    for p in products_all:
        cats = " ".join(c.get("name", "") + " " + c.get("slug", "") for c in p.get("categories", []))
        name = clean(p.get("name"))
        named = bool(GENUS_RE.search(name) or SPIDER_GENUS_RE.search(name))
        if SUPPLY_CAT.search(cats) and not (named and LIVE_CAT.search(cats)):
            continue  # supplies, kits, books (even ones named after a spider)
        if is_spider(name + " " + cats) and looks_like_livestock(name):
            keep.append((p, name, cats))

    # Sizes chosen on the product page: read each option's own price and stock.
    var_ids = [v["id"] for p, _, _ in keep if p.get("type") == "variable"
               for v in (p.get("variations") or [])][:MAX_VARIATIONS]
    var_data = _woo_variations(api, var_ids) if var_ids else {}

    items = []
    for p, name, cats in keep:
        sku = re.sub(r"-\d+$", "", str(p.get("sku") or ""))
        hint = clean(" ".join([cats, sku, clean(p.get("short_description")),
                               clean(p.get("description"))[:160]]))[:300]
        pimgs = p.get("images") or []
        image = (pimgs[0].get("thumbnail") or pimgs[0].get("src")) if pimgs else None
        rows = []
        opts = [a.get("value", "") for var in (p.get("variations") or []) for a in var.get("attributes", [])]
        if any(APPAREL.match(o.strip()) for o in opts):
            continue  # clothing (T-shirt sizes), not a spider
        if p.get("type") == "variable":
            for var in p.get("variations") or []:
                v = var_data.get(var["id"])
                if not v:
                    rows = []
                    break
                option = " / ".join(_pretty_option(a.get("value", "")) for a in var.get("attributes", [])
                                    if a.get("value"))
                rows.append({
                    "id": f"woo:{var['id']}",
                    "name": f"{name} – {option}" if option else name,
                    "price": _woo_price(v),
                    "in_stock": bool(v.get("is_in_stock")),
                    "url": _option_url(p.get("permalink"), var.get("attributes", [])),
                    "image": ((v.get("images") or [{}])[0].get("thumbnail") or image),
                    "hint": hint,
                    "listed": None,
                })
        if rows:
            items.extend(rows)
        else:
            items.append({
                "id": f"woo:{p['id']}",
                "name": name,
                "price": _woo_price(p),
                "in_stock": bool(p.get("is_in_stock")),
                "url": p.get("permalink"),
                "image": image,
                "hint": hint,
                "listed": None,
            })
    return items


# --------------------------------------------------- Browser (any website)
EXTRACT_JS = r"""
(topOrigin) => {
  const okOrigin = o => o === location.origin || o === topOrigin;
  const priceRe = /[£$]\s?\d[\d,]*(?:\.\d{1,2})?/;
  const skip = /add-to-cart|\/cart|\/basket|\/account|\/login|\/checkout|wishlist|mailto:|tel:/i;
  const notProduct = /\/(shipping|delivery|terms|about|contact|faq|blog|care|guide|policy|privacy|returns|info|pages?)\b/i;
  // "Back in stock!" banners don't count; a real basket button or "3 left" does.
  const inStockRe = /\b\d+\s+(left|in stock|available)\b|add to (cart|basket|bag)|buy now/i;
  const outRe = /out of stock|sold out|currently unavailable/i;
  const productPath = h => { try { const u = new URL(h); return okOrigin(u.origin) ? u.pathname.replace(/\/$/, '') : null; } catch { return null; } };
  // The price you'd pay: skip struck-through / "was" / compare-at prices.
  const struck = /compare|was-price|\bwas\b|old-price|regular|original|strike|line-through|crossed/i;
  const currentPrice = (card, text) => {
    const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
    const live = [], dead = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const m = (n.textContent || '').match(priceRe);
      if (!m) continue;
      let el = n.parentElement, isDead = false;
      for (let i = 0; i < 4 && el && el !== card.parentElement; i++, el = el.parentElement) {
        const cs = getComputedStyle(el);
        if (/^(DEL|S|STRIKE)$/.test(el.tagName) || struck.test(el.className || '') ||
            (cs.textDecorationLine || cs.textDecoration || '').includes('line-through')) { isDead = true; break; }
      }
      if (/^[£$]\s?0+(\.0+)?$/.test(m[0].trim())) continue;  // £0.00 placeholders for sold-out options
      (isDead ? dead : live).push(m[0]);
    }
    if (live.length) return live[0];
    const any = (text.match(new RegExp(priceRe.source, 'g')) || []).filter(p => !/^[£$]\s?0+(\.0+)?$/.test(p.trim()));
    return any[0] || null;
  };
  const cards = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    let href;
    try { href = new URL(a.href); } catch { continue; }
    if (!okOrigin(href.origin) || skip.test(a.href) || notProduct.test(href.pathname)) continue;
    if (a.rel === 'next' || a.rel === 'prev' || /^(next|prev|previous|\d+|›|»|←|→)$/i.test((a.innerText || '').trim())) continue;
    if (href.pathname === location.pathname || href.pathname === '/') continue;
    // The card is the link itself or one of its ancestors (whichever first contains a price).
    let el = a, card = null;
    for (let i = 0; i < 8 && el && el !== document.body; i++) {
      const t = el.innerText || '';
      if (t.length > 700) break;
      if (priceRe.test(t)) { card = el; break; }
      el = el.parentElement;
    }
    if (!card) continue;
    // A container holding several products is not a single product card.
    if (card.querySelectorAll('h1,h2,h3,h4,h5').length > 1) continue;
    const paths = new Set([...card.querySelectorAll('a[href]')].map(x => productPath(x.href))
      .filter(p => p && !skip.test(p) && p !== location.pathname.replace(/\/$/, '')));
    if (paths.size > 1) continue;
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
    const img = card.querySelector('img');
    let image = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';
    if (image.startsWith('data:')) image = img.getAttribute('data-src') || '';
    cards.set(card, { name, url, image, hint: text.replace(/\s+/g, ' ').slice(0, 700), price: currentPrice(card, text),
                      out: outRe.test(text) && !inStockRe.test(text) });
  }
  let items = [...cards.values()].filter(i => i.name && i.name.length > 2);
  // Plain stock-list pages (tables or lists of "Species ... £price").
  if (items.length < 3) {
    const seen = new Set(items.map(i => i.name));
    for (const el of document.querySelectorAll('tr, li, p, div, td')) {
      if (el.querySelector('tr, li, p, div')) continue;  // innermost blocks only
      const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
      if (t.length < 4 || t.length > 220 || !priceRe.test(t)) continue;
      const name = t.split(priceRe)[0].replace(/[-–:|]+\s*$/, '').trim() || t;
      if (name.length < 3 || seen.has(name)) continue;
      seen.add(name);
      const a = el.querySelector('a[href]');
      items.push({ name, url: a ? a.href : location.href.split('#')[0] + '#' + encodeURIComponent(name),
                   price: (t.match(priceRe) || [null])[0],
                   out: outRe.test(t) && !inStockRe.test(t) });
    }
  }
  const next = document.querySelector('a[rel="next"], a.next, .pagination a.next, a[aria-label*="next" i]');
  const links = [...document.querySelectorAll('a[href]')].map(a => a.href)
    .filter(h => productPath(h) !== null && /tarantula|sling|spider|shop|store|categor|collection|emporium|invertebrate|arachnid/i.test(h)
                 && !skip.test(h) && !notProduct.test(h));
  const allLinks = [...new Set([...document.querySelectorAll('a[href]')].map(a => a.href.split('#')[0])
    .filter(h => productPath(h) !== null))].slice(0, 400);
  return { items, next: next ? next.href : null, links: [...new Set(links)], allLinks,
           title: document.title, snippet: (document.body.innerText || '').slice(0, 600) };
}
"""

DEBUG: dict[str, list] = {}


def clean_name(name: str) -> str:
    name = re.split(r"\s*(?:Sale Price:|Regular Price|Original Price|Price\s*[£$]|[£$]\s?\d)", name)[0]
    name = re.sub(r"\s*\b(sold out|out of stock|add to (cart|basket))\b.*$", "", name, flags=re.I)
    return name.strip(" -–|:")


def _load(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:  # noqa: BLE001  one retry for flaky redirects
        page.wait_for_timeout(3000)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)
    # Script-built shops (incl. store widgets in iframes): wait until a price shows anywhere.
    for _ in range(15):
        hit = False
        for frame in page.frames:
            try:
                if frame.evaluate("() => /[£$]\\s?\\d/.test(document.body ? document.body.innerText : '')"):
                    hit = True
                    break
            except Exception:  # noqa: BLE001
                pass
        if hit:
            break
        page.wait_for_timeout(1000)
    # Lazy loading + "load more" buttons: keep going until the page stops growing.
    last, steady = -1, 0
    for _ in range(40):
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(900)
        btn = page.locator("button:has-text('Load More'), button:has-text('Show more'), a:has-text('Load more'), "
                           "button:has-text('Load more')")
        try:
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(2000)
                steady = 0
                continue
        except Exception:  # noqa: BLE001
            pass
        size = page.evaluate("() => document.querySelectorAll('a[href]').length + (document.body.innerText.match(/£/g) || []).length")
        steady = steady + 1 if size == last else 0
        last = size
        if steady >= 3:
            break
    # Some shops (e.g. embedded store widgets) render products inside iframes.
    merged = None
    for frame in page.frames:
        try:
            r = frame.evaluate(EXTRACT_JS, urlparse(page.url).scheme + "://" + urlparse(page.url).netloc)
        except Exception:  # noqa: BLE001
            continue
        if merged is None:
            merged = r
            merged["frames"] = len(page.frames)
        else:
            merged["items"] += r["items"]
            merged["allLinks"] += r.get("allLinks", [])
            merged["next"] = merged["next"] or r.get("next")
    body = page.evaluate("() => document.body.innerText")
    i = body.find("£")
    merged["frame_urls"] = [f.url[:80] for f in page.frames][:6]
    merged["snippet"] = (body[max(0, i - 300):i + 300] if i >= 0 else body[:600])
    merged["pounds"] = body.count("£")
    return merged


def try_browser(listings: list[str], vendor: str, filter_names: bool, base: str,
                follow: str | None = None, stages: dict | None = None) -> list[dict] | None:
    from playwright.sync_api import sync_playwright

    found: dict[str, dict] = {}
    log = DEBUG.setdefault(vendor, [])
    cur = {"stage": None}

    def harvest(result, force_filter):
        n = 0
        for it in result["items"]:
            it["name"] = clean_name(it["name"])
            if len(it["name"]) < 3:
                continue
            # Only the URL path counts: a shop called "...tarantulas.co.uk" says nothing about the item.
            if (filter_names or force_filter) and not is_spider(it["name"] + " " + urlparse(it["url"]).path):
                continue
            if not looks_like_livestock(it["name"], it["url"]):
                continue
            if cur["stage"]:  # this list page only sells one size, e.g. "Juvenile Spiders"
                it["hint"] = f"{it.get('hint', '')} {cur['stage']}".strip()
            if it["url"] not in found:
                found[it["url"]] = it
                n += 1
        return n

    def crawl(start, force_filter=False):
        url, hops, total, result = start, 0, 0, None
        while url and hops < 15:
            try:
                result = _load(page, url)
            except Exception as e:  # noqa: BLE001
                log.append({"url": url, "error": str(e)[:200]})
                break
            got = harvest(result, force_filter)
            total += got
            log.append({"url": page.url, "title": result["title"], "found": got,
                        "frames": result.get("frame_urls"), "pounds": result.get("pounds"),
                        "snippet": result["snippet"] if got == 0 else ""})
            nxt = result.get("next")
            url = nxt if nxt and nxt != url else None
            hops += 1
        return result

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(user_agent=UA, locale="en-GB")
        visited = set()
        for start in listings:
            cur["stage"] = (stages or {}).get(start)
            res = crawl(start)
            visited.add(start)
            # Optional: also walk sibling category pages (e.g. Slings -> Juveniles -> Adults).
            if follow and res:
                cur["stage"] = None
                for link in [l for l in res.get("allLinks", []) if re.search(follow, l)][:10]:
                    if link not in visited:
                        visited.add(link)
                        crawl(link)
        cur["stage"] = None
        if not found:
            # Discover tarantula pages from the home page and try those.
            home = crawl(base + "/", force_filter=True)
            for link in (home or {}).get("links", [])[:8]:
                crawl(link, force_filter=True)
        browser.close()
    if not found:
        return None
    out = []
    for it in found.values():
        price = None
        if it["price"]:
            try:
                price = float(re.sub(r"[£$,\s]", "", it["price"])) or None
            except ValueError:
                pass
        pu = urlparse(it["url"])
        out.append({
            "id": "web:" + pu.path.rstrip("/") + ("#" + pu.fragment if pu.fragment else ""),
            "name": it["name"][:160],
            "price": price,
            "in_stock": not it["out"],
            "url": it["url"],
            "hint": re.sub(r"\s+", " ", ADULT_SIZE.sub(" ", it.get("hint", "")))[:400],
            "image": it.get("image") or None,
            "listed": None,
        })
    return out


# ------------------------------------------------------------------ main
def _strip_tracking(u: str) -> str:
    """Drop tracking junk (?srsltid=, utm_*, gclid...) but keep real options like ?limit=180."""
    base, _, q = u.partition("?")
    keep = [kv for kv in q.split("&") if kv and not re.match(r"(srsltid|utm_\w+|gclid|fbclid|mc_\w+)=", kv)]
    return base + ("?" + "&".join(keep) if keep else "")


def scrape_vendor(v: dict) -> tuple[list[dict] | None, str, str]:
    base = v["base"].rstrip("/")
    # Drop tracking junk like ?srsltid=... from pasted links.
    # A listing is a URL, or {url: ..., stage: ...} for a page that only sells one size.
    entries = [u if isinstance(u, dict) else {"url": u} for u in v.get("listings", [])]
    listings = [_strip_tracking(e["url"]) for e in entries]
    stages = {_strip_tracking(e["url"]): e["stage"] for e in entries if e.get("stage")}
    collections = [urlparse(u).path.rstrip("/") for u in listings if "/collections/" in u]
    errors = []
    attempts = []
    if collections:
        def all_collections():
            merged = {}
            for c in collections:
                for it in try_shopify(base, c) or []:
                    merged[it["id"]] = it
            return list(merged.values()) or None
        attempts.append(("shopify", all_collections))
    attempts += [("shopify", lambda: try_shopify(base)),
                 ("woocommerce", lambda: try_woo(base))]
    feed_ok = ""
    for method, fn in attempts:
        try:
            items = fn()
            if items is not None and len(items) > 0:
                return items, method, ""
            if items is not None:
                feed_ok = method
        except Exception as e:  # noqa: BLE001
            errors.append(f"{method}: {e}")
    if errors:  # keep a record of why the shop's own feed didn't work this time
        DEBUG.setdefault(v["name"], []).append({"feed_errors": [e[:300] for e in errors]})
    try:
        items = try_browser(listings, v["name"], v.get("filter", False), base, v.get("follow"), stages)
        if items:
            return items, "browser", ""
        if feed_ok:
            return [], feed_ok, ""  # shop feed works, it just has no spiders listed right now
        errors.append("browser: no products found (see docs/debug.json)")
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
    headers = {"Title": "Spider stock: " + ", ".join(title), "Tags": "spider"}
    if os.environ.get("PAGE_URL"):
        headers["Click"] = os.environ["PAGE_URL"]
    try:
        requests.post(f"https://ntfy.sh/{topic}", data="\n".join(lines).encode("utf-8"),
                      headers=headers, timeout=TIMEOUT)
    except Exception as e:  # noqa: BLE001
        print(f"ntfy failed: {e}")


def list_date(v: dict) -> str | None:
    """'Last updated 09/10/2026' on a shop's price-list page -> '2026-10-09'."""
    for e in v.get("listings", []):
        url = e["url"] if isinstance(e, dict) else e
        try:
            text = clean(requests.get(url, headers=HEADERS, timeout=30).text)
        except Exception:  # noqa: BLE001
            continue
        m = re.search(r"last updated:?\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", text, re.I)
        if m:
            d, mth, y = (int(x) for x in m.groups())
            return f"{y + 2000 if y < 100 else y:04d}-{mth:02d}-{d:02d}"
    return None


CORRECTIONS_FILE = Path(__file__).resolve().parent.parent / "corrections.yml"


def apply_corrections(items: dict) -> None:
    """Fix mistakes in shops' own listings (corrections.yml): wrong names, stages, sexes,
    lifestyles, or listings that are not spiders at all."""
    if not CORRECTIONS_FILE.exists():
        return
    from lifestyle import lifestyle_of
    for c in yaml.safe_load(CORRECTIONS_FILE.read_text()) or []:
        rx = re.compile(c["match"], re.I)
        for key in list(items):
            it = items[key]
            if c.get("vendor") and it["vendor"].lower() != c["vendor"].lower():
                continue
            if not rx.search(f"{it['name']} {it.get('url', '')}"):
                continue
            if c.get("drop"):
                del items[key]
                continue
            fix = dict(c.get("set") or {})
            it.update(fix)
            if "species" in fix:
                it["group"] = fix.get("group") or species.group_of(it)
                if "lifestyle" not in fix:
                    it["lifestyle"] = lifestyle_of(it)


def main():
    cfg = yaml.safe_load(VENDORS_FILE.read_text())
    state = load_state()
    items, vendors = state["items"], state["vendors"]
    stamp = now_iso()
    alerts = []

    only = {n.strip().lower() for n in os.environ.get("ONLY_VENDORS", "").split(",") if n.strip()}
    todo = [v for v in cfg["vendors"] if v.get("enabled", True) is not False
            and (not only or v["name"].lower() in only)]
    # Shops are scraped side by side (each browser in its own thread), then merged in order.
    from concurrent.futures import ThreadPoolExecutor
    started = time.time()
    with ThreadPoolExecutor(max_workers=int(os.environ.get("SCRAPE_THREADS", "6"))) as pool:
        results = list(pool.map(lambda v: (v, *scrape_vendor(v)), todo))
    print(f"scraped {len(todo)} shops in {time.time() - started:.0f}s")

    for v, found, method, err in results:
        name = v["name"]
        print(f"- {name}")
        if found:
            found = [f for f in found if looks_like_livestock(f["name"], f.get("url", ""))]
            # The same listing can show up on two category pages: keep one.
            uniq, seen_ids, seen_rows = [], set(), set()
            for f in found:
                row = (f["url"].rstrip("/"), re.sub(r"\W+", "", f["name"].lower()), f.get("price"))
                if f["id"] in seen_ids or row in seen_rows:
                    continue
                seen_ids.add(f["id"]); seen_rows.add(row); uniq.append(f)
            found = uniq
        vs = vendors.setdefault(name, {"first_ok": None})
        prev_ids = {k for k, it in items.items() if it["vendor"] == name and not it.get("gone")}

        # A shop whose own feed normally works fell back to reading pages and got fewer
        # listings: that's a bad read, not stock selling out. Keep the last results.
        degraded = (found is not None and method == "browser" and vs.get("method") in ("shopify", "woocommerce")
                    and len(found) < 0.9 * len(prev_ids))
        if degraded:
            err = f"shop feed unavailable this run ({len(found)} of {len(prev_ids)} read from pages); kept last results"
        if found is None or degraded or (len(found) < 3 and len(prev_ids) > 15):
            vs.update(status="failed", error=err or "suspiciously few items", checked=stamp)
            print(f"    FAILED {vs['error']}")
            continue

        # First run for a shop, or a big jump after its links were fixed: record quietly.
        # SHAPE changes when listings are split differently (e.g. per size option);
        # the first run after that records quietly instead of alerting on everything.
        seeding = vs.get("shape") != SHAPE or vs.get("first_ok") is None or (
            len(found) - len(prev_ids) > max(10, len(prev_ids)))
        vs.update(status="ok", method=method, error="", checked=stamp,
                  count=len(found), in_stock=sum(1 for f in found if f["in_stock"]))
        vs["shape"] = SHAPE
        if seeding:
            vs["first_ok"] = stamp
        print(f"    ok via {method}: {len(found)} spiders ({vs['in_stock']} in stock)"
              + (" [first run, no alerts]" if seeding else ""))

        # Some shops only publish a price list and say "phone to check availability":
        # nothing on the page says what is actually in stock, so never show it as in stock.
        unconfirmed = v.get("stock") == "unconfirmed"
        if unconfirmed:
            vs["stock"] = "unconfirmed"
            vs["list_updated"] = list_date(v) or vs.get("list_updated")
            vs["in_stock"] = 0
        else:
            vs.pop("stock", None)
            vs.pop("list_updated", None)

        seen = set()
        for f in found:
            f["currency"] = v.get("currency", "GBP")
            if unconfirmed:
                f["in_stock"] = False
                f["unconfirmed"] = True
            if v.get("stage"):  # shop page that only sells one size, e.g. "Spiderlings for Sale"
                f["hint"] = f"{f.get('hint', '')} {v['stage']}".strip()
            key = f"{name}|{f['id']}"
            seen.add(key)
            old = items.get(key)
            rec = {**(old or {}), **f, "vendor": name, "last_seen": stamp, "gone": False}
            if not unconfirmed:
                rec.pop("unconfirmed", None)
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

    # Drop anything that is clearly not a spider (old junk rows included).
    for key in [k for k, it in items.items() if not looks_like_livestock(it["name"], it.get("url", ""))]:
        del items[key]
    # Forget shops that have been removed from vendors.yml.
    active = {v["name"] for v in cfg["vendors"] if v.get("enabled", True) is not False}
    for name in [n for n in vendors if n not in active]:
        del vendors[name]
    for key in [k for k, it in items.items() if it["vendor"] not in active]:
        del items[key]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=GONE_RETENTION_DAYS)).isoformat()
    for key in [k for k, it in items.items() if it.get("gone") and it["last_seen"] < cutoff]:
        del items[key]

    species.annotate(items)
    apply_corrections(items)
    # Without a recognisable species name, keep it only if the name says it's a spider.
    for key in [k for k, it in items.items()
                if not it.get("species") and not ANIMAL_WORDS.search(it["name"] + " " + (it.get("hint") or ""))]:
        del items[key]
    state["checked"] = stamp
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))
    (STATE_FILE.parent / "debug.json").write_text(json.dumps(DEBUG, indent=1))
    print(f"{len(alerts)} alerts")
    notify(alerts)


if __name__ == "__main__":
    sys.exit(main())

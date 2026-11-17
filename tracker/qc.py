"""Quality check: compare the tracker's data with the shops' real product pages.

Usage: python tracker/qc.py docs/stock.json [per_shop]
Opens a random sample of listings from every shop in a real browser and checks
that the recorded price appears on the page and that in-stock / sold-out agrees.
Also checks every listing's species against its own name/URL.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import defaultdict

from playwright.sync_api import sync_playwright

PAGE_JS = r"""
() => {
  const pick = s => document.querySelector(s);
  const main = pick('.summary, .product-summary, form[action*="/cart/add"], [data-hook="product-page"], .product-details, .ec-store__content-wrapper, .details-product, main') || document.body;
  let area = main;
  // Widen to a block that holds the add-to-cart control and a price.
  for (let i = 0; i < 4 && area.parentElement && !/£/.test(area.innerText || ''); i++) area = area.parentElement;
  const text = (area.innerText || '').replace(/\s+/g, ' ');
  const btns = [...area.querySelectorAll('button, input[type=submit], a')].filter(b => /add to (cart|basket|bag)|buy now/i.test(b.innerText || b.value || ''));
  const enabled = btns.some(b => !b.disabled && !/disabled/.test(b.className) && b.getAttribute('aria-disabled') !== 'true');
  return { text: text.slice(0, 4000), out: /out of stock|sold out|currently unavailable/i.test(text),
           cart: btns.length > 0, enabled, title: document.title };
}
"""


def money_variants(p: float) -> list[str]:
    return [f"£{p:.2f}", f"£{p:,.2f}", f"£{p:g}", f"£{int(p)}" if p == int(p) else f"£{p:.2f}"]


def species_ok(it: dict) -> bool:
    key = it.get("species")
    if not key:
        return True
    genus, _, ep = key.partition(" ")
    hay = re.sub(r"[^a-z]", "", (it["name"] + it["url"] + (it.get("hint") or "")).lower())
    words = [w for w in re.sub(r"^sp\.?\s*", "", ep).split() if len(w) > 3]
    return all(w[:5] in hay for w in words) if words else True


def main():
    path = sys.argv[1]
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    d = json.load(open(path))
    live = [i for i in d["items"].values() if not i.get("gone")]
    by_vendor = defaultdict(list)
    for it in live:
        by_vendor[it["vendor"]].append(it)

    print("== species name vs listing (mismatches)")
    for it in live:
        if it["in_stock"] and not species_ok(it):
            print(f"  ? {it['vendor'][:16]:16} {it['species_name'][:34]:34} <- {it['name'][:60]}")

    print("\n== live page checks")
    random.seed(7)
    proxy = {"server": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
    problems = 0
    checked = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch(proxy=proxy)
        page = b.new_page(ignore_https_errors=True, locale="en-GB")
        for vendor, items in sorted(by_vendor.items()):
            ins = [i for i in items if i["in_stock"] and "#" not in i["url"]]
            outs = [i for i in items if not i["in_stock"] and "#" not in i["url"]]
            sample = random.sample(ins, min(len(ins), per - min(2, len(outs)))) + random.sample(outs, min(2, len(outs)))
            for it in sample:
                checked += 1
                try:
                    page.goto(it["url"], wait_until="domcontentloaded", timeout=40000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(2500)
                    r = page.evaluate(PAGE_JS)
                    for fr in page.frames[1:]:  # embedded store widgets
                        try:
                            fr_r = fr.evaluate(PAGE_JS)
                        except Exception:  # noqa: BLE001
                            continue
                        if "£" in fr_r["text"]:
                            r["text"] += " " + fr_r["text"]
                            r["out"] = r["out"] or fr_r["out"]
                            r["cart"] = r["cart"] or fr_r["cart"]
                            r["enabled"] = r["enabled"] or fr_r["enabled"]
                except Exception as e:  # noqa: BLE001
                    print(f"  ! {vendor[:16]:16} could not open {it['url'][:70]} ({str(e)[:60]})")
                    problems += 1
                    continue
                issues = []
                if it.get("price") and it.get("currency", "GBP") == "GBP":
                    if not any(v in r["text"] for v in money_variants(float(it["price"]))):
                        issues.append(f"price £{it['price']} not on page")
                page_in = r["enabled"] and not r["out"] if r["cart"] else not r["out"]
                if it["in_stock"] and r["out"] and not r["enabled"]:
                    issues.append("we say IN stock, page says sold out")
                if not it["in_stock"] and page_in and r["cart"]:
                    issues.append("we say SOLD OUT, page has add-to-cart")
                mark = "x" if issues else "ok"
                problems += bool(issues)
                print(f"  {mark:2} {vendor[:16]:16} {'in ' if it['in_stock'] else 'out'} £{it.get('price')} "
                      f"{it['name'][:42]:42} {'; '.join(issues)}")
        b.close()
    print(f"\n{checked} pages checked, {problems} with problems")


if __name__ == "__main__":
    main()

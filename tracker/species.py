"""Work out species, life stage and sex from messy shop listings.

Shops write the same spider many ways ("Brachypelma Hamorii", "Mexican Red Knee
Tarantula, Brachypelma hamorii", "B. hamorii 2cm"). This turns each listing into
a species key so the stock page can show every shop's offer for one species
together.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import unquote, urlparse

KNOWN_GENERA = set("""
abdomegaphobema acanthoscurria acanthopelma aenigmarachne ami anqasha antillena aphonopelma
aspinochilus augacephalus avicularia birupes bonnetina brachionopus brachypelma bumba
cardiopelma caribena catumiri ceratogyrus chaetopelma chilobrachys chilocosmia chromatopelma
cilantica citharacanthus coremiocnemis cotztetlana crassicrus cyclosternum cyriocosmus
cyriopagopus cyrtopholis davus dolichothele encyocratella ephebopus eucratoscelus euathlus
eupalaestrus euthycaelus grammostola guyruita hapalopus hapalotremus haploclastus haplopelma
harpactira harpactirella hemirrhagus heteroscodra heterothele holothele homoeomma
hysterocrates idiothele iridopelma ischnocolus kankuamo kochiana lampropelma lasiocyano
lasiodora lasiodorides lyrognathus magulla megaphobema melognathus melopoeus metriopelma
monocentropus munduruku neoholothele nesipelma nhandu omothymus orphnaecus ornithoctonus
pachistopelma pamphobeteus pelinobius phlogiellus phlogius phormictopus phormingochilus
phrixotrichus plesiopelma poecilotheria proshapalopus psalmopoeus pseudhapalopus
pseudoclamoris pterinochilus pterinopelma reversopelma selenocosmia selenotholus
selenotypus sericopelma sickius stromatopelma tapinauchenius theraphosa thrigmopoeus
thrixopelma tliltocatl tmesiphantes typhochlaena umbyquyra vitalius xenesthis ybyrapora
yanomamius
""".split())

# Misspellings and old names -> current hobby names.
GENUS_FIX = {
    "tlitocatl": "tliltocatl", "theraposa": "theraphosa", "lasiodera": "lasiodora",
    "psalmopeus": "psalmopoeus", "pseudohapalopus": "pseudhapalopus", "pseudohaplopus": "pseudhapalopus", "thrixoplema": "thrixopelma", "cyriopagopoeus": "cyriopagopus", "pterinochillus": "pterinochilus",
    "phormingochillus": "phormingochilus", "chilobrachis": "chilobrachys",
}
EPITHET_FIX = {
    "albopilosum": "albopilosus", "albopilosom": "albopilosus", "atrichromatus": "atrichomatus", "bohemi": "boehmei",
    "boehmi": "boehmei", "versilcolor": "versicolor", "blondii": "blondi", "seemani": "seemanni",
    "victorii": "victori", "sazmai": "sazimai", "lividum": "lividus", "hati": "hatihati",
"cyaneopubescens": "cyaneopubescens", "vagan": "vagans",
}
SPECIES_FIX = {
    "brachypelma albopilosus": "tliltocatl albopilosus",
    "brachypelma vagans": "tliltocatl vagans",
    "haplopelma lividus": "cyriopagopus lividus",
    "avicularia versicolor": "caribena versicolor",
    "nhandu chromatus": "vitalius chromatus",
    "pterinopelma sazimai": "lasiocyano sazimai",
    "brachypelma smithi": "brachypelma hamorii",
}

DESCRIPTOR = re.compile(r"^(blue|green|red|black|tiger|small|large|giant|dwarf|purple|gold|golden|orange|"
                        r"white|yellow|chilean|titan|lava|brown|pink|female|male|bird|earth|tree)$")
LATIN_END = re.compile(r"(us|a|i|um|is|ae|es|or|ax|ex|ix|ii|on|ensis|ata|ina|oides)$")
STOP = re.compile(r"^(cb|wc|af|am|mm|sa|s/a|juvenile|juvie|sling|slings|spiderling|spiderlings|female|"
                  r"male|unsexed|adult|sub|semi|mature|pair|tarantula|cm|mm|ex|aka|the)$", re.I)
SIZE_WORDS = re.compile(
    r"\b(\d+(\.\d+)?\s*(-|to)?\s*\d*(\.\d+)?\s*(cm|mm|\"|inch(es)?)|cb|wc|\d+ left|sling[s]?|spiderling[s]?|"
    r"juvenile|juvie|sub[- ]?adult|semi[- ]?adult|s/a|adult|mature|female|male|unsexed|pair|af|am|mm|"
    r"tarantula[s]?|bird[- ]?eat(ing|er)|\(\s*\))\b", re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z.\-’']*|\"[^\"]+\"|“[^”]+”", text)


def _epithet_after(tokens: list[str], i: int) -> str | None:
    if i >= len(tokens):
        return None
    t = tokens[i].strip(".,").lower()
    if t in ("sp", "spp", "cf", "aff"):
        # sp. "Locality" or sp. Locality Words
        rest = []
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if nxt.startswith(("\"", "“")):  # sp. "Locality" -> just the quoted part
            rest = [nxt.strip("\"“”").lower()]
        else:
            for tok in tokens[i + 1:i + 3]:
                clean = tok.strip("\"“”'’.,()").lower()
                if (not clean or STOP.match(clean) or SIZE_WORDS.fullmatch(clean)
                        or re.match(r"^\d", clean) or re.search(r"adult|juv|sling", clean)
                        or (rest and DESCRIPTOR.match(clean))):
                    break
                rest.append(clean)
        return "sp. " + " ".join(rest) if rest else "sp."
    if re.match(r"^[a-z][a-z\-]{2,}$", t) and not STOP.match(t):
        return t
    return None


def find_binomial(text: str, genera: set[str]) -> str | None:
    tokens = _words(text.replace("—", " ").replace("–", " "))
    for i, tok in enumerate(tokens):
        g = GENUS_FIX.get(tok.lower(), tok.lower())
        if tok.endswith(".") and len(tok.rstrip(".")) >= 4:  # "Ornith." / "Aphono.."
            pre = tok.rstrip(".").lower()
            hits = [x for x in genera if x.startswith(pre)]
            if len(hits) == 1:
                g = hits[0]
        if g in genera:
            ep = _epithet_after(tokens, i + 1)
            if ep:
                return normalise(f"{g} {ep}")
    # Unknown genus: Capitalised word + latin-looking lower-case epithet, or "Xxx sp."
    for i, tok in enumerate(tokens[:-1]):
        if not re.match(r"^[A-Z][a-z]{4,}$", tok):
            continue
        nxt = tokens[i + 1].strip(".,")
        if nxt.lower() == "sp" or (re.match(r"^[a-z]{4,}$", nxt) and LATIN_END.search(nxt)
                                   and not STOP.match(nxt)):
            ep = _epithet_after(tokens, i + 1)
            if ep:
                return normalise(f"{tok.lower()} {ep}")
    return None


LOCALITY_FIX = {"dom purple": "dominican purple", "machalla": "machala", "platyomma": "platyoma",
                "magnanegra": "manganegra", "columbia": "colombia", "columbia large": "colombia large"}


def normalise(key: str) -> str:
    g, _, ep = key.partition(" ")
    g = GENUS_FIX.get(g, g)
    if ep.startswith("sp. "):
        loc = re.sub(r"[-/_]+", " ", ep[4:])
        words = []
        for w in loc.split():
            if not words or words[-1] != w:
                words.append(w)
        loc = " ".join(words)
        ep = "sp. " + LOCALITY_FIX.get(loc, loc)
    elif not ep.startswith("sp."):
        ep = " ".join(EPITHET_FIX.get(w, w) for w in ep.split()[:1])
    key = f"{g} {ep}".strip()
    return SPECIES_FIX.get(key, key)


def display_name(key: str) -> str:
    g, _, ep = key.partition(" ")
    if ep.startswith("sp. ") and len(ep) > 4:
        return f'{g.capitalize()} sp. "{ep[4:].title()}"'
    return f"{g.capitalize()} {ep}"


def common_part(name: str, key: str) -> str | None:
    """The non-scientific words of a listing name, e.g. 'Mexican Red Knee'."""
    g, _, ep = key.partition(" ")
    text = name
    m = re.search(r"\(([^)]+)\)", text)
    if m and not re.search(g, m.group(1), re.I):
        text = m.group(1)
    else:
        text = re.sub(re.escape(g) + r"\s+(sp\.?\s*)?[\"“]?[\w\- ]*?" + (re.escape(ep.split()[0]) if ep and not ep.startswith("sp") else ""),
                      " ", text, flags=re.I)
    text = re.sub(r"\(.*?\)|[\"“”]", " ", text)
    text = SIZE_WORDS.sub(" ", text)
    text = re.sub(r"[^A-Za-z' ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = [w for w in text.split() if not re.match(r"^(ex|aka|cb|wc|and|the|of)$", w, re.I)]
    if 1 <= len(words) <= 5 and len(" ".join(words)) >= 5:
        return " ".join(w.capitalize() for w in words)
    return None


def stage_of(text: str) -> str:
    t = text.lower()
    if re.search(r"sub[\s-]?adult|semi[\s-]?adult|\bs/a\b|\(sa\)", t):
        return "subadult"
    if re.search(r"spiderling|\bslings?\b|\bslg\b", t):
        return "sling"
    if re.search(r"juvenile|juvie|\bjuv\b|\bjuvs?\b", t):
        return "juvenile"
    if re.search(r"\badult\b|\bmature\b|\b(af|am|mm)\b", t):
        return "adult"
    sizes = []
    for a, b, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)?\s*(\d+(?:\.\d+)?)?\s*(cm|\"|inch|in\b)", t):
        v = float(b or a)
        sizes.append(v * 2.54 if unit != "cm" else v)
    sizes = [s for s in sizes if 0.2 <= s <= 25]
    if sizes:
        s = max(sizes)
        if s <= 3.5:
            return "sling"
        if s <= 7:
            return "juvenile"
        if s <= 10:
            return "subadult"
        return "adult"
    return ""


def sex_of(text: str) -> str:
    t = text.lower()
    if re.search(r"\b1\.1\b|\bpair\b", t):
        return "pair"
    if re.search(r"\bfemales?\b|♀|\baf\b|\b0\.1\b", t):
        return "female"
    if re.search(r"\bmales?\b|♂|\b(am|mm)\b|\b1\.0\b", t):
        return "male"
    return ""


def annotate(items: dict) -> None:
    """Add species, species_name, common, stage and sex to every item in place."""
    live = list(items.values())
    genera = set(KNOWN_GENERA)

    # Pass 1: species from the listing name, then from the URL slug.
    for it in live:
        hint = it.get("hint", "")
        key = find_binomial(it["name"], genera)
        if not key:
            slug = unquote(urlparse(it.get("url", "")).path.rstrip("/").split("/")[-1])
            slug_text = re.sub(r"[-_]+", " ", slug)
            key = find_binomial(slug_text, genera)
            if key and key.split()[0] not in genera:
                key = None  # slugs only count for genera we already trust
        it["species"] = key
        if key:
            genera.add(key.split()[0])
        text = f"{it['name']} {hint}"
        it["stage"] = stage_of(it["name"]) or stage_of(hint)
        it["sex"] = sex_of(text)

    # Second look now that genera seen in other shops are known.
    for it in live:
        if not it["species"]:
            it["species"] = find_binomial(it["name"], genera)

    # Abbreviated genus, e.g. "T. kahlenbergeri" -> tliltocatl kahlenbergeri.
    by_epithet = defaultdict(set)
    for it in live:
        if it["species"] and not it["species"].split(" ", 1)[1].startswith("sp"):
            g, ep = it["species"].split(" ", 1)
            by_epithet[ep].add(g)
    for it in live:
        if it["species"]:
            continue
        m = re.search(r"\b([A-Z])\.\s*([a-z]{4,})", it["name"])
        if m:
            ep = EPITHET_FIX.get(m.group(2), m.group(2))
            cands = [g for g in by_epithet.get(ep, ()) if g[0] == m.group(1).lower()]
            if len(cands) == 1:
                it["species"] = f"{cands[0]} {ep}"

    # Learn common names from listings that have both, then match common-only listings.
    commons = defaultdict(Counter)
    for it in live:
        if it["species"]:
            c = common_part(it["name"], it["species"])
            if c:
                commons[it["species"]][c] += 1
    by_common = {}
    for key, cnt in commons.items():
        for c in cnt:
            by_common.setdefault(c.lower(), Counter())[key] += cnt[c]
    for it in live:
        if it["species"]:
            continue
        plain = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z' ]", " ", SIZE_WORDS.sub(" ", it["name"]))).strip().lower()
        if plain in by_common:
            it["species"] = by_common[plain].most_common(1)[0][0]

    for it in live:
        key = it["species"]
        it["species_name"] = display_name(key) if key else it["name"]
        it["common"] = commons[key].most_common(1)[0][0] if key and commons.get(key) else ""
        if it.get("hint"):
            it["hint"] = it["hint"][:240]

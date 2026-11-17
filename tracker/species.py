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

from lifestyle import lifestyle_of

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
yanomamius amazonius viridasius selenobrachys neischnocolus ornithoctoninae spinosatibiapalpus euthycaelus magnacrus selenocosmiinae theraphosidae
""".split())

JUMPING_GENERA = set("""
anasaitis asemonea attulus bianor carrhotus chrysilla colonus cosmophasis cytaea epeus eris euophrys
evarcha habronattus harmochirus hasarius heliophanus hentzia holoplatys hyllus hypoblemum irura
lyssomanes maevia maratus marpissa menemerus mopsus myrmarachne ocrisiona opisthoncus paraphidippus
pelegrina pellenes phidippus philaeus platycryptus plexippus portia ptocasius rhene saitis salticus
sassacus servaea siler simaetha sitticus tauala telamonia thiania thyene zygoballus
""".split())

OTHER_SPIDER_GENERA = set("""
agelena selenops ancylometes aphantochilus araneus argiope atypus caerostris cteniza cupiennius cyclosa
cyrtophora deinopis diguetia dolomedes dresserus eratigena eresus euagrus eusparassus filistata
gandanameno gasteracantha geolycosa hersilia heteropoda hexophthalma hippasa hogna holocnemus
ischnothele kukulcania latrodectus linothele liphistius loxosceles lycosa macrothele micrommata
misumena nemesia nephila nephilingis oxyopes pandercetes pardosa parasteatoda peucetia pholcus
phoneutria phrynarachne poltys psechrus rabidosa scytodes sicarius sosippus sphodros steatoda
stegodyphus tegenaria tengella thomisus tibellus tigrosa trichonephila ummidia olios
cyclocosmia luthela calommata barylestis holconia africactenus piloctenus ctenus sason idiops
gorgyrella heligmomerus bothriocyrtum aptostichus antrodiaetus conothele latouchia porrhothele
segestria dysdera zoropsis trechona isopeda neosparassus delena pisaura thalassius nilus
orientothele bolostromus barychelidae
""".split())

# Misspellings and old names -> current hobby names.
GENUS_FIX = {
    "phormictopuss": "phormictopus", "aviculata": "avicularia", "tiltocatl": "tliltocatl",
    "ornith": "ornithoctoninae", "cheatopelma": "chaetopelma",
    "tlitocatl": "tliltocatl", "amazonicus": "amazonius", "avicuaria": "avicularia",
    "ideothele": "idiothele", "orphaneus": "orphnaecus", "photmictopus": "phormictopus", "phormingochiluis": "phormingochilus",
    "phormictopous": "phormictopus", "brachypelama": "brachypelma", "poecilotheira": "poecilotheria", "theraposa": "theraphosa", "lasiodera": "lasiodora",
    "psalmopeus": "psalmopoeus", "pseudohapalopus": "pseudhapalopus", "pseudohaplopus": "pseudhapalopus", "thrixoplema": "thrixopelma", "cyriopagopoeus": "cyriopagopus", "pterinochillus": "pterinochilus",
    "phormingochillus": "phormingochilus", "chilobrachis": "chilobrachys",
}
EPITHET_FIX = {
    "diamantensis": "diamantinensis", "minerium": "mineirum",
    "albopilosum": "albopilosus", "albopilosom": "albopilosus",
    "pingungensis": "pingtungensis", "cyanopubescens": "cyaneopubescens", "oliveaceum": "olivaceum",
    "caraponensis": "carapoensis", "metalica": "metallica", "germanii": "germani", "albostriatum": "albostriatus",
    "uataman": "uatuman", "ornate": "ornata", "vittate": "vittata", "stiata": "striata",
    "vegans": "vagans", "gniculata": "geniculata", "viollosella": "villosella", "gabomensis": "gabonensis",
    "huahnini": "huahini", "albostiantum": "albostriatus", "colloratovilosum": "coloratovillosus", "coloratovillosum": "coloratovillosus", "klassi": "klaasi", "pentalore": "pentaloris", "phsycadelicus": "psychedelicus",
    "psychadelicus": "psychedelicus", "fuego": "fuego", "atrichromatus": "atrichomatus", "bohemi": "boehmei",
    "boehmi": "boehmei", "versilcolor": "versicolor", "blondii": "blondi", "seemani": "seemanni",
    "victorii": "victori", "sazmai": "sazimai", "lividum": "lividus", "hati": "hatihati",
"cyaneopubescens": "cyaneopubescens", "vagan": "vagans",
}
SPECIES_FIX = {
    # World Spider Catalog: Smith, Daniel & Vignaud 2026 moved these to Melopoeus
    **{f"{g} {e}": f"melopoeus {e}" for g in ("haplopelma", "cyriopagopus", "melopoeus")
       for e in ("albostriatus", "hainanus", "lividus", "longipes", "minax", "schmidti", "vonwirthi")},
    # WSC: Acuña et al. 2025 restored Selenobrachys
    "orphnaecus philippinus": "selenobrachys philippinus",
    "euathlus fuego": "euathlus sp. fuego",
    "brachypelma albopilosus": "tliltocatl albopilosus",
    "brachypelma vagans": "tliltocatl vagans",
    "avicularia versicolor": "caribena versicolor",
    "nhandu chromatus": "vitalius chromatus",
    "pterinopelma sazimai": "lasiocyano sazimai",
    "brachypelma smithi": "brachypelma hamorii",
    # WSC: Sherwood et al. 2025 moved T. lagunas to the new genus Warmiru
    "thrixopelma lagunas": "warmiru lagunas",
    "phormingochilus sp. rufus": "aspinochilus rufus", "phormingochilus rufus": "aspinochilus rufus",
    "orphnaecus dichromata": "chilocosmia dichromata",
    # WSC: Müller et al. 2024 described hobby "Cyriopagopus sp. hati hati" as Phormingochilus hatihati
    **{f"{g} {e}": "phormingochilus hatihati" for g in ("cyriopagopus", "phormingochilus", "omothymus")
       for e in ("sp. hati hati", "sp. hatihati", "sp. hati", "hati hati", "hatihati", "hati")},
    "pseudhapalopus sp. colom": "pseudhapalopus sp. colombia",
    # common names some shops print in the Latin slot
    "cyriopagopus bach": "cyriopagopus sp. bach ma",
    "pseudhapalopus columbia": "pseudhapalopus sp. colombia", "thyene jumping": "thyene sp.",
    "trinidad olive": "neoholothele incei", "trinidad chevron": "psalmopoeus cambridgei",
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
        if nxt.startswith(("\"", "“")):  # sp. "Locality Words" -> the whole quoted part
            for tok in tokens[i + 1:i + 5]:
                rest.append(tok.strip("\"“”'’.,()").lower())
                if re.search(r"[\"”]", tok[1:] if tok is nxt else tok):
                    break
            rest = [w for w in rest if w]
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
        if nxt.lower() in ("cf", "aff") and i + 2 < len(tokens) and re.match(r"^[a-z]{4,}$", tokens[i + 2].strip(".,")):
            return normalise(f"{tok.lower()} {tokens[i + 2].strip('.,').lower()}")
        if nxt.lower() == "sp" or (re.match(r"^[a-z]{4,}$", nxt) and LATIN_END.search(nxt)
                                   and not STOP.match(nxt)):
            ep = _epithet_after(tokens, i + 1)
            if ep:
                return normalise(f"{tok.lower()} {ep}")
    return None


# Abbreviated names written with an old genus initial: (initial, epithet) -> current species.
ABBREV = {
    ("b", "smithi"): "brachypelma hamorii", ("p", "sazimai"): "lasiocyano sazimai",
    ("c", "minax"): "melopoeus minax", ("c", "lividus"): "melopoeus lividus",
    ("h", "lividus"): "melopoeus lividus", ("p", "striata"): "poecilotheria striata",
    ("c", "sanderi"): "ceratogyrus sanderi", ("o", "schioedtei"): "omothymus schioedtei",
    ("b", "cabocla"): "bumba cabocla", ("p", "vespertinus"): "pamphobeteus vespertinus",
    ("t", "epicureanum"): "tliltocatl epicureanus", ("t", "epicureanus"): "tliltocatl epicureanus",
    ("t", "kahlenbergeri"): "tliltocatl kahlenbergeri", ("t", "cupreus"): "tapinauchenius cupreus",
    ("t", "violceus"): "tapinauchenius violaceus", ("t", "violaceus"): "tapinauchenius violaceus",
    ("n", "panamanus"): "neischnocolus panamanus", ("t", "lagunas"): "warmiru lagunas",
    ("t", "iagunas"): "warmiru lagunas", ("w", "lagunas"): "warmiru lagunas",
    ("t", "angustum"): "sericopelma angustum", ("s", "angustum"): "sericopelma angustum",
    ("c", "schmardae"): "cyclosternum schmardae", ("n", "incei"): "neoholothele incei",
    ("p", "cambridgei"): "psalmopoeus cambridgei", ("d", "sanguinea"): "diplura sanguinea",
}

# "O. sp. cebu" style: (initial, locality letters only) -> key, for names no other shop spells out
SP_ABBREV = {
    ("o", "cebu"): "orphnaecus sp. cebu", ("p", "blue"): "pseudhapalopus sp. blue",
    ("h", "columbialongform"): "hapalopus sp. colombia large", ("h", "colombialongform"): "hapalopus sp. colombia large",
    ("n", "panama"): "neischnocolus sp. panama", ("c", "hatihati"): "phormingochilus hatihati", ("p", "hatihati"): "phormingochilus hatihati",
    ("p", "rufus"): "aspinochilus rufus", ("c", "nepal"): "chilobrachys sp. nepal",
}

COLOUR_FORMS = ("phan cay",)

# Listings that give only a common name (or a garbled Latin one)
NAME_ONLY = [
    (re.compile(r"^yellow (bottle blue|blue bottle)\b", re.I), "pseudhapalopus sp. colombia"),
    (re.compile(r"neosteno\w*\W+french guiana", re.I), "neostenotarsus sp. french guiana"),
    (re.compile(r"\bN\.\s*suriname\b"), "neostenotarsus sp. suriname"),
    (re.compile(r"\bdecorated velvet spider\b", re.I), "paradonea sp. limpopo"),
]

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


def _one_edit(a: str, b: str) -> bool:
    """True if a and b differ by exactly one insert, delete or substitution."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def group_of(it: dict) -> str:
    """tarantula / jumping / other (true spiders and non-tarantula mygalomorphs)."""
    g = (it.get("species") or "").split(" ")[0]
    if g in JUMPING_GENERA:
        return "jumping"
    if g in OTHER_SPIDER_GENERA:
        return "other"
    if g in KNOWN_GENERA:
        return "tarantula"
    text = f"{it.get('name', '')} {it.get('hint', '')}".lower()
    if re.search(r"jumping|salticid|\bjumper", text):
        return "jumping"
    if re.search(r"other spiders|true spiders|araneomorph|widow|huntsman|orb ?weaver|wolf spider|fishing spider|true spider|trapdoor|"
                 r"funnel|crab spider|lynx|net[- ]?casting|velvet spider|wandering|purse ?web|hourglass", text):
        return "other"
    if re.search(r"tarantula|theraphosid|bird ?eat", text):
        return "tarantula"
    if re.search(r"tree spider|earth ?tiger|baboon|pink ?toe|starburst|bird ?eater|tree tiger", text):
        return "tarantula"  # hobby names that only ever mean tarantulas
    if re.search(r"\bspider", it.get("name", ""), re.I):
        return "other"  # unknown genus called a "spider" rather than a tarantula
    return "tarantula"


def stage_of(text: str) -> str:
    t = text.lower()
    if re.search(r"sub[\s-]?adult|semi[\s-]?adult|\bs/a\b|\(sa\)|\bsa[fm]\b", t):
        return "subadult"
    if re.search(r"spiderling|\bslings?\b|\bslg\b", t):
        return "sling"
    if re.search(r"juvenile|juvie|\bjuv\b|\bjuvs?\b", t):
        return "juvenile"
    if re.search(r"\badult\b|\bmature\b|\b(af|am|mm)\b", t):
        return "adult"
    m = re.search(r"size\s*:\s*(\d+(?:\.\d+)?)\s*(?:[-–=]|to)?\s*(\d+(?:\.\d+)?)?\s*cm", t)
    if m:  # an explicit "Size: 2-3cm" wins over any other numbers
        t = m.group(0)
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
    if re.search(r"\bfemales?\b|♀|\b(af|saf|jf)\b|\b0\.1\b", t):
        return "female"
    if re.search(r"\bmales?\b|♂|\b(am|mm|sam|jm)\b|\b1\.0\b", t):
        return "male"
    return ""


def annotate(items: dict) -> None:
    """Add species, species_name, common, stage and sex to every item in place."""
    live = list(items.values())
    genera = set(KNOWN_GENERA) | JUMPING_GENERA | OTHER_SPIDER_GENERA

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

    # Second look now that genera seen in other shops are known (name, then URL slug).
    for it in live:
        if not it["species"]:
            it["species"] = find_binomial(it["name"], genera)
        if not it["species"]:
            slug = unquote(urlparse(it.get("url", "")).path.rstrip("/").split("/")[-1])
            key = find_binomial(re.sub(r"[-_]+", " ", slug), genera)
            if key and key.split()[0] in genera:
                it["species"] = key

    # Abbreviated genus, e.g. "T. kahlenbergeri" -> tliltocatl kahlenbergeri.
    by_epithet = defaultdict(set)
    for it in live:
        if it["species"] and not it["species"].split(" ", 1)[1].startswith("sp"):
            g, ep = it["species"].split(" ", 1)
            by_epithet[ep].add(g)
    sp_keys = {}
    for it in live:
        if it["species"] and " sp. " in it["species"]:
            g, loc = it["species"].split(" sp. ", 1)
            sp_keys.setdefault((g[0], re.sub(r"[^a-z]", "", loc)), set()).add(it["species"])
    # Colour forms sold as different animals ("Phan Cay Red" vs "Phan Cay Blue")
    for it in live:
        sp = it["species"] or ""
        for loc in COLOUR_FORMS:
            if sp.endswith("sp. " + loc):
                m = re.search(loc.replace(" ", r"\W*") + r"\W*(red|blue|black|gold|green)\b", it["name"], re.I)
                if m:
                    it["species"] = f"{sp} {m.group(1).lower()}"
    for it in live:
        if not it["species"]:
            for rx, key in NAME_ONLY:
                if rx.search(it["name"]):
                    it["species"] = key
                    break
        if it["species"]:
            continue
        # "C. sp. Hati hati" / "O.sp. cebu": genus initial + locality matching a known sp. key
        m = re.search(r"\b([A-Z])\.\s*sp\.?,?\s*([A-Za-z][A-Za-z .'-]{2,30}?)\s*,", it["name"] + ",")
        if m:
            loc = re.sub(r"[^a-z]", "", m.group(2).lower())
            if (m.group(1).lower(), loc) in SP_ABBREV:
                it["species"] = SP_ABBREV[(m.group(1).lower(), loc)]
                continue
            for (ini, l), ks in sp_keys.items():
                if ini == m.group(1).lower() and (l == loc or _one_edit(l, loc)) and len(ks) == 1:
                    it["species"] = next(iter(ks))
                    break
            continue
        # "B. bohemi" / "A. gniculata": genus initial + epithet, allowing one typo
        m = re.search(r"(?<![A-Za-z])([A-Z])(?![A-Za-z])[.,]?\s*([A-Za-z]{4,})\s*,", it["name"] + ",") or \
            re.search(r"(?<![A-Za-z])([A-Z])\.\s*([A-Za-z]{4,})", it["name"])
        if m:
            ep = EPITHET_FIX.get(m.group(2).lower(), m.group(2).lower())
            if (m.group(1).lower(), ep) in ABBREV:
                it["species"] = ABBREV[(m.group(1).lower(), ep)]
                continue
            cands = {f"{g} {ep}" for g in by_epithet.get(ep, ()) if g[0] == m.group(1).lower()}
            if not cands:
                cands = {f"{g} {e}" for e, gs in by_epithet.items() for g in gs
                         if g[0] == m.group(1).lower() and len(e) >= 6 and _one_edit(e, ep)}
            if len(cands) == 1:
                it["species"] = normalise(next(iter(cands)))

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
        for cand in (it["name"], it["name"].split(",")[0], it["name"].split(" - ")[0]):
            plain = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z' ]", " ", SIZE_WORDS.sub(" ", cand))).strip().lower()
            if plain in by_common:
                it["species"] = by_common[plain].most_common(1)[0][0]
                break

    # Spelling slips between shops ("pingungensis" vs "pingtungensis"): merge keys in the
    # same genus that are one letter apart, keeping the spelling most shops use.
    counts = Counter(it["species"] for it in live if it["species"])
    keys = sorted(counts)
    alias = {}
    for i, a in enumerate(keys):
        ga, ea = a.split(" ", 1)
        if ea.startswith("sp") or len(ea) < 8:
            continue
        for b in keys[i + 1:]:
            gb, eb = b.split(" ", 1)
            if gb != ga:
                break
            if not eb.startswith("sp") and _one_edit(ea, eb):
                keep, drop = (a, b) if counts[a] >= counts[b] else (b, a)
                alias[drop] = keep
    for it in live:
        if it["species"] in alias:
            it["species"] = alias[it["species"]]

    for it in live:
        it["group"] = group_of(it)
        it["lifestyle"] = lifestyle_of(it)
    for it in live:
        key = it["species"]
        it["species_name"] = display_name(key) if key else it["name"]
        it["common"] = commons[key].most_common(1)[0][0] if key and commons.get(key) else ""
        if it.get("hint"):
            it["hint"] = it["hint"][:240]

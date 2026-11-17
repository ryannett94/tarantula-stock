"""How each spider lives: arboreal, terrestrial, fossorial (burrowing) or trapdoor.

Based on hobby/husbandry consensus by genus, with species-level exceptions where a
genus is mixed. A lifestyle printed on the shop's own listing (e.g. "LIFESTYLE:
Arboreal") wins over this table. Some spiders get two tags, e.g. opportunistic
burrowers are "terrestrial" + "fossorial".
"""
from __future__ import annotations

import re

A, T, F, D = "arboreal", "terrestrial", "fossorial", "trapdoor"

GENUS = {
    # --- New World arboreals
    "avicularia": [A], "caribena": [A], "ybyrapora": [A], "typhochlaena": [A], "iridopelma": [A],
    "pachistopelma": [A], "amazonius": [A], "antillena": [A], "psalmopoeus": [A], "tapinauchenius": [A],
    "ephebopus": [F], "viridasius": [A],
    # --- Old World arboreals
    "poecilotheria": [A], "omothymus": [A], "phormingochilus": [A], "lampropelma": [A],
    "heteroscodra": [A], "stromatopelma": [A], "encyocratella": [A], "pseudoclamoris": [A],
    # --- Old World burrowers
    "haplopelma": [F], "melopoeus": [F], "cyriopagopus": [F], "ornithoctonus": [F],
    "ornithoctoninae": [F], "chilobrachys": [F], "selenocosmia": [F], "selenobrachys": [F],
    "orphnaecus": [F], "lyrognathus": [F], "coremiocnemis": [F], "phlogiellus": [F],
    "haploclastus": [F], "thrigmopoeus": [F], "annandaliella": [F], "birupes": [F],
    "hysterocrates": [F], "pelinobius": [F], "ceratogyrus": [F], "augacephalus": [F],
    "eucratoscelus": [F], "harpactira": [T, F], "harpactirella": [F], "idiothele": [F, D],
    "pterinochilus": [T, F], "monocentropus": [T, F], "heterothele": [T, F], "chaetopelma": [F],
    "ischnocolus": [T], "selenotholus": [F], "selenotypus": [F], "phlogius": [F],
    # --- New World terrestrials
    "acanthoscurria": [T], "aphonopelma": [T], "brachypelma": [T], "tliltocatl": [T], "davus": [T],
    "grammostola": [T], "euathlus": [T], "homoeomma": [T], "hapalopus": [T], "cyriocosmus": [T, F],
    "chromatopelma": [T], "lasiodora": [T], "lasiodorides": [T], "nhandu": [T], "vitalius": [T],
    "pamphobeteus": [T], "xenesthis": [T], "theraphosa": [T], "megaphobema": [T], "phormictopus": [T],
    "thrixopelma": [T], "pterinopelma": [T], "lasiocyano": [T], "eupalaestrus": [T], "proshapalopus": [T],
    "bumba": [T], "cotztetlana": [T], "kochiana": [T], "pseudhapalopus": [T], "dolichothele": [T],
    "neoholothele": [T], "holothele": [T], "sericopelma": [T], "citharacanthus": [T], "cyrtopholis": [T],
    "crassicrus": [T, F], "bonnetina": [T, F], "plesiopelma": [T], "magulla": [T], "catumiri": [T],
    "tmesiphantes": [T], "nesipelma": [T], "cyclosternum": [T], "metriopelma": [T], "hemirrhagus": [T],
    "kankuamo": [T], "umbyquyra": [T], "spinosatibiapalpus": [T], "euthycaelus": [T],
    "hapalotremus": [T], "phrixotrichus": [T], "abdomegaphobema": [T], "sickius": [T], "guyruita": [T],
    "aenigmarachne": [T], "reversopelma": [T], "yanomamius": [T], "munduruku": [T], "cardiopelma": [T],
    "ami": [T], "anqasha": [T], "acanthopelma": [T], "neischnocolus": [T], "warmiru": [T],
    "antikuna": [T], "uropelma": [T], "theraphosinae": [T],
    "haplocosmia": [F], "psednocnemis": [F], "brachionopus": [F], "cilantica": [F],
    # --- jumping spiders: climbers, live up high
    **{g: [A] for g in """phidippus hyllus evarcha salticus plexippus menemerus marpissa thiania epeus
       colonus paraphidippus platycryptus carrhotus telamonia cosmophasis maratus habronattus portia
       myrmarachne siler heliophanus pellenes saitis servaea ptocasius philaeus euophrys attulus sitticus
       hasarius chrysilla irura bianor rhene harmochirus hentzia pelegrina eris anasaitis lyssomanes
       asemonea holoplatys cytaea maevia zygoballus sassacus thyene hypoblemum ocrisiona opisthoncus
       mopsus simaetha tauala artabrus""".split()},
    # --- true & other spiders
    "heteropoda": [A], "holconia": [A], "isopeda": [A], "neosparassus": [A], "delena": [A],
    "barylestis": [A], "pandercetes": [A], "olios": [A], "micrommata": [A], "eusparassus": [T],
    "nephila": [A], "trichonephila": [A], "nephilingis": [A], "argiope": [A], "araneus": [A],
    "gasteracantha": [A], "cyrtophora": [A], "caerostris": [A], "poltys": [A], "cyclosa": [A],
    "deinopis": [A], "oxyopes": [A], "peucetia": [A], "thomisus": [A], "misumena": [A],
    "phrynarachne": [A], "hersilia": [A], "tibellus": [A], "stegodyphus": [A], "gandanameno": [A],
    "dresserus": [F], "eresus": [F], "psechrus": [T], "zoropsis": [T],
    "hogna": [T, F], "lycosa": [T, F], "geolycosa": [F], "tigrosa": [T, F], "rabidosa": [T],
    "pardosa": [T], "hippasa": [T], "sosippus": [T], "dolomedes": [T], "thalassius": [T], "nilus": [T],
    "pisaura": [T], "cupiennius": [A], "phoneutria": [T], "ctenus": [T], "africactenus": [T],
    "piloctenus": [T], "ancylometes": [T], "kukulcania": [T], "filistata": [T], "sicarius": [T, F],
    "hexophthalma": [T, F], "loxosceles": [T], "scytodes": [T], "latrodectus": [T], "steatoda": [T],
    "parasteatoda": [T], "pholcus": [T], "tegenaria": [T], "eratigena": [T], "agelena": [T],
    "segestria": [T], "dysdera": [T], "diguetia": [T], "tengella": [T],
    # non-tarantula mygalomorphs
    "linothele": [T], "ischnothele": [T], "euagrus": [T], "trechona": [T], "macrothele": [T, F],
    "porrhothele": [T, F], "orientothele": [T], "atypus": [F], "sphodros": [F], "calommata": [F],
    "liphistius": [D], "luthela": [D], "cyclocosmia": [D], "ummidia": [D], "cteniza": [D],
    "nemesia": [D], "idiops": [D], "gorgyrella": [D], "heligmomerus": [D], "bothriocyrtum": [D],
    "aptostichus": [D], "antrodiaetus": [D], "conothele": [D], "latouchia": [D], "bolostromus": [D],
    "barychelidae": [D],
}

SPECIES = {
    # mixed genera: species that differ from their genus default
    "pterinochilus murinus": [T, F],
    "monocentropus balfouri": [T, F],
    "chilobrachys fimbriatus": [F], "chilobrachys dyscolus": [F],
    "cyriopagopus sp. hati hati": [F], "cyriopagopus sp. hatihati": [F],
    "phormingochilus sp. hati hati": [A], "phormingochilus sp. hatihati": [A],
    "orphnaecus sp. blue panay": [F],
    "theraphosa blondi": [T, F], "theraphosa stirmi": [T, F], "theraphosa apophysis": [T, F],
    "xenesthis immanis": [T, F],
    "aphonopelma seemanni": [T, F], "aphonopelma hentzi": [T, F],
    "ceratogyrus darlingi": [F], "ceratogyrus marshalli": [F],
    "heteroscodra maculata": [A],
    "psalmopoeus cambridgei": [A], "psalmopoeus irminia": [A],
    "harpactira pulchripes": [T, F],
    "ephebopus cyanognathus": [F], "ephebopus murinus": [F], "ephebopus uatuman": [F],
    "hapalopus formosus": [T], "cyriocosmus elegans": [T, F],
    "lasiodora parahybana": [T], "grammostola pulchra": [T], "nhandu chromatus": [T],
}

SHOP_WORDS = [
    (re.compile(r"trap[\s-]?door", re.I), D),
    (re.compile(r"semi[\s-]?arboreal|arboreal|tree[\s-]?dwell", re.I), A),
    (re.compile(r"fossorial|obligate burrow|burrower|burrowing", re.I), F),
    (re.compile(r"terrestrial|ground[\s-]?dwell", re.I), T),
]


def lifestyle_of(it: dict) -> list[str]:
    key = it.get("species") or ""
    # 1. What the shop itself says ("LIFESTYLE: Arboreal", "Type: Fossorial")
    hint = it.get("hint") or ""
    m = re.search(r"(lifestyle|type|habit(at)?)\s*:?\s*([A-Za-z /,-]{4,40})", hint, re.I)
    if m:
        tags = [tag for rx, tag in SHOP_WORDS if rx.search(m.group(3))]
        if tags:
            return sorted(set(tags), key=[A, T, F, D].index)
    # 2. Species exceptions, then genus
    if key in SPECIES:
        return SPECIES[key]
    genus = key.split(" ")[0] if key else ""
    if genus in GENUS:
        return GENUS[genus]
    # 3. Words in the listing name/description ("Trapdoor Spider", "burrowing")
    text = f"{it.get('name', '')} {hint}"
    tags = [tag for rx, tag in SHOP_WORDS if rx.search(text)]
    return sorted(set(tags), key=[A, T, F, D].index)

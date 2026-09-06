#!/usr/bin/env python3
"""
Bouwt een geoptimaliseerde Google Merchant Center kledingfeed voor lou-marie.be.

Odoo's eigen gmc.xml levert alleen de basisvelden en propt maat in een
`product_detail`-blok dat Google niet als `size` leest. Dit script leest die feed,
verrijkt hem met de kledingattributen die Google voor Belgie verwacht, en schrijft
een nieuwe feed weg die je in de repo kan committen.

Uitgangspunt: NIETS VERZINNEN. Een attribuut wordt alleen weggeschreven als het
aantoonbaar uit de titel, de omschrijving of de productpagina komt. Wat niet
gevonden wordt, blijft weg -- een ontbrekend veld is beter dan een fout veld.

Gebruik:
    python3 tools/build_gmc_feed.py                 # volledige build incl. prijzen
    python3 tools/build_gmc_feed.py --no-prices     # sla het scrapen van compare-prijzen over
    python3 tools/build_gmc_feed.py --report-only   # bouw niets, toon alleen dekking

Alleen standaardbibliotheek, zodat het ook in GitHub Actions draait zonder pip install.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

# ---------------------------------------------------------------------------
# CONFIGURATIE
# ---------------------------------------------------------------------------

# De bron-feed bevat een access_token. Deze repo is openbaar, dus die staat hier
# niet in de code. Zet hem in de omgeving:
#
#   lokaal   export GMC_SOURCE_FEED="https://www.lou-marie.be/gmc.xml?feed_id=7&access_token=..."
#   Actions  Settings -> Secrets and variables -> Actions -> GMC_SOURCE_FEED
#
SOURCE_FEED = os.environ.get("GMC_SOURCE_FEED", "")

OUTPUT_PATH = "gmc-feed.xml"
CACHE_PATH = "tools/.price-cache.json"

FEED_TITLE = "Lou-Marie fashion | Tijdloze & betaalbare dameskleding"
FEED_LINK = "https://www.lou-marie.be/nl"
FEED_DESCRIPTION = (
    "Stijlvolle en comfortabele kleding voor vrouwen die er graag vrouwelijk "
    "en verzorgd uitzien, zonder blindelings de trends te volgen."
)

# Vaststaande waarden. Deze zijn bevestigd door de eigenaar, geen gok.
BRAND = ""               # bewust leeg: geen eigen merk. Vul in als dat verandert.
GENDER = "female"        # de hele winkel is dameskleding
AGE_GROUP = "adult"
CONDITION = "new"

HTTP_TIMEOUT = 30
SCRAPE_DELAY = 0.4       # seconden tussen productpagina's, wees beleefd
USER_AGENT = "lou-marie-feed-builder/1.0 (+https://github.com/andriesss/lou-marie.be)"

# --- Google producttaxonomie -----------------------------------------------
# Odoo's websitecategorie -> officiele Google-categorie.
# Categorieen die hier niet in staan, krijgen geen google_product_category.
# De officiele lijst wordt bij elke build opgehaald en gecontroleerd.
CATEGORY_MAP = {
    "Jurken": "Apparel & Accessories > Clothing > Dresses",
    "Blouses en tops": "Apparel & Accessories > Clothing > Shirts & Tops",
    "T-shirts": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Truien en vesten": "Apparel & Accessories > Clothing > Shirts & Tops",
    "Jassen en blazers": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
    "Sjaals": "Apparel & Accessories > Clothing Accessories > Scarves & Shawls",
}

# "Broeken, shorts en rokken" bevat drie verschillende Google-categorieen.
# Die splitsen we op woorden in de titel, van specifiek naar algemeen.
TROUSER_SPLIT = [
    ("rok", "Apparel & Accessories > Clothing > Skirts"),
    ("short", "Apparel & Accessories > Clothing > Shorts"),
    ("bermuda", "Apparel & Accessories > Clothing > Shorts"),
]
TROUSER_DEFAULT = "Apparel & Accessories > Clothing > Pants"
TROUSER_CATEGORY = "Broeken, shorts en rokken"

TAXONOMY_URL = "https://www.google.com/basepages/producttype/taxonomy.en-US.txt"

# Websitecategorieen die geen producttype zijn maar een verkooplabel. Ze horen
# niet in g:product_type thuis; ze worden custom labels zodat de informatie
# bruikbaar blijft voor campagnesegmentatie.
MERCH_LABELS = {"SALE", "NIEUW"}

# --- Woordenlijsten ---------------------------------------------------------
# Nederlands verbuigt bijvoeglijke naamwoorden ("blauw" -> "blauwe", "goud" ->
# "gouden", "grijs" -> "grijze"), dus elke kleur krijgt zijn eigen varianten.
# Sleutel = de waarde die in de feed komt, lijst = wat we in de tekst zoeken.
# Alleen kleuren die in deze catalogus voorkomen of realistisch zijn.
COLORS = {
    "gebroken wit": ["gebroken wit", "gebroken witte"],
    "donkerblauw":  ["donkerblauw", "donkerblauwe"],
    "lichtblauw":   ["lichtblauw", "lichtblauwe"],
    "marineblauw":  ["marineblauw", "marineblauwe", "marine"],
    "donkergroen":  ["donkergroen", "donkergroene"],
    "lichtgroen":   ["lichtgroen", "lichtgroene"],
    "olijfgroen":   ["olijfgroen", "olijfgroene", "olijf"],
    "donkerbruin":  ["donkerbruin", "donkerbruine"],
    "donkergrijs":  ["donkergrijs", "donkergrijze"],
    "lichtgrijs":   ["lichtgrijs", "lichtgrijze"],
    "oudroze":      ["oudroze"],
    "lichtroze":    ["lichtroze"],
    "terracotta":   ["terracotta"],
    "bordeaux":     ["bordeaux"],
    "antraciet":    ["antraciet"],
    "turquoise":    ["turquoise", "turkoois", "turkooizen"],
    "camel":        ["camel"],
    "taupe":        ["taupe"],
    "kaki":         ["kaki"],
    "ecru":         ["ecru"],
    "creme":        ["creme", "cr\u00e8me", "cremekleurig", "cr\u00e8mekleurig"],
    "beige":        ["beige"],
    "koraal":       ["koraal", "koraalrood"],
    "zalm":         ["zalm", "zalmroze"],
    "mosterd":      ["mosterd", "mosterdgeel"],
    "brique":       ["brique"],
    "lila":         ["lila"],
    "mauve":        ["mauve"],
    "zwart":        ["zwart", "zwarte"],
    "wit":          ["wit", "witte"],
    "grijs":        ["grijs", "grijze"],
    "blauw":        ["blauw", "blauwe"],
    "groen":        ["groen", "groene"],
    "rood":         ["rood", "rode"],
    "roze":         ["roze"],
    "geel":         ["geel", "gele"],
    "bruin":        ["bruin", "bruine"],
    "paars":        ["paars", "paarse"],
    "oranje":       ["oranje"],
    "goud":         ["goud", "gouden", "goudkleurig", "goudkleurige"],
    "zilver":       ["zilver", "zilveren", "zilverkleurig", "zilverkleurige"],
}

# Materialen. "gebreid" en "denim" zijn in modefeeds gangbare materiaalwaarden.
# Bewust NIET opgenomen: "stretch" (een eigenschap, geen materiaal).
MATERIALS = {
    "imitatieleer": ["imitatieleer", "imitatieleren"],
    "suedine":      ["suedine", "su\u00e8dine", "suedinelook", "su\u00e8dinelook"],
    "ribfluweel":   ["ribfluweel", "corduroy"],
    "polyester":    ["polyester"],
    "viscose":      ["viscose"],
    "katoen":       ["katoen", "katoenen"],
    "linnen":       ["linnen"],
    "satijn":       ["satijn", "satijnen"],
    "chiffon":      ["chiffon"],
    "tricot":       ["tricot"],
    "denim":        ["denim", "jeansstof"],
    "lurex":        ["lurex"],
    "gebreid":      ["gebreid", "gebreide"],
    "kant":         ["kant", "kanten"],
    "wol":          ["wol", "wollen"],
    "tweed":        ["tweed"],
    "leer":         ["leer", "leren"],
}

PATTERNS = {
    "luipaardprint": ["luipaardprint", "luipaard"],
    "bloemenprint":  ["bloemenprint", "bloemenmotief"],
    "dierenprint":   ["dierenprint"],
    "palmprint":     ["palmprint"],
    "gestreept":     ["gestreept", "gestreepte", "strepen"],
    "geruit":        ["geruit", "geruite", "ruitjes", "ruitjesprint"],
    "stippen":       ["stippen", "bolletjesprint", "polkadot"],
}

# --- Custom labels voor campagnesegmentatie --------------------------------
PRICE_BUCKETS = [(25, "tot 25"), (40, "25 tot 40"), (55, "40 tot 55")]
PRICE_BUCKET_TOP = "vanaf 55"


# ---------------------------------------------------------------------------
# HULPFUNCTIES
# ---------------------------------------------------------------------------

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def tag(block: str, name: str) -> str:
    m = re.search(rf"<g:{name}>(.*?)</g:{name}>", block, re.S)
    return html.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""


def tags(block: str, name: str) -> list[str]:
    return [
        html.unescape(re.sub(r"\s+", " ", v).strip())
        for v in re.findall(rf"<g:{name}>(.*?)</g:{name}>", block, re.S)
    ]


def to_float(text: str) -> float | None:
    """'39,95 EUR' en '39.95' -> 39.95"""
    m = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(" ", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def find_term(vocab: dict, *haystacks: str) -> str:
    """
    Zoekt de vocabulaire-waarde die het VROEGST in de tekst staat.

    Positie wint van lengte, want het Nederlands zet de kleur van het kledingstuk
    vooraan: in "Donkerblauwe blazer met gouden knopen" is het kledingstuk
    donkerblauw en zijn alleen de knopen goud. Bij gelijke positie wint de
    langste match, zodat "donkergroen" niet als "groen" wordt gelezen.

    Haystacks worden op volgorde geprobeerd; pas als de titel niets oplevert,
    kijken we in de omschrijving.
    """
    for hay in haystacks:
        if not hay:
            continue
        low = hay.lower()
        best = None
        for canonical, variants in vocab.items():
            for variant in variants:
                m = re.search(rf"\b{re.escape(variant)}\b", low)
                if m and (best is None or (m.start(), -len(variant)) < best[0]):
                    best = ((m.start(), -len(variant)), canonical)
        if best:
            return best[1]
    return ""


# ---------------------------------------------------------------------------
# AFLEIDINGEN
# ---------------------------------------------------------------------------

def derive_color(title: str, description: str) -> str:
    """
    Titels volgen sinds 2026-09 het patroon 'Type kenmerk, kleur (maat)'.
    Eerst dat patroon proberen, anders een woordenlijst-scan over titel en tekst.
    """
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    if "," in stripped:
        tail = stripped.rsplit(",", 1)[1].strip().lower()
        for canonical, variants in COLORS.items():
            if tail in variants:
                return canonical
    return find_term(COLORS, title, description)


def derive_size(details: list[tuple[str, str]], title: str) -> str:
    for name, value in details:
        if name.strip().lower() == "maat" and value.strip():
            size = value.strip()
            return "one size" if size.upper() == "ONE SIZE" else size
    m = re.search(r"\(([^)]+)\)\s*$", title)
    return m.group(1).strip() if m else ""


def derive_category(product_types: list[str], title: str) -> str:
    real = [p for p in product_types if p not in MERCH_LABELS]
    for pt in real:
        if pt == TROUSER_CATEGORY:
            low = title.lower()
            for word, cat in TROUSER_SPLIT:
                if word in low:
                    return cat
            return TROUSER_DEFAULT
        if pt in CATEGORY_MAP:
            return CATEGORY_MAP[pt]
    return ""


def price_bucket(value: float | None) -> str:
    if value is None:
        return ""
    for limit, label in PRICE_BUCKETS:
        if value < limit:
            return label
    return PRICE_BUCKET_TOP


# ---------------------------------------------------------------------------
# COMPARE-PRIJS VAN DE PRODUCTPAGINA
# ---------------------------------------------------------------------------

COMPARE_RE = re.compile(
    r'<del[^>]*oe_compare_list_price[^>]*>(.*?)</del>', re.S | re.I
)
CURRENCY_RE = re.compile(r'oe_currency_value"[^>]*>([\d.,]+)')


def scrape_compare_price(url: str, cache: dict) -> float | None:
    """
    Odoo toont een doorstreepprijs als 'Vergelijkingsprijs' is ingevuld:
        <del class="... oe_compare_list_price"> ... 39,95 EUR </del>
    Staat die er niet, dan is er geen aanbieding en geven we None terug.
    """
    if url in cache:
        return cache[url]
    result = None
    try:
        page = fetch(url)
        m = COMPARE_RE.search(page)
        if m:
            v = CURRENCY_RE.search(m.group(1))
            if v:
                result = to_float(v.group(1))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  ! kon {url} niet ophalen: {exc}", file=sys.stderr)
        return None
    cache[url] = result
    time.sleep(SCRAPE_DELAY)
    return result


# ---------------------------------------------------------------------------
# TAXONOMIECONTROLE
# ---------------------------------------------------------------------------

def load_taxonomy() -> set[str] | None:
    try:
        text = fetch(TAXONOMY_URL)
    except Exception as exc:
        print(f"  ! taxonomie niet opgehaald ({exc}); controle overgeslagen", file=sys.stderr)
        return None
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }


# ---------------------------------------------------------------------------
# BOUWEN
# ---------------------------------------------------------------------------

def el(name: str, value) -> str:
    return f"      <g:{name}>{escape(str(value))}</g:{name}>\n"


def build(items: list[dict]) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">\n',
        "  <channel>\n",
        f"    <title>{escape(FEED_TITLE)}</title>\n",
        f"    <link>{escape(FEED_LINK)}</link>\n",
        f"    <description>{escape(FEED_DESCRIPTION)}</description>\n",
    ]
    for it in items:
        out.append("    <item>\n")
        out.append(el("id", it["id"]))
        out.append(el("title", it["title"]))
        out.append(el("description", it["description"]))
        out.append(el("link", it["link"]))
        out.append(el("image_link", it["image_link"]))
        for extra in it["additional_image_link"][:10]:
            out.append(el("additional_image_link", extra))
        out.append(el("availability", it["availability"]))
        out.append(el("price", it["price"]))
        if it.get("sale_price"):
            out.append(el("sale_price", it["sale_price"]))
        if BRAND:
            out.append(el("brand", BRAND))
        out.append(el("condition", CONDITION))
        out.append(el("gender", GENDER))
        out.append(el("age_group", AGE_GROUP))
        for field in ("google_product_category", "color", "size", "size_system",
                      "material", "pattern", "item_group_id"):
            if it.get(field):
                out.append(el(field, it[field]))
        out.append(el("identifier_exists", it["identifier_exists"] or "no"))
        for pt in it["product_type"]:
            out.append(el("product_type", pt))
        for idx, label in enumerate(it["custom_labels"]):
            if label:
                out.append(el(f"custom_label_{idx}", label))
        out.append("    </item>\n")
    out.append("  </channel>\n</rss>\n")
    return "".join(out)


def parse_source(xml: str) -> list[dict]:
    items = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        details = [
            (html.unescape(n.strip()), html.unescape(v.strip()))
            for n, v in re.findall(
                r"<g:attribute_name>(.*?)</g:attribute_name>\s*"
                r"<g:attribute_value>(.*?)</g:attribute_value>",
                block, re.S,
            )
        ]
        items.append({
            "id": tag(block, "id"),
            "title": tag(block, "title"),
            "description": tag(block, "description"),
            "link": tag(block, "link"),
            "image_link": tag(block, "image_link"),
            "additional_image_link": tags(block, "additional_image_link"),
            "availability": tag(block, "availability") or "in_stock",
            "price_raw": tag(block, "price"),
            "item_group_id": tag(block, "item_group_id"),
            "identifier_exists": tag(block, "identifier_exists"),
            "product_type": tags(block, "product_type"),
            "ads_label": tags(block, "custom_label_0"),
            "details": details,
        })
    return items


def enrich(items: list[dict], with_prices: bool, cache: dict) -> list[dict]:
    total = len(items)
    for n, it in enumerate(items, 1):
        title = it["title"].strip()
        it["title"] = title
        desc = it["description"]

        current = to_float(it["price_raw"])
        it["price"] = f"{current:.2f} EUR" if current is not None else it["price_raw"]

        if with_prices and it["link"]:
            print(f"  [{n}/{total}] {title[:52]}", file=sys.stderr)
            compare = scrape_compare_price(it["link"], cache)
            if compare and current and compare > current:
                it["price"] = f"{compare:.2f} EUR"
                it["sale_price"] = f"{current:.2f} EUR"

        it["color"] = derive_color(title, desc)
        size = derive_size(it["details"], title)
        it["size"] = size
        it["size_system"] = "EU" if size and size.isdigit() else ""
        it["material"] = find_term(MATERIALS, title, desc)
        it["pattern"] = find_term(PATTERNS, title, desc)
        it["google_product_category"] = derive_category(it["product_type"], title)

        all_types = it["product_type"]
        it["product_type"] = [p for p in all_types if p not in MERCH_LABELS]
        main_cat = it["product_type"][0] if it["product_type"] else ""
        it["custom_labels"] = [
            it["ads_label"][0] if it["ads_label"] else "",
            price_bucket(current),
            main_cat,
            "aanbieding" if it.get("sale_price") else "",
            "nieuw" if "NIEUW" in all_types else "",
        ]
    return items


def report(items: list[dict], taxonomy: set[str] | None) -> None:
    total = len(items)
    fields = ["color", "size", "size_system", "material", "pattern",
              "google_product_category", "sale_price"]
    print("\nDekking per veld")
    print("-" * 46)
    for f in fields:
        n = sum(1 for it in items if it.get(f))
        bar = "#" * round(n / total * 24) if total else ""
        print(f"  {f:<26} {n:>4}/{total}  {bar}")

    missing_color = [it for it in items if not it.get("color")]
    if missing_color:
        print(f"\nGeen kleur gevonden ({len(missing_color)}), vul handmatig aan:")
        for it in missing_color[:15]:
            print(f"  {it['id']:<5} {it['title'][:60]}")
        if len(missing_color) > 15:
            print(f"  ... en {len(missing_color) - 15} meer")

    no_cat = [it for it in items if not it.get("google_product_category")]
    if no_cat:
        cats = sorted({p for it in no_cat for p in it["product_type"]})
        print(f"\nGeen Google-categorie ({len(no_cat)} items). "
              f"Voeg toe aan CATEGORY_MAP: {', '.join(cats) or 'geen categorie in bron'}")

    if taxonomy:
        used = {it["google_product_category"] for it in items
                if it.get("google_product_category")}
        bad = sorted(c for c in used if c not in taxonomy)
        if bad:
            print("\n! Deze categorieen staan NIET in de officiele Google-taxonomie:")
            for c in bad:
                print(f"    {c}")
        else:
            print(f"\nAlle {len(used)} gebruikte categorieen komen voor in de "
                  f"officiele Google-taxonomie.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-prices", action="store_true",
                    help="sla het ophalen van doorstreepprijzen over (veel sneller)")
    ap.add_argument("--report-only", action="store_true",
                    help="toon alleen de dekking, schrijf geen bestand")
    ap.add_argument("--source", default=SOURCE_FEED, help="bron-feed URL")
    ap.add_argument("--out", default=OUTPUT_PATH, help="pad naar de uitvoerfeed")
    args = ap.parse_args()

    if not args.source:
        print(
            "Geen bron-feed. Zet GMC_SOURCE_FEED in je omgeving of geef --source mee.\n"
            "  export GMC_SOURCE_FEED='https://www.lou-marie.be/gmc.xml?feed_id=7&access_token=...'",
            file=sys.stderr,
        )
        return 1
    # token niet meelogen
    safe = re.sub(r"access_token=[^&]+", "access_token=***", args.source)
    print(f"Bron: {safe}", file=sys.stderr)
    source = fetch(args.source)
    items = parse_source(source)
    print(f"{len(items)} items ingelezen", file=sys.stderr)

    cache = {}
    if not args.no_prices and os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as fh:
            cache = json.load(fh)

    if not args.no_prices:
        print("Doorstreepprijzen ophalen van de productpagina's...", file=sys.stderr)

    items = enrich(items, with_prices=not args.no_prices, cache=cache)

    if not args.no_prices:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=1, sort_keys=True)

    taxonomy = load_taxonomy()
    report(items, taxonomy)

    if args.report_only:
        return 0

    xml = build(items)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(xml)
    print(f"\nGeschreven: {args.out} ({len(xml):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

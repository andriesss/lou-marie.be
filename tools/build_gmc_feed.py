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
import concurrent.futures
import html
import json
import os
import re
import sys
import threading
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
CACHE_MAX_AGE = 20 * 3600   # cache-items ouder dan 20 uur opnieuw ophalen

FEED_TITLE = "Lou-Marie fashion | Tijdloze & betaalbare dameskleding"
FEED_LINK = "https://www.lou-marie.be/nl"
FEED_DESCRIPTION = (
    "Stijlvolle en comfortabele kleding voor vrouwen die er graag vrouwelijk "
    "en verzorgd uitzien, zonder blindelings de trends te volgen."
)

# Vaststaande waarden. Deze zijn bevestigd door de eigenaar, geen gok.
# Merk per product komt uit een Odoo-attribuut met deze naam. Maak dat attribuut
# aan met Variant Creation = "Never", anders maakt Odoo er varianten van.
# Let op: die instelling kan niet meer gewijzigd worden zodra het attribuut in
# gebruik is op een product, dus zet hem meteen goed.
STORE_CODE = "LOU-MARIE"
BRAND_ATTRIBUTE = "Merk"
BRAND_FALLBACK = ""      # gebruikt als een product geen merkattribuut heeft
GENDER = "female"        # de hele winkel is dameskleding
AGE_GROUP = "adult"
CONDITION = "new"

HTTP_TIMEOUT = 30
SCRAPE_WORKERS = 6       # gelijktijdige verbindingen naar de webshop
SCRAPE_DELAY = 0.15      # pauze per worker na elk verzoek, wees beleefd
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


def derive_brand(details: list[tuple[str, str]]) -> str:
    """Merk uit het Odoo-attribuut, anders de fallback (mag leeg zijn)."""
    for name, value in details:
        if name.strip().lower() == BRAND_ATTRIBUTE.lower() and value.strip():
            return value.strip()
    return BRAND_FALLBACK


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


def scrape_compare_price(url: str) -> float | None:
    """
    Odoo toont een doorstreepprijs als 'Vergelijkingsprijs' is ingevuld:
        <del class="... oe_compare_list_price"> ... 39,95 EUR </del>
    Staat die er niet, dan is er geen aanbieding en geven we None terug.
    """
    try:
        page = fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  ! kon {url} niet ophalen: {exc}", file=sys.stderr)
        return None
    finally:
        if SCRAPE_DELAY:
            time.sleep(SCRAPE_DELAY)
    m = COMPARE_RE.search(page)
    if not m:
        return None
    v = CURRENCY_RE.search(m.group(1))
    return to_float(v.group(1)) if v else None


def scrape_all(urls: list[str], cache: dict) -> dict[str, float | None]:
    """
    Haalt alle productpagina's parallel op met een kleine pool threads.
    urllib blokkeert per verzoek, dus threads volstaan; geen async nodig.
    Cache-treffers die nog vers zijn worden overgeslagen.
    """
    prices: dict[str, float | None] = {}
    todo = []
    now = time.time()
    for url in dict.fromkeys(urls):          # dedupliceren, volgorde behouden
        entry = cache.get(url)
        if isinstance(entry, dict) and now - entry.get("ts", 0) < CACHE_MAX_AGE:
            prices[url] = entry.get("price")
        else:
            todo.append(url)

    if prices:
        print(f"  {len(prices)} uit cache", file=sys.stderr)
    if not todo:
        return prices

    print(f"  {len(todo)} ophalen met {SCRAPE_WORKERS} gelijktijdige verbindingen",
          file=sys.stderr)
    lock = threading.Lock()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCRAPE_WORKERS) as pool:
        futures = {pool.submit(scrape_compare_price, u): u for u in todo}
        for fut in concurrent.futures.as_completed(futures):
            url = futures[fut]
            try:
                price = fut.result()
            except Exception as exc:                       # noqa: BLE001
                print(f"  ! {url}: {exc}", file=sys.stderr)
                price = None
            with lock:
                prices[url] = price
                cache[url] = {"price": price, "ts": time.time()}
                done += 1
                if done % 25 == 0 or done == len(todo):
                    print(f"    {done}/{len(todo)}", file=sys.stderr)
    return prices


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
        if it.get("brand"):
            out.append(el("brand", it["brand"]))
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
    prices: dict[str, float | None] = {}
    if with_prices:
        prices = scrape_all([it["link"] for it in items if it["link"]], cache)

    for it in items:
        title = it["title"].strip()
        it["title"] = title
        desc = it["description"]

        current = to_float(it["price_raw"])
        it["price"] = f"{current:.2f} EUR" if current is not None else it["price_raw"]

        if with_prices and it["link"]:
            compare = prices.get(it["link"])
            if compare and current and compare > current:
                it["price"] = f"{compare:.2f} EUR"
                it["sale_price"] = f"{current:.2f} EUR"

        it["brand"] = derive_brand(it["details"])
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
    fields = ["brand", "color", "size", "size_system", "material", "pattern",
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

    no_brand = [it for it in items if not it.get("brand")]
    if no_brand:
        msg = (f"{len(no_brand)} items zonder merk. Vul het attribuut "
               f"'{BRAND_ATTRIBUTE}' in Odoo in (Variant Creation = Never).")
        print("\n" + msg)
        gh_warning(msg)

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
    ap.add_argument("--no-cache", action="store_true",
                    help="prijscache negeren, alles opnieuw ophalen (CI gebruikt dit)")
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
    if not args.no_prices and not args.no_cache and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            cache = {}

    if not args.no_prices:
        print("Doorstreepprijzen ophalen van de productpagina's...", file=sys.stderr)

    items = enrich(items, with_prices=not args.no_prices, cache=cache)

    if not args.no_prices and not args.no_cache:
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

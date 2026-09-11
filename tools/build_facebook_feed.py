#!/usr/bin/env python3
"""
Bouwt de Facebook-catalogusfeed (CSV) uit de al gegenereerde Google-feed.

Waarom afgeleid en niet apart opgebouwd: de Google-feed is de bron van waarheid voor
id's, prijzen, voorraad en verrijking. Twee losse bouwers zouden op termijn uit elkaar
lopen, en juist de id's moeten identiek blijven -- de Meta-pixel stuurt
`input[name="product_id"]` als content_ids, en dat is dezelfde Odoo-variant-id die in
<g:id> staat. Loopt dat uiteen, dan koppelt Meta events niet aan producten.

Twee bewerkingen die Facebook nodig heeft en Google niet:

1. **Links zonder /nl.** De Google-feed gebruikt /nl/shop/... en dat geeft een 303 naar
   /shop/... Google volgt dat prima, maar bij Meta komt het verkeer uit een trage in-app
   browser en telt elke extra rondgang. Gemeten 2026-09-11: 19 link-klikken leverden
   2 landingspaginaweergaven op.

2. **Afbeeldingen naar JPEG.** Meta accepteert alleen JPEG en PNG. Odoo levert WebP
   (106 van 137 producten) en de rest is PNG met een alfakanaal, wat Meta ook weigert.
   Beide worden hier omgezet naar JPEG op witte achtergrond en in de repo gezet, zodat
   raw.githubusercontent.com ze serveert -- dezelfde route waarlangs de feed zelf al gaat.

Gebruik:  python3 tools/build_facebook_feed.py [--in gmc-feed.xml] [--out facebook-feed.csv]
          --no-images      laat de Odoo-URL's staan (sneller, maar Meta weigert ze)
          --extra-images N aantal extra afbeeldingen per product (standaard 1)

Stdlib only, behalve de afbeeldingsconversie: die vraagt Pillow. Ontbreekt Pillow, dan
slaat het script die stap over met een waarschuwing en blijft de rest werken.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request
from xml.etree import ElementTree

G = "{http://base.google.com/ns/1.0}"

INPUT_PATH = "gmc-feed.xml"
OUTPUT_PATH = "facebook-feed.csv"

# Afbeeldingen: Meta wil JPEG of PNG zonder transparantie, minstens 500x500, onder 8 MB.
IMAGE_DIR = os.path.join("images", "feed")   # eigen map: images/ bevat al site-assets
IMAGE_BASE = "https://raw.githubusercontent.com/andriesss/lou-marie.be/main/images/feed/"
IMAGE_MAX_PX = 1200      # ruim boven Meta's 500x500-minimum, klein genoeg voor de repo
IMAGE_QUALITY = 85
MANIFEST = os.path.join(IMAGE_DIR, "manifest.json")

# De Google-feed linkt naar /nl/shop/... en dat geeft een 303 naar /shop/...
NL_PREFIX = re.compile(r"^(https://[^/]+)/nl/")

# Facebook eist een merk. De winkel voert geen eigen merk en de Google-feed laat het
# daarom bewust leeg (identifier_exists=no). Voor Facebook is de winkelnaam de gangbare
# invulling bij retailers zonder merkdata.
BRAND = "Lou-Marie"

# Facebook gebruikt "in stock" met spatie, Google "in_stock".
AVAILABILITY = {
    "in_stock": "in stock",
    "out_of_stock": "out of stock",
    "preorder": "preorder",
    "backorder": "backorder",
}

# Kolomvolgorde van de uitvoer. Verplicht voor Facebook: id, title, description,
# availability, condition, price, link, image_link, brand.
COLUMNS = [
    "id", "title", "description", "availability", "condition", "price", "sale_price",
    "link", "image_link", "additional_image_link", "brand", "item_group_id",
    "google_product_category", "product_type", "color", "size", "gender", "age_group",
    "material", "pattern", "custom_label_0", "custom_label_1", "custom_label_2",
    "custom_label_3", "custom_label_4",
]


def text(item: ElementTree.Element, name: str) -> str:
    node = item.find(G + name)
    if node is None or node.text is None:
        return ""
    return html.unescape(node.text).strip()


def texts(item: ElementTree.Element, name: str) -> list[str]:
    return [html.unescape(n.text).strip()
            for n in item.findall(G + name) if n is not None and n.text]


def convert(item: ElementTree.Element) -> dict | None:
    pid = text(item, "id")
    if not pid:
        return None

    avail_raw = text(item, "availability") or "in_stock"
    row = {
        "id": pid,
        "title": text(item, "title")[:200],
        "description": text(item, "description")[:9999],
        "availability": AVAILABILITY.get(avail_raw, avail_raw.replace("_", " ")),
        "condition": text(item, "condition") or "new",
        "price": text(item, "price"),
        "sale_price": text(item, "sale_price"),
        "link": NL_PREFIX.sub(r"\1/", text(item, "link")),
        "image_link": text(item, "image_link"),
        # Facebook wil aanvullende afbeeldingen als één komma-gescheiden veld
        "additional_image_link": ",".join(texts(item, "additional_image_link")[:20]),
        "brand": BRAND,
        "item_group_id": text(item, "item_group_id"),
        "google_product_category": text(item, "google_product_category"),
        "product_type": text(item, "product_type"),
        "color": text(item, "color"),
        "size": text(item, "size"),
        "gender": text(item, "gender"),
        "age_group": text(item, "age_group"),
        "material": text(item, "material"),
        "pattern": text(item, "pattern"),
    }
    for n in range(5):
        row[f"custom_label_{n}"] = text(item, f"custom_label_{n}")
    return row


# --- afbeeldingen -------------------------------------------------------------

def _fetch(url: str, pogingen: int = 2) -> bytes | None:
    """Haalt een afbeelding op. Eén herkansing, want een netwerkhikje in CI mag niet
    stilzwijgend de Odoo-URL laten staan die Meta vervolgens weigert."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for poging in range(1, pogingen + 1):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return resp.read()
        except Exception as exc:                  # noqa: BLE001 - bron is extern
            if poging == pogingen:
                print(f"  ! ophalen mislukt na {pogingen} pogingen: {url} ({exc})",
                      file=sys.stderr)
            else:
                time.sleep(2)
    return None


def _to_jpeg(raw: bytes, dest: str) -> bool:
    """WebP/PNG -> JPEG op witte achtergrond. Meta weigert WebP en transparantie."""
    from PIL import Image                          # lokaal: script blijft bruikbaar zonder
    import io

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:                       # noqa: BLE001
        print(f"  ! kan afbeelding niet lezen: {exc}", file=sys.stderr)
        return False

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        vlak = Image.new("RGB", img.size, (255, 255, 255))
        vlak.paste(img, mask=img.split()[-1])
        img = vlak
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if max(img.size) > IMAGE_MAX_PX:
        img.thumbnail((IMAGE_MAX_PX, IMAGE_MAX_PX), Image.LANCZOS)

    if min(img.size) < 500:
        print(f"  ! {os.path.basename(dest)} is {img.size[0]}x{img.size[1]}, "
              f"onder Meta's minimum van 500x500", file=sys.stderr)

    img.save(dest, "JPEG", quality=IMAGE_QUALITY, optimize=True, progressive=True)
    return True


def localise_images(rows: list[dict], extra: int) -> None:
    """Zet elke afbeelding om naar JPEG in de repo en herschrijft de URL's.

    Ongewijzigde bronnen worden overgeslagen (hash in manifest.json), zodat de
    dagelijkse build niet elke dag 137 bestanden opnieuw commit.
    """
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Pillow ontbreekt -- afbeeldingen blijven op de Odoo-URL's staan.\n"
              "  Meta weigert die (WebP / transparante PNG). Installeer met: pip install Pillow",
              file=sys.stderr)
        return

    os.makedirs(IMAGE_DIR, exist_ok=True)
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}

    nieuw = ongewijzigd = mislukt = 0
    gebruikt: set[str] = set()

    for row in rows:
        bronnen = [(row["image_link"], f"{row['id']}.jpg")]
        losse = [u for u in row["additional_image_link"].split(",") if u][:extra]
        bronnen += [(u, f"{row['id']}-{n + 1}.jpg") for n, u in enumerate(losse)]

        gelukt: dict[str, str] = {}
        for url, naam in bronnen:
            if not url:
                continue
            pad = os.path.join(IMAGE_DIR, naam)
            gebruikt.add(naam)
            raw = _fetch(url)
            if raw is None:
                mislukt += 1
                continue
            digest = hashlib.sha256(raw).hexdigest()
            if manifest.get(naam) == digest and os.path.exists(pad):
                ongewijzigd += 1
            elif _to_jpeg(raw, pad):
                manifest[naam] = digest
                nieuw += 1
            else:
                mislukt += 1
                continue
            gelukt[naam] = IMAGE_BASE + naam

        # Hoofdafbeelding en extra's strikt gescheiden houden. Lukt de hoofdafbeelding
        # niet, dan blijft de Odoo-URL staan (Meta weigert die, maar dat is zichtbaar);
        # een detailfoto mag NOOIT stilzwijgend de hoofdafbeelding worden.
        hoofd = f"{row['id']}.jpg"
        if hoofd in gelukt:
            row["image_link"] = gelukt[hoofd]
        else:
            print(f"  ! id {row['id']}: hoofdafbeelding niet omgezet, Odoo-URL blijft staan",
                  file=sys.stderr)
        extras = [gelukt[n] for _, n in bronnen[1:] if n in gelukt]
        if extras:
            row["additional_image_link"] = ",".join(extras)

    # Verweesde bestanden opruimen: producten die uit de feed zijn verdwenen.
    # NOODREM: raakt de bronfeed ooit onvolledig (mislukte Odoo-export, netwerkfout),
    # dan zou dit in één run bijna de hele beeldbank wissen. Meer dan een derde
    # ineens weggooien is vrijwel zeker een fout in de invoer, geen echte opschoning.
    verweesd = [n for n in manifest if n not in gebruikt]
    verwijderd = 0
    if manifest and len(verweesd) > len(manifest) / 3:
        print(f"  ! opruimen overgeslagen: {len(verweesd)} van {len(manifest)} "
              f"afbeeldingen zouden verdwijnen. Bronfeed lijkt onvolledig.",
              file=sys.stderr)
    else:
        for naam in verweesd:
            pad = os.path.join(IMAGE_DIR, naam)
            if os.path.exists(pad):
                os.remove(pad)
            del manifest[naam]
            verwijderd += 1

    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)

    print(f"afbeeldingen: {nieuw} omgezet, {ongewijzigd} ongewijzigd, "
          f"{mislukt} mislukt, {verwijderd} opgeruimd")


def validate(rows: list[dict]) -> list[str]:
    """Controleert wat Facebook zou weigeren. Blokkeert niet, maar rapporteert."""
    problems: list[str] = []
    verplicht = ["id", "title", "description", "availability", "condition",
                 "price", "link", "image_link", "brand"]
    seen: dict[str, int] = {}
    for row in rows:
        for veld in verplicht:
            if not row[veld]:
                problems.append(f"id {row['id']}: '{veld}' ontbreekt")
        if not re.fullmatch(r"\d+(\.\d{1,2})? [A-Z]{3}", row["price"] or ""):
            problems.append(f"id {row['id']}: prijs '{row['price']}' heeft niet de vorm '39.00 EUR'")
        if row["sale_price"] and not re.fullmatch(r"\d+(\.\d{1,2})? [A-Z]{3}", row["sale_price"]):
            problems.append(f"id {row['id']}: sale_price '{row['sale_price']}' onjuist")
        seen[row["id"]] = seen.get(row["id"], 0) + 1
    for pid, n in seen.items():
        if n > 1:
            problems.append(f"id {pid} komt {n}x voor -- Facebook verwerkt dan maar één rij")
    return problems


def report(rows: list[dict]) -> None:
    print(f"{len(rows)} producten")
    dekking = [
        ("sale_price", sum(1 for r in rows if r["sale_price"])),
        ("color", sum(1 for r in rows if r["color"])),
        ("size", sum(1 for r in rows if r["size"])),
        ("material", sum(1 for r in rows if r["material"])),
        ("pattern", sum(1 for r in rows if r["pattern"])),
        ("extra afbeeldingen", sum(1 for r in rows if r["additional_image_link"])),
        ("item_group_id", sum(1 for r in rows if r["item_group_id"])),
    ]
    print("dekking: " + ", ".join(f"{naam} {n}" for naam, n in dekking))
    labels: dict[str, int] = {}
    for r in rows:
        if r["custom_label_0"]:
            labels[r["custom_label_0"]] = labels.get(r["custom_label_0"], 0) + 1
    if labels:
        print("custom_label_0: " + ", ".join(f"{k} {v}" for k, v in sorted(labels.items())))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=INPUT_PATH, help="pad naar de Google-feed")
    ap.add_argument("--out", default=OUTPUT_PATH, help="pad naar de Facebook-CSV")
    ap.add_argument("--no-images", action="store_true",
                    help="laat de Odoo-URL's staan (Meta weigert die)")
    ap.add_argument("--extra-images", type=int, default=1, metavar="N",
                    help="extra afbeeldingen per product (standaard 1)")
    args = ap.parse_args()

    try:
        tree = ElementTree.parse(args.src)
    except (OSError, ElementTree.ParseError) as exc:
        print(f"kan {args.src} niet lezen: {exc}", file=sys.stderr)
        return 1

    rows = [r for r in (convert(i) for i in tree.iter("item")) if r]
    if not rows:
        print("geen producten gevonden in de bronfeed", file=sys.stderr)
        return 1

    if not args.no_images:
        localise_images(rows, max(0, args.extra_images))

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"{args.out} geschreven")
    report(rows)

    problems = validate(rows)
    if problems:
        print(f"\n{len(problems)} aandachtspunten:")
        for p in problems[:20]:
            print("  - " + p)
        if len(problems) > 20:
            print(f"  ... en nog {len(problems) - 20}")
    else:
        print("geen problemen gevonden")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

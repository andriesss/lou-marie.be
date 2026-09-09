#!/usr/bin/env python3
"""
Bouwt de Facebook-catalogusfeed (CSV) uit de al gegenereerde Google-feed.

Waarom afgeleid en niet apart opgebouwd: de Google-feed is de bron van waarheid voor
id's, prijzen, voorraad en verrijking. Twee losse bouwers zouden op termijn uit elkaar
lopen, en juist de id's moeten identiek blijven -- de Meta-pixel stuurt
`input[name="product_id"]` als content_ids, en dat is dezelfde Odoo-variant-id die in
<g:id> staat. Loopt dat uiteen, dan koppelt Meta events niet aan producten.

Gebruik:  python3 tools/build_facebook_feed.py [--in gmc-feed.xml] [--out facebook-feed.csv]
Stdlib only, geen dependencies.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from xml.etree import ElementTree

G = "{http://base.google.com/ns/1.0}"

INPUT_PATH = "gmc-feed.xml"
OUTPUT_PATH = "facebook-feed.csv"

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
        "link": text(item, "link"),
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

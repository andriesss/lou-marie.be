# GMC-feedbouwer

Genereert `gmc-feed.xml` in de repo-root: een Google Merchant Center kledingfeed met
de attributen die Odoo's eigen `gmc.xml` niet kan leveren.

## Waarom dit bestaat

Odoo Online levert alleen `id`, `title`, `description`, `link`, `image_link`,
`availability`, `price`, `product_type` en `item_group_id`. Alle kledingattributen
ontbreken, en de maat reist mee als een los `product_detail`-blok dat Google **niet**
als `size` leest. Odoo-productattributen toevoegen lost dat niet op: die komen
allemaal als `product_detail` in de feed terecht, ongeacht hoe je ze noemt.
Bovendien maken ze in Odoo varianten aan en vervuilen ze je catalogus.

Dit script vult het gat.

## Wat het toevoegt

| Veld | Bron |
|---|---|
| `gender`, `age_group`, `condition` | vaste waarden bovenaan het script |
| `size` | het `product_detail`-veld met label "Maat" |
| `size_system` | `EU`, alleen bij numerieke maten (38, 42, 44) |
| `color` | de titel (patroon `..., kleur`) of een woordenlijst-scan |
| `material` | woordenlijst-scan over titel en omschrijving |
| `pattern` | woordenlijst-scan over titel en omschrijving |
| `google_product_category` | mapping van je Odoo-websitecategorie |
| `sale_price` | de doorstreepprijs van de productpagina |
| `custom_label_1..4` | prijsklasse, hoofdcategorie, aanbieding, nieuw |

`brand` blijft leeg: er is geen eigen merk en een verzonnen merknaam is slechter
dan geen. Daarom staat `identifier_exists` op `no`. Verandert dat ooit, vul dan
`BRAND` bovenaan het script in.

`product_type` bevat alleen echte productcategorieen. `SALE` en `NIEUW` zijn
verkooplabels, geen producttypes; die gaan naar `custom_label_3` en
`custom_label_4` zodat je er wel op kan segmenteren in je campagne.

## Het uitgangspunt: niets verzinnen

Een attribuut wordt alleen weggeschreven als het aantoonbaar uit de brondata komt.
Staat er geen stof in de omschrijving, dan krijgt dat item geen `material`. Een
ontbrekend veld kost je wat matchkwaliteit; een fout veld kost je een afkeuring en
retouren.

Na elke build toont het script welke items géén kleur kregen, zodat je die met de
hand kan aanvullen in Odoo. Dat is werk voor jou, niet voor het script.

## Instellen

De bron-feed bevat een access_token en deze repo is openbaar, dus die staat niet in
de code. Zet hem in je omgeving:

```bash
export GMC_SOURCE_FEED="https://www.lou-marie.be/gmc.xml?feed_id=7&access_token=..."
```

Voor de GitHub Action: **Settings → Secrets and variables → Actions → New repository
secret**, naam `GMC_SOURCE_FEED`, waarde de volledige URL.

## Gebruik

```bash
python3 tools/build_gmc_feed.py                # volledig, duurt ~1 minuut
python3 tools/build_gmc_feed.py --no-prices    # zonder doorstreepprijzen, seconden
python3 tools/build_gmc_feed.py --report-only  # alleen de dekking tonen
```

Geen dependencies, alleen de Python-standaardbibliotheek.

Doorstreepprijzen worden gecached in `tools/.price-cache.json`. Verwijder dat bestand
als je prijzen hebt aangepast in Odoo en de wijziging meteen wil zien.

## De feed aan Google koppelen

Commit `gmc-feed.xml` en verwijs Merchant Center naar de raw-URL:

```
https://raw.githubusercontent.com/andriesss/lou-marie.be/main/gmc-feed.xml
```

Merchant Center → Producten → Feeds → **Feed toevoegen** → *Geplande ophaling*, en
zet het ophaalmoment ná 05:20 UTC, zodat je altijd de verse versie krijgt.

Laat de oude Odoo-feed voorlopig staan tot deze is goedgekeurd. Draaien ze allebei
tegelijk, dan overschrijven ze elkaars items — koppel de oude feed dus los zodra
deze werkt.

## Automatisch bijwerken

`.github/workflows/gmc-feed.yml` draait het script elke dag om 05:20 UTC en commit
alleen als er iets gewijzigd is. Je kan hem ook handmatig starten via de
Actions-tab.

Let op: die commit landt op `main` en zet daarmee ook de bestaande
`deploy.yml` (Eleventy naar GitHub Pages) in gang. Die workflow hoort bij de
oude site en is niet meer nodig nu het domein naar Odoo wijst. Zet hem uit als je
geen dagelijkse foutmeldingen wil.

## Onderhoud

Alles wat je waarschijnlijk ooit wil aanpassen staat bovenaan het script:

- `GMC_SOURCE_FEED` (omgevingsvariabele) — verandert als je in Odoo een nieuwe feed aanmaakt
- `BRAND` — nu leeg; invullen voegt het veld toe
- `MERCH_LABELS` — websitecategorieen die geen producttype zijn
- `CATEGORY_MAP` — nieuwe websitecategorie? Voeg hem hier toe
- `COLORS`, `MATERIALS`, `PATTERNS` — woordenlijsten, sleutel is wat in de feed komt

De officiële Google-taxonomie wordt bij elke build opgehaald en je categorieën
worden ertegen gecontroleerd. Typ je er één verkeerd, dan zie je dat meteen in de
uitvoer in plaats van pas bij een afkeuring.

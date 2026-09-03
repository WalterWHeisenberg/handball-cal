import requests
from ics import Calendar
from datetime import timedelta
import urllib.parse
import time
import re
import sys

# --- Globale Einstellungen ---
START_ADRESSE = "Gouvieuxstraße 2, 51588 Nümbrecht"

# --- Konfiguration: handball.net Abo-Kalender (ICS-Feed, wird gefiltert) ---
# nuLiga/liga.nu ist entfallen. handball.net liefert pro Liga einen
# Gesamt-Kalender als ICS; wir laden ihn herunter, übernehmen nur die Spiele
# des eigenen Vereins und ergänzen Halle + Fahrzeit in der Beschreibung.
HANDBALLNET_CONFIG = [
    {
        "url": "https://www.handball.net/kalender/liga/8053.ics",
        "filter_team": "Nümbrecht",
        "output": "handball_h3.ics",
        "puffer_min": 60,
        "immer_fahrzeit_berechnen": False
    },
    # Weitere Kalender (wJC, mJD1, mJD2, wJB, wJC-HSG, ggf. FC Köln) hier
    # ergänzen, sobald die jeweilige handball.net Liga-ICS-URL bekannt ist:
    # {
    #     "url": "https://www.handball.net/kalender/liga/XXXX.ics",
    #     "filter_team": "Nümbrecht",
    #     "output": "handball_wjc.ics",
    #     "puffer_min": 75,
    #     "immer_fahrzeit_berechnen": False
    # },
]

# --- Caches für Performance (pro Skriptlauf) ---
fahrzeit_cache = {}
koordinaten_cache = {}

# Mögliche Trennzeichen, mit denen handball.net Heim- und Gastmannschaft
# im Event-Titel (SUMMARY) verbindet. Wird defensiv probiert, da das exakte
# Format nicht offiziell dokumentiert ist.
TITEL_TRENNER = [" - ", " – ", " vs. ", " vs ", " : "]


def zerlege_titel(titel):
    """Versucht Heim- und Gastmannschaft aus dem Event-Titel zu extrahieren."""
    for trenner in TITEL_TRENNER:
        if trenner in titel:
            teile = titel.split(trenner, 1)
            if len(teile) == 2:
                return teile[0].strip(), teile[1].strip()
    return None, None


def bereinige_adresse(adresse):
    """Intelligente Adressbereinigung mit Regex-Parsing"""
    original = adresse
    adresse = re.sub(r'Tel\.?:?\s*[\d\s/\-()]+', '', adresse, flags=re.IGNORECASE)
    adresse = re.sub(r'Telefon:?\s*[\d\s/\-()]+', '', adresse, flags=re.IGNORECASE)
    adresse = re.sub(r'Fax:?\s*[\d\s/\-()]+', '', adresse, flags=re.IGNORECASE)
    adresse = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', adresse)
    adresse = re.sub(r'http[s]?://\S+', '', adresse)
    adresse = adresse.replace('\n', ' ').replace('\r', ' ')
    adresse = re.sub(r'\s+', ' ', adresse).strip()

    match = re.search(r'([^\d]+)\s*(\d{5})\s+([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+)?)', adresse)
    if match:
        strasse, plz, ort = match.groups()
        adresse = f"{strasse.strip()}, {plz} {ort}"

    if ',' in adresse:
        teile = adresse.split(',', 1)
        erster_teil = teile[0].strip().lower()
        if not any(char.isdigit() for char in teile[0]) and \
           not any(keyword in erster_teil for keyword in ['straße', 'str.', 'weg', 'platz', 'allee', 'gasse']):
            adresse = teile[1].strip()

    if 'deutschland' not in adresse.lower() and 'germany' not in adresse.lower():
        adresse += ', Deutschland'

    if len(original) - len(adresse) > 20:
        print(f"  🔧 Adresse bereinigt von: '{original[:50]}...'")
        print(f"     zu: '{adresse[:50]}...'")

    return adresse


def get_coords_strukturiert(adresse):
    strasse_match = re.search(r'([A-ZÄÖÜa-zäöüß\.\-]+(?:straße|str\.|weg|platz|allee))\s*(\d+[a-z]?)', adresse, re.IGNORECASE)
    plz_match = re.search(r'\b(\d{5})\b', adresse)
    ort_match = re.search(r'(\d{5})\s+([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+)?)', adresse)

    params = {'format': 'json', 'countrycodes': 'de', 'limit': 1}
    if strasse_match:
        params['street'] = f"{strasse_match.group(1)} {strasse_match.group(2)}"
    if plz_match:
        params['postalcode'] = plz_match.group(1)
    if ort_match:
        params['city'] = ort_match.group(2)

    if len(params) > 3:
        try:
            headers = {'User-Agent': 'HandballKalenderSkript/1.0'}
            response = requests.get('https://nominatim.openstreetmap.org/search', params=params, headers=headers, timeout=10)
            data = response.json()
            if data:
                print(f"  ✓ Strukturierte Suche: {params.get('street', '')} {params.get('postalcode', '')} {params.get('city', '')}")
                return data[0]['lat'], data[0]['lon']
        except Exception:
            pass

    return None, None


def get_coords(adresse):
    if adresse in koordinaten_cache:
        return koordinaten_cache[adresse]

    lat, lon = get_coords_strukturiert(adresse)
    if lat and lon:
        koordinaten_cache[adresse] = (lat, lon)
        return lat, lon

    time.sleep(0.5)
    adresse_bereinigt = bereinige_adresse(adresse)
    try:
        headers = {'User-Agent': 'HandballKalenderSkript/1.0'}
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(adresse_bereinigt)}&format=json&countrycodes=de&limit=1"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data:
            lat, lon = data[0]['lat'], data[0]['lon']
            koordinaten_cache[adresse] = (lat, lon)
            print(f"  ✓ Nominatim (bereinigte Adresse): Koordinaten gefunden")
            return lat, lon
    except Exception as e:
        print(f"  ⚠ Nominatim fehlgeschlagen: {e}")

    time.sleep(0.5)
    try:
        url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(adresse_bereinigt)}&limit=1"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('features'):
            coords = data['features'][0]['geometry']['coordinates']
            lat, lon = str(coords[1]), str(coords[0])
            koordinaten_cache[adresse] = (lat, lon)
            print(f"  ✓ Photon (Fallback): Koordinaten gefunden")
            return lat, lon
    except Exception as e:
        print(f"  ⚠ Photon fehlgeschlagen: {e}")

    print(f"  ✗ Keine Koordinaten gefunden für: {adresse[:60]}...")
    koordinaten_cache[adresse] = (None, None)
    return None, None


def hole_fahrzeit(ziel_adresse):
    """Berechnet die Fahrzeit von der Startadresse zum Ziel in Minuten."""
    if not ziel_adresse:
        return None
    if ziel_adresse in fahrzeit_cache:
        return fahrzeit_cache[ziel_adresse]

    start_lat, start_lon = get_coords(START_ADRESSE)
    ziel_lat, ziel_lon = get_coords(ziel_adresse)

    time.sleep(1)

    if not all([start_lat, start_lon, ziel_lat, ziel_lon]):
        print(f"  ⚠ Koordinaten für Fahrzeit konnten nicht ermittelt werden.")
        fahrzeit_cache[ziel_adresse] = None
        return None

    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{ziel_lon},{ziel_lat}?overview=false"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 'Ok':
            duration_minutes = int(data['routes'][0]['duration'] / 60)
            fahrzeit_cache[ziel_adresse] = duration_minutes
            print(f"  → Fahrzeit nach '{ziel_adresse[:40]}...': {duration_minutes} min")
            return duration_minutes
    except Exception as e:
        print(f"  ⚠ OSRM-Routing fehlgeschlagen: {e}")

    fahrzeit_cache[ziel_adresse] = None
    return None


def verarbeite_handballnet_kalender(url, filter_team, output, puffer_min=60, immer_fahrzeit_berechnen=False):
    """
    Lädt einen kompletten Liga-ICS-Kalender von handball.net, übernimmt nur
    die Spiele des eigenen Vereins und ergänzt die Beschreibung um Halle,
    Treffzeit und (bei Auswärtsspielen) Fahrzeit/Abfahrtszeit.
    Der Event-Titel (SUMMARY) von handball.net bleibt dabei unverändert.
    """
    print(f"\n{'='*60}\nhandball.net-Kalender: {output} (Filter: '{filter_team}')\n{'='*60}")

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        ics_text = response.text
    except requests.exceptions.RequestException as e:
        print(f"✗ Fehler beim Abrufen von handball.net: {e}")
        return False

    try:
        quell_cal = Calendar(ics_text)
    except Exception as e:
        print(f"✗ ICS konnte nicht geparst werden: {e}")
        return False

    print(f"  → {len(quell_cal.events)} Spiele im Gesamt-Kalender gefunden")

    ziel_cal = Calendar()
    treffer = 0
    filter_lower = filter_team.lower()

    for event in quell_cal.events:
        titel = event.name or ""
        beschreibung_original = event.description or ""
        ort = (event.location or "").strip()
        haystack = f"{titel} {beschreibung_original} {ort}".lower()

        if filter_lower not in haystack:
            continue

        treffer += 1

        heim, gast = zerlege_titel(titel)
        if heim and gast:
            spieltyp = "Heimspiel" if filter_lower in heim.lower() else (
                "Auswärts" if filter_lower in gast.lower() else "unbekannt"
            )
        else:
            spieltyp = "unbekannt"
            print(f"  ⚠ Titel konnte nicht in Heim/Gast zerlegt werden: '{titel}'")

        zeit_info_zeilen = []
        if ort:
            zeit_info_zeilen.append(f"Halle: {ort}")

        if event.begin:
            treffzeit = event.begin - timedelta(minutes=puffer_min)
            zeit_info_zeilen.append(f"Treffzeit an der Halle: {treffzeit.strftime('%H:%M Uhr')}")

            soll_fahrzeit_berechnen = ort and (spieltyp == "Auswärts" or immer_fahrzeit_berechnen or spieltyp == "unbekannt")
            if soll_fahrzeit_berechnen:
                fahrzeit = hole_fahrzeit(ort)
                if fahrzeit is not None:
                    abfahrtszeit = treffzeit - timedelta(minutes=fahrzeit)
                    zeit_info_zeilen.insert(0, f"Abfahrt von Nümbrecht: {abfahrtszeit.strftime('%H:%M Uhr')}")
                    zeit_info_zeilen.insert(1, f"Voraussichtliche Fahrzeit: ca. {fahrzeit} Minuten")

        zusatz = "\n== Zeiten & Ort ==\n" + "\n".join(zeit_info_zeilen)
        event.description = (beschreibung_original + zusatz) if beschreibung_original else zusatz.strip()

        ziel_cal.events.add(event)

    with open(output, "w", encoding="utf-8") as f:
        f.writelines(ziel_cal)

    print(f"✓ {treffer} Spiele mit '{filter_team}' übernommen -> {output}")

    if treffer == 0:
        print(f"  ⚠ Keine Treffer! Beispiel-Titel aus dem Feed zur Kontrolle:")
        for event in list(quell_cal.events)[:3]:
            print(f"    Titel: {event.name} | Ort: {event.location}")

    return True


# --- Hauptprogramm ---
if __name__ == "__main__":
    print("="*60 + "\nHANDBALL KALENDER GENERATOR (handball.net)\n" + "="*60)

    results = []
    for config in HANDBALLNET_CONFIG:
        result = verarbeite_handballnet_kalender(
            url=config["url"],
            filter_team=config["filter_team"],
            output=config["output"],
            puffer_min=config.get("puffer_min", 60),
            immer_fahrzeit_berechnen=config.get("immer_fahrzeit_berechnen", False)
        )
        results.append(result)

    print(f"\n{'='*60}\nZUSAMMENFASSUNG\n{'='*60}")
    print(f"Erfolgreich: {sum(1 for r in results if r)} | Fehler: {sum(1 for r in results if not r)}")
    print(f"Koordinaten im Cache: {len(koordinaten_cache)} | Fahrzeiten im Cache: {len(fahrzeit_cache)}\n{'='*60}\n")
    sys.exit(0)

import requests
from ics import Calendar
from datetime import timedelta
from math import radians, sin, cos, sqrt, atan2
import urllib.parse
import time
import re
import sys

# --- Globale Einstellungen ---
START_ADRESSE = "Gouvieuxstraße 2, 51588 Nümbrecht"

# --- Konfiguration: handball.net Abo-Kalender (ICS-Feed, wird gefiltert) ---
# nuLiga/liga.nu ist entfallen (wird abgeschaltet). handball.net liefert pro
# Liga einen Gesamt-Kalender als ICS; wir laden ihn herunter, übernehmen nur
# die Spiele des eigenen Vereins (bzw. des gewünschten Vereins) und ergänzen
# Halle, Treffzeit und Fahrzeit in der Beschreibung.
HANDBALLNET_CONFIG = [
    {
        "url": "https://www.handball.net/kalender/liga/8053.ics",
        "filter_team": "Nümbrecht",
        "output": "handball_h3.ics",
        "puffer_min": 60,
        "immer_fahrzeit_berechnen": False
    },
    {
        "url": "https://www.handball.net/kalender/liga/10014.ics?season_id=2627&fed_id=148",
        "filter_team": "Nümbrecht",
        "output": "handball_mjd1.ics",
        "puffer_min": 60,
        "immer_fahrzeit_berechnen": False
    },
    {
        "url": "https://www.handball.net/kalender/liga/10012.ics?season_id=2627&fed_id=148",
        "filter_team": "Nümbrecht",
        "output": "handball_wjb.ics",
        "puffer_min": 60,
        "immer_fahrzeit_berechnen": False
    },
    {
        # Hier interessiert der 1. FC Köln, nicht Nümbrecht.
        # Filter bewusst nur auf "Köln" (statt "1. FC Köln"), da der exakte
        # Vereinsname im Feed abweichend geschrieben sein kann
        # (z.B. "1.FC Köln", "1. FC Köln 1934" o.ä.) - "Köln" als Teilstring
        # ist robuster.
        # immer_fahrzeit_berechnen=True, da die Fahrzeit ab Nümbrecht
        # unabhängig davon interessant ist, ob Köln Heim- oder Auswärtsspiel hat.
        "url": "https://www.handball.net/kalender/liga/6108.ics?season_id=2627&fed_id=20",
        "filter_team": "Köln",
        "output": "handball_wjc-hsg.ics",
        "puffer_min": 60,
        "immer_fahrzeit_berechnen": True
    },

    # Noch ohne handball.net-ICS-Quelle -> vorerst auskommentiert:
    # {
    #     "url": "https://www.handball.net/kalender/liga/XXXX.ics",
    #     "filter_team": "Nümbrecht",
    #     "output": "handball_wjc.ics",
    #     "puffer_min": 75,
    #     "immer_fahrzeit_berechnen": False
    # },
    # {
    #     "url": "https://www.handball.net/kalender/liga/XXXX.ics",
    #     "filter_team": "Nümbrecht",
    #     "output": "handball_mjd2.ics",
    #     "puffer_min": 60,
    #     "immer_fahrzeit_berechnen": False
    # },
]

# --- Manuelle Hallen-Overrides (bei bekannten Geokodierungs-Fehlern) ---
# Schlüssel = eindeutiges Teilwort im Hallen-/Ortsnamen (klein geschrieben).
HALLEN_KOORDINATEN_MANUELL = {
    # "wiehl": (50.9530, 7.4550),
}

# Bekannte, noch nicht ins Deutsche übersetzte Status-Begriffe von
# handball.net (vermutlich ein Lokalisierungs-Bug in deren Backend).
STATUS_UEBERSETZUNG = {
    "pendiente": "Ausstehend",
    "finalizado": "Beendet",
    "en curso": "Laufend",
    "en juego": "Laufend",
    "aplazado": "Verschoben",
    "cancelado": "Abgesagt",
    "suspendido": "Abgebrochen",
}

# --- Caches für Performance (pro Skriptlauf) ---
fahrzeit_cache = {}
koordinaten_cache = {}

# Mögliche Trennzeichen zwischen Heim- und Gastmannschaft im Event-Titel.
# " - " ist im echten handball.net-Feed bestätigt (z.B.
# "TV Wahlscheid II - SG Engelskirchen/Loope").
TITEL_TRENNER = [" - ", " – ", " vs. ", " vs ", " : "]


def zerlege_titel(titel):
    """Versucht Heim- und Gastmannschaft aus dem Event-Titel zu extrahieren."""
    for trenner in TITEL_TRENNER:
        if trenner in titel:
            teile = titel.split(trenner, 1)
            if len(teile) == 2:
                return teile[0].strip(), teile[1].strip()
    return None, None


def uebersetze_status(text):
    """Ersetzt bekannte spanische Status-Begriffe durch deutsche Entsprechungen."""
    if not text:
        return text
    ergebnis = text
    for spanisch, deutsch in STATUS_UEBERSETZUNG.items():
        ergebnis = re.sub(rf'\b{re.escape(spanisch)}\b', deutsch, ergebnis, flags=re.IGNORECASE)
    return ergebnis


def korrigiere_umlaut_grossschreibung(text):
    """
    Korrigiert einen Quell-Bug bei handball.net: Ortsnamen werden in
    Grossbuchstaben geschrieben, dabei aber Umlaute klein gelassen
    (z.B. "WALDBRöL" statt "WALDBRÖL", "NüMBRECHT" statt "NÜMBRECHT").
    Das erschwert die Geokodierung unnötig.
    """
    if not text:
        return text
    return text.replace('ü', 'Ü').replace('ö', 'Ö').replace('ä', 'Ä')


def haversine_km(lat1, lon1, lat2, lon2):
    """Luftlinien-Distanz in km zwischen zwei Koordinaten."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(lambda x: radians(float(x)), [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def extrahiere_plz(adresse):
    match = re.search(r'\b(\d{5})\b', adresse)
    return match.group(1) if match else None


def bereinige_adresse(adresse):
    """Intelligente Adressbereinigung mit Regex-Parsing (Fallback-Strategie)."""
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
        print(f"  🔧 Adresse bereinigt von: '{original[:50]}...' zu: '{adresse[:50]}...'")

    return adresse


def geocode_mit_validierung(adresse, erwartete_plz=None):
    """
    Nominatim-Freitextsuche mit Adressdetails, prüft die zurückgegebene PLZ
    gegen die erwartete PLZ (falls vorhanden). Verhindert, dass ein falsch
    getroffener Ort mit gleichem/ähnlichem Namen unbemerkt akzeptiert wird.
    """
    try:
        headers = {'User-Agent': 'HandballKalenderSkript/1.0'}
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': adresse, 'format': 'json', 'countrycodes': 'de', 'limit': 3, 'addressdetails': 1}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data:
            return None, None

        if erwartete_plz:
            for treffer in data:
                gefundene_plz = treffer.get('address', {}).get('postcode')
                if gefundene_plz == erwartete_plz:
                    return treffer['lat'], treffer['lon']
            print(f"  ⚠ Keine Übereinstimmung mit erwarteter PLZ {erwartete_plz}, nehme ersten Treffer mit Vorbehalt")

        return data[0]['lat'], data[0]['lon']
    except Exception as e:
        print(f"  ⚠ Nominatim fehlgeschlagen: {e}")
        return None, None


def get_coords(adresse):
    if adresse in koordinaten_cache:
        return koordinaten_cache[adresse]

    # 1. Manuelle Overrides zuerst prüfen (zuverlässigste Quelle)
    adresse_lower = adresse.lower()
    for schluesselwort, (lat, lon) in HALLEN_KOORDINATEN_MANUELL.items():
        if schluesselwort in adresse_lower:
            koordinaten_cache[adresse] = (lat, lon)
            print(f"  ✓ Manueller Override für '{schluesselwort}' verwendet")
            return lat, lon

    erwartete_plz = extrahiere_plz(adresse)

    # 2. Freitextsuche mit PLZ-Validierung
    lat, lon = geocode_mit_validierung(adresse, erwartete_plz)
    if lat and lon:
        koordinaten_cache[adresse] = (lat, lon)
        return lat, lon

    time.sleep(0.5)

    # 3. Fallback: bereinigte Adresse erneut versuchen
    adresse_bereinigt = bereinige_adresse(adresse)
    lat, lon = geocode_mit_validierung(adresse_bereinigt, erwartete_plz)
    if lat and lon:
        koordinaten_cache[adresse] = (lat, lon)
        return lat, lon

    time.sleep(0.5)

    # 4. Letzter Fallback: Photon
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
    """
    Berechnet die Fahrzeit von der Startadresse zum Ziel in Minuten.
    Prüft das OSRM-Ergebnis zusätzlich auf Plausibilität anhand der
    Luftlinien-Distanz, um Geokodierungsfehler (falscher Ort gleichen
    Namens) zu erkennen.
    """
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

    distanz_km = haversine_km(start_lat, start_lon, ziel_lat, ziel_lon)

    duration_minutes = None
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{ziel_lon},{ziel_lat}?overview=false"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 'Ok':
            duration_minutes = int(data['routes'][0]['duration'] / 60)
    except Exception as e:
        print(f"  ⚠ OSRM-Routing fehlgeschlagen: {e}")

    # Plausibilitätsprüfung: unter 15 km/h Durchschnitt ist unrealistisch
    # für PKW-Fahrten -> deutet auf falsch geokodierten Ort hin.
    plausibel = True
    if duration_minutes is not None and distanz_km > 0:
        implizierte_kmh = distanz_km / (duration_minutes / 60)
        if implizierte_kmh < 15:
            plausibel = False
            print(f"  ⚠ Unplausible Fahrzeit erkannt: {duration_minutes} min für {distanz_km:.1f} km "
                  f"({implizierte_kmh:.0f} km/h) -> nutze Schätzung")

    if duration_minutes is None or not plausibel:
        # Grobe Schätzung: 45 km/h Durchschnitt für Landstraßen im Oberbergischen
        duration_minutes = max(5, round(distanz_km / 45 * 60))
        fahrzeit_cache[ziel_adresse] = duration_minutes
        print(f"  → Fahrzeit (Schätzung, {distanz_km:.1f} km Luftlinie): ca. {duration_minutes} min")
        return duration_minutes

    fahrzeit_cache[ziel_adresse] = duration_minutes
    print(f"  → Fahrzeit nach '{ziel_adresse[:40]}...': {duration_minutes} min ({distanz_km:.1f} km Luftlinie)")
    return duration_minutes


def verarbeite_handballnet_kalender(url, filter_team, output, puffer_min=60, immer_fahrzeit_berechnen=False):
    """
    Lädt einen kompletten Liga-ICS-Kalender von handball.net, übernimmt nur
    die Spiele des gewünschten Vereins und ergänzt die Beschreibung um
    Halle, Treffzeit und (bei Bedarf) Fahrzeit/Abfahrtszeit.
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
        beschreibung_original = uebersetze_status(event.description or "")
        ort = korrigiere_umlaut_grossschreibung((event.location or "").strip())
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
        event.location = ort

        ziel_cal.events.add(event)

    with open(output, "w", encoding="utf-8") as f:
        f.writelines(ziel_cal)

    print(f"✓ {treffer} Spiele mit '{filter_team}' übernommen -> {output}")

    if treffer == 0:
        print(f"  ⚠ Keine Treffer! Beispiel-Titel aus dem Feed zur Kontrolle:")
        for event in list(quell_cal.events)[:3]:
            print(f"    Titel: {event.name} | Ort: {event.location}")

    return True


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

    # Bricht den Workflow sichtbar (rotes Kreuz) ab, wenn KEIN einziger
    # Kalender erstellt werden konnte - z.B. bei einem fehlenden Import.
    if results and not any(results):
        print("✗ ABBRUCH: Kein einziger Kalender konnte erfolgreich erstellt werden.")
        sys.exit(1)

    sys.exit(0)

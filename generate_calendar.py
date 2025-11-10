import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime, timedelta
import pytz
import sys
import urllib.parse
import time
import re

# --- Konfiguration für mehrere Kalender ---
KALENDER_CONFIG = [
    {
        "name": "SSV Nümbrecht Handball",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424244",
        "output": "handball_wjc.ics",
        "puffer_min": 75
    },
    {
        "name": "SSV Nümbrecht Handball",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424217",
        "output": "handball_mjd1.ics",
        "puffer_min": 60
    },
    {
        "name": "SSV Nümbrecht Handball",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424113",
        "output": "handball_mjd2.ics",
        "puffer_min": 60
    },
    {
        "name": "SSV Nümbrecht Handball III",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424114",
        "output": "handball_h3.ics",
        "puffer_min": 60
    },
    {
        "name": "SSV Nümbrecht Handball",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424406",
        "output": "handball_wjb.ics",
        "puffer_min": 60
    },
    {
        "name": "HSG Siebengebirge-Thomasberg",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=HNR+25%2F26&group=423996",
        "output": "handball_wjc-hsg.ics",
        "puffer_min": 60,
        "immer_fahrzeit_berechnen": True
    }
]

# --- Globale Einstellungen ---
ZEITZONE = pytz.timezone("Europe/Berlin")
START_ADRESSE = "Gouvieuxstraße 2, 51588 Nümbrecht"

# --- Caches für Performance ---
hallen_cache = {}
fahrzeit_cache = {}
koordinaten_cache = {}

def bereinige_adresse(adresse):
    """Intelligente Adressbereinigung mit Regex-Parsing"""
    original = adresse
    
    # 1. Entferne Telefonnummern (verschiedene Formate)
    adresse = re.sub(r'Tel\.?:?\s*[\d\s/\-()]+', '', adresse, flags=re.IGNORECASE)
    adresse = re.sub(r'Telefon:?\s*[\d\s/\-()]+', '', adresse, flags=re.IGNORECASE)
    adresse = re.sub(r'Fax:?\s*[\d\s/\-()]+', '', adresse, flags=re.IGNORECASE)
    
    # 2. Entferne Email-Adressen
    adresse = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', adresse)
    
    # 3. Entferne URLs
    adresse = re.sub(r'http[s]?://\S+', '', adresse)
    
    # 4. Normalisiere Zeilenumbrüche und mehrfache Leerzeichen
    adresse = adresse.replace('\n', ' ').replace('\r', ' ')
    adresse = re.sub(r'\s+', ' ', adresse).strip()
    
    # 5. Erkenne und korrigiere PLZ-Ort-Trennung
    match = re.search(r'([^\d]+)\s*(\d{5})\s+([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+)?)', adresse)
    if match:
        strasse, plz, ort = match.groups()
        adresse = f"{strasse.strip()}, {plz} {ort}"
    
    # 6. Entferne Hallennamen am Anfang (falls kein Teil der Adresse)
    if ',' in adresse:
        teile = adresse.split(',', 1)
        erster_teil = teile[0].strip().lower()
        if not any(char.isdigit() for char in teile[0]) and \
           not any(keyword in erster_teil for keyword in ['straße', 'str.', 'weg', 'platz', 'allee', 'gasse']):
            adresse = teile[1].strip()
    
    # 7. Füge Deutschland hinzu, falls nicht vorhanden
    if 'deutschland' not in adresse.lower() and 'germany' not in adresse.lower():
        adresse += ', Deutschland'
    
    # Debug-Ausgabe bei signifikanten Änderungen
    if len(original) - len(adresse) > 20:
        print(f"  🔧 Adresse bereinigt: '{original[:40]}...' → '{adresse[:40]}...'")
    
    return adresse

def get_coords_strukturiert(adresse):
    """Versucht strukturierte Abfrage bei Nominatim"""
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
                print(f"  ✓ Strukturierte Suche erfolgreich")
                return data[0]['lat'], data[0]['lon']
        except Exception:
            pass
    
    return None, None

def get_coords(adresse):
    """Wandelt eine Adresse in Geo-Koordinaten um - mit mehreren Strategien"""
    if adresse in koordinaten_cache:
        return koordinaten_cache[adresse]
    
    # Strategie 1: Strukturierte Suche
    lat, lon = get_coords_strukturiert(adresse)
    if lat and lon:
        koordinaten_cache[adresse] = (lat, lon)
        return lat, lon
    
    time.sleep(0.5)
    
    # Strategie 2: Bereinigte Adresse mit Nominatim
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
            print(f"  ✓ Nominatim: Koordinaten gefunden")
            return lat, lon
    except Exception as e:
        print(f"  ⚠ Nominatim fehlgeschlagen: {e}")
    
    time.sleep(0.5)
    
    # Strategie 3: Photon (Fallback)
    try:
        url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(adresse_bereinigt)}&limit=1"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('features'):
            coords = data['features'][0]['geometry']['coordinates']
            lat, lon = str(coords[1]), str(coords[0])
            koordinaten_cache[adresse] = (lat, lon)
            print(f"  ✓ Photon: Koordinaten gefunden")
            return lat, lon
    except Exception as e:
        print(f"  ⚠ Photon fehlgeschlagen: {e}")
    
    print(f"  ✗ Keine Koordinaten für: {adresse[:40]}...")
    koordinaten_cache[adresse] = (None, None)
    return None, None

def hole_fahrzeit(ziel_adresse):
    """Berechnet die Fahrzeit von der Startadresse zum Ziel in Minuten."""
    if ziel_adresse in fahrzeit_cache:
        return fahrzeit_cache[ziel_adresse]

    start_lat, start_lon = get_coords(START_ADRESSE)
    ziel_lat, ziel_lon = get_coords(ziel_adresse)
    
    time.sleep(1) 

    if not all([start_lat, start_lon, ziel_lat, ziel_lon]):
        print(f"  ⚠ Koordinaten für Fahrzeit fehlen")
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
            print(f"  → Fahrzeit: {duration_minutes} min")
            return duration_minutes
    except Exception as e:
        print(f"  ⚠ OSRM-Routing fehlgeschlagen: {e}")
    
    fahrzeit_cache[ziel_adresse] = None
    return None
    
def hole_hallen_info(hallen_nr, spielplan_url):
    """Holt die Halleninformationen (Name + Adresse) von liga.nu."""
    if hallen_nr in hallen_cache:
        return hallen_cache[hallen_nr]
    
    fallback = f"Halle {hallen_nr}"
    try:
        response = requests.get(spielplan_url, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        
        hallen_link = soup.find("a", string=hallen_nr)
        if not hallen_link or not hallen_link.get("href"):
            hallen_cache[hallen_nr] = fallback
            return fallback
        
        hallen_url = hallen_link["href"]
        if not hallen_url.startswith("http"):
            base_url = spielplan_url.split("/cgi-bin/")[0]
            hallen_url = base_url + hallen_url
        
        hallen_response = requests.get(hallen_url, timeout=5)
        hallen_soup = BeautifulSoup(hallen_response.text, "html.parser")
        
        hallen_name, adresse = "", ""
        title_tag = hallen_soup.find("title")
        if title_tag:
            title_text = title_tag.get_text()
            if "(" in title_text:
                extracted_name = title_text.split("(")[0].strip()
                if extracted_name and "unbekannt" not in extracted_name.lower():
                    hallen_name = extracted_name
        
        adresse_header = hallen_soup.find("h2", string=lambda t: t and "adresse" in t.lower())
        if adresse_header:
            adresse_elem = adresse_header.find_next_sibling()
            if adresse_elem:
                adresse = adresse_elem.get_text(separator=" ", strip=True).split("[")[0].strip()
        
        result = ", ".join(filter(None, [hallen_name, adresse])) or fallback
        hallen_cache[hallen_nr] = result
        print(f"  → Halle {hallen_nr}: {result}")
        return result
        
    except Exception:
        hallen_cache[hallen_nr] = fallback
        return fallback

def erstelle_kalender(name, url, output, puffer_min=60, immer_fahrzeit_berechnen=False):
    """Erstellt einen Kalender für ein Team"""
    print(f"\n{'='*60}\nErstelle Kalender für: {name}\n{'='*60}")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        html = response.text
    except requests.exceptions.RequestException as e:
        print(f"✗ Fehler beim Abrufen: {e}")
        return False
    
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables: return False
    
    table = next((t for t in tables if any("mannschaft" in h.get_text(strip=True).lower() for h in t.find_all("th"))), tables[0])
    
    spiele, aktuelles_datum = [], None
    rows = table.select("tbody tr") if table.find("tbody") else table.select("tr")
    
    print("Extrahiere Spiele und berechne Zeiten...")
    
    for row in rows:
        tds = row.find_all("td")
        
        if len(tds) < 8: 
            continue
        
        # NEU: Extrahiere Spiel-Info aus dem Kürzel (4. Spalte, Index 3)
        # Das Kürzel hat ein title-Attribut mit dem Hover-Text
        spiel_info = None
        if len(tds) > 3:
            kuerzel_td = tds[3]
            # Prüfe, ob die Zelle ein title-Attribut hat (Hover-Text)
            if kuerzel_td.has_attr('title') and kuerzel_td.get('title').strip():
                spiel_info = kuerzel_td.get('title').strip()
                kuerzel_text = kuerzel_td.get_text(strip=True)
                if kuerzel_text:
                    print(f"  📋 Kürzel gefunden: '{kuerzel_text}' = {spiel_info}")
        
        # Extrahiere die Standard-Spalten (Text-Inhalte)
        cols = [td.get_text(strip=True) for td in tds]
        
        # Bei 9 Spalten (mit Kürzel): Tag, Datum, Zeit, Kürzel, Halle, Nr, Heim, Gast, Erg
        # Bei 8 Spalten (ohne Kürzel): Tag, Datum, Zeit, Halle, Nr, Heim, Gast, Erg
        if len(cols) >= 9:
            tag, datum_str, zeit, _, hallen_nr, spiel_nr, heim, gast, ergebnis = cols[:9]
        elif len(cols) >= 8:
            tag, datum_str, zeit, hallen_nr, spiel_nr, heim, gast, ergebnis = cols[:8]
        else:
            continue
        
        if datum_str: aktuelles_datum = datum_str
        if not aktuelles_datum or "spielfrei" in heim.lower() or "spielfrei" in gast.lower() or name not in f"{heim} {gast}": 
            continue

        hallen_info = hole_hallen_info(hallen_nr, url)
        spieltyp = "Heimspiel" if name in heim else "Auswärts"
        gegner = gast if spieltyp == "Heimspiel" else heim

        try:
            start = ZEITZONE.localize(datetime.strptime(f"{aktuelles_datum} {zeit.split()[0]}", "%d.%m.%Y %H:%M"))
            fahrzeit = hole_fahrzeit(hallen_info.split(',')[-1].strip()) if (spieltyp == "Auswärts" or immer_fahrzeit_berechnen) else 0
            
            spiele.append({
                "beginn": start, "gegner": gegner, "spieltyp": spieltyp, "ort": hallen_info,
                "fahrzeit": fahrzeit, "puffer_min": puffer_min, "spiel_info": spiel_info
            })
        except (ValueError, IndexError):
            continue
    
    print(f"✓ {len(spiele)} Spiele gefunden")
    
    cal = Calendar()
    if spiele:
        for s in spiele:
            e = Event()
            
            if s["spieltyp"] == "Heimspiel":
                e.name = f"🏠 {name} - {s['gegner']}"
                beschreibung_teams = f"{name} vs. {s['gegner']}"
            else:
                e.name = f"✈️ {s['gegner']} - {name}"
                beschreibung_teams = f"{s['gegner']} vs. {name}"
            
            e.begin = s["beginn"]
            e.location = s["ort"]
            e.duration = timedelta(hours=1, minutes=30)
            
            treffzeit_puffer = timedelta(minutes=s['puffer_min'])
            treffzeit_an_halle = s['beginn'] - treffzeit_puffer
            zeit_info = f"Treffzeit an der Halle: {treffzeit_an_halle.strftime('%H:%M Uhr')}"
            
            if s.get('fahrzeit'):
                fahrzeit_delta = timedelta(minutes=s['fahrzeit'])
                abfahrtszeit = treffzeit_an_halle - fahrzeit_delta
                zeit_info = (f"Abfahrt von Nümbrecht: {abfahrtszeit.strftime('%H:%M Uhr')}\n"
                             f"Voraussichtliche Fahrzeit: ca. {s['fahrzeit']} Minuten\n"
                             f"{zeit_info}")

            beschreibung = (f"Handballspiel ({s['spieltyp']})\n{beschreibung_teams}\n\n"
                           f"== Zeiten ==\n{zeit_info}\n\n"
                           f"== Ort ==\n{s['ort']}")
            
            # NEU: Spiel-Info im Infobereich anhängen
            if s.get('spiel_info'):
                beschreibung += f"\n\n== Hinweis ==\n{s['spiel_info']}"
            
            e.description = beschreibung
            cal.events.add(e)

    with open(output, "w", encoding="utf-8") as f: f.writelines(cal)
    print(f"✓ {output} erfolgreich erstellt")
    return True

# --- Hauptprogramm ---
if __name__ == "__main__":
    print("="*60 + "\nHANDBALL KALENDER GENERATOR\n" + "="*60)
    
    results = []
    for config in KALENDER_CONFIG:
        result = erstelle_kalender(
            name=config["name"],
            url=config["url"],
            output=config["output"],
            puffer_min=config.get("puffer_min", 60),
            immer_fahrzeit_berechnen=config.get("immer_fahrzeit_berechnen", False)
        )
        results.append(result)
    
    print(f"\n{'='*60}\nZUSAMMENFASSUNG\n{'='*60}")
    print(f"Erfolgreich: {sum(1 for r in results if r)} | Fehler: {sum(1 for r in results if not r)}")
    print(f"Hallen im Cache: {len(hallen_cache)} | Fahrzeiten im Cache: {len(fahrzeit_cache)}\n{'='*60}\n")
    sys.exit(0)

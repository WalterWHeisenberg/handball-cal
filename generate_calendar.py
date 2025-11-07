import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime, timedelta
import pytz
import sys
import urllib.parse
import time

# --- Konfiguration für mehrere Kalender ---
KALENDER_CONFIG = [
    {
        "name": "SSV Nümbrecht Handball",  # weibliche Jugend C
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424244",
        "output": "handball_wjc.ics"
    },
    {
        "name": "SSV Nümbrecht Handball",  # männliche Jugend D1
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424217",
        "output": "handball_mjd1.ics"
    },
    {
        "name": "SSV Nümbrecht Handball",  # männliche Jugend D2
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424113",
        "output": "handball_mjd2.ics"
    },
    {
        "name": "SSV Nümbrecht Handball III",  # Herren III
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424114",
        "output": "handball_h3.ics"
    },
    {
        "name": "SSV Nümbrecht Handball",  # weibliche Jugend B
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424406",
        "output": "handball_wjb.ics"
    }
]

# --- Globale Einstellungen ---
ZEITZONE = pytz.timezone("Europe/Berlin")
START_ADRESSE = "Heideweg 9, 51588 Nümbrecht"

# --- Caches für Performance ---
hallen_cache = {}
fahrzeit_cache = {}

def get_coords(adresse):
    """Wandelt eine Adresse in Geo-Koordinaten um."""
    try:
        # Nominatim benötigt einen User-Agent
        headers = {'User-Agent': 'HandballKalenderSkript/1.0'}
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(adresse)}&format=json"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data:
            return data[0]['lat'], data[0]['lon']
    except Exception:
        return None, None
    return None, None

def hole_fahrzeit(ziel_adresse):
    """Berechnet die Fahrzeit von der Startadresse zum Ziel in Minuten."""
    if ziel_adresse in fahrzeit_cache:
        return fahrzeit_cache[ziel_adresse]

    start_lat, start_lon = get_coords(START_ADRESSE)
    ziel_lat, ziel_lon = get_coords(ziel_adresse)
    
    # Kleine Pause, um die API nicht zu überlasten
    time.sleep(1) 

    if not all([start_lat, start_lon, ziel_lat, ziel_lon]):
        print(f"  ⚠ Koordinaten für Fahrzeit konnten nicht ermittelt werden.")
        return None

    try:
        # OSRM (Open Source Routing Machine) für die Routenberechnung verwenden
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{ziel_lon},{ziel_lat}?overview=false"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 'Ok':
            # Fahrzeit in Sekunden, umgerechnet in Minuten
            duration_minutes = int(data['routes'][0]['duration'] / 60)
            fahrzeit_cache[ziel_adresse] = duration_minutes
            print(f"  → Fahrzeit nach '{ziel_adresse.split(',')[0]}': {duration_minutes} min")
            return duration_minutes
    except Exception:
        pass # Bei Fehler einfach None zurückgeben
    
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

def erstelle_kalender(team_name, url, output_datei):
    """Erstellt einen Kalender für ein Team"""
    print(f"\n{'='*60}\nErstelle Kalender für: {team_name}\n{'='*60}")
    
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
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) < 8: continue
        
        tag, datum_str, zeit, hallen_nr, spiel_nr, heim, gast, ergebnis = cols[:8]
        if datum_str: aktuelles_datum = datum_str
        if not aktuelles_datum or "spielfrei" in heim.lower() or "spielfrei" in gast.lower() or team_name not in f"{heim} {gast}": continue

        hallen_info = hole_hallen_info(hallen_nr, url)
        spieltyp = "Heimspiel" if team_name in heim else "Auswärts"
        gegner = gast if spieltyp == "Heimspiel" else heim

        try:
            start = ZEITZONE.localize(datetime.strptime(f"{aktuelles_datum} {zeit.split()[0]}", "%d.%m.%Y %H:%M"))
            fahrzeit = hole_fahrzeit(hallen_info.split(',')[-1].strip()) if spieltyp == "Auswärts" else 0
            
            spiele.append({"beginn": start, "gegner": gegner, "spieltyp": spieltyp, "ort": hallen_info, "fahrzeit": fahrzeit})
        except (ValueError, IndexError):
            continue
    
    print(f"✓ {len(spiele)} Spiele gefunden")
    
    cal = Calendar()
    if spiele:
        for s in spiele:
            e = Event()
            
            if s["spieltyp"] == "Heimspiel":
                e.name = f"🏠 {team_name} - {s['gegner']}"
                beschreibung_teams = f"{team_name} vs. {s['gegner']}"
            else:
                e.name = f"✈️ {s['gegner']} - {team_name}"
                beschreibung_teams = f"{s['gegner']} vs. {team_name}"
            
            e.begin = s["beginn"]
            e.location = s["ort"]
            e.duration = timedelta(hours=1, minutes=30)
            
            # Zeitinformationen für die Beschreibung
            treffzeit_puffer = timedelta(hours=1)
            treffzeit_an_halle = s['beginn'] - treffzeit_puffer
            zeit_info = f"Treffzeit an der Halle: {treffzeit_an_halle.strftime('%H:%M Uhr')}"
            
            if s['spieltyp'] == 'Auswärts' and s.get('fahrzeit'):
                fahrzeit_delta = timedelta(minutes=s['fahrzeit'])
                abfahrtszeit = treffzeit_an_halle - fahrzeit_delta
                zeit_info = (f"Abfahrt von Nümbrecht: {abfahrtszeit.strftime('%H:%M Uhr')}\n"
                             f"Voraussichtliche Fahrzeit: ca. {s['fahrzeit']} Minuten\n"
                             f"{zeit_info}")

            e.description = (f"Handballspiel ({s['spieltyp']})\n{beschreibung_teams}\n\n"
                             f"== Zeiten ==\n{zeit_info}\n\n"
                             f"== Ort ==\n{s['ort']}")
            cal.events.add(e)

    with open(output_datei, "w", encoding="utf-8") as f: f.writelines(cal)
    print(f"✓ {output_datei} erfolgreich erstellt")
    return True

# --- Hauptprogramm ---
if __name__ == "__main__":
    print("="*60 + "\nHANDBALL KALENDER GENERATOR\n" + "="*60)
    results = [erstelle_kalender(**config) for config in KALENDER_CONFIG]
    print(f"\n{'='*60}\nZUSAMMENFASSUNG\n{'='*60}")
    print(f"Erfolgreich: {sum(1 for r in results if r)} | Fehler: {sum(1 for r in results if not r)}")
    print(f"Hallen im Cache: {len(hallen_cache)} | Fahrzeiten im Cache: {len(fahrzeit_cache)}\n{'='*60}\n")
    sys.exit(0)

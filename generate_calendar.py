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
        "name": "SSV Nümbrecht Handball", "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424244",
        "output": "handball_wjc.ics", "puffer_min": 75
    },
    {
        "name": "SSV Nümbrecht Handball", "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424217",
        "output": "handball_mjd1.ics", "puffer_min": 60
    },
    {
        "name": "SSV Nümbrecht Handball", "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424113",
        "output": "handball_mjd2.ics", "puffer_min": 60
    },
    {
        "name": "SSV Nümbrecht Handball III", "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424114",
        "output": "handball_h3.ics", "puffer_min": 60
    },
    {
        "name": "SSV Nümbrecht Handball", "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424406",
        "output": "handball_wjb.ics", "puffer_min": 60
    },
    {
        "name": "HSG Siebengebirge", "url": "HIER_DIE_KORREKTE_URL_EINFUEGEN", "output": "handball_hsg_siebengebirge.ics",
        "puffer_min": 60, "immer_fahrzeit_berechnen": True
    }
]

# --- Globale Einstellungen ---
ZEITZONE = pytz.timezone("Europe/Berlin")
START_ADRESSE = "Heideweg 9, 51588 Nümbrecht"

# --- Caches für Performance ---
hallen_cache, fahrzeit_cache = {}, {}

def get_coords(adresse):
    try:
        headers = {'User-Agent': 'HandballKalenderSkript/1.0'}
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(adresse)}&format=json"
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        if data: return data[0]['lat'], data[0]['lon']
    except Exception: pass
    return None, None

def hole_fahrzeit(ziel_adresse):
    if ziel_adresse in fahrzeit_cache: return fahrzeit_cache[ziel_adresse]
    start_lat, start_lon = get_coords(START_ADRESSE)
    ziel_lat, ziel_lon = get_coords(ziel_adresse)
    time.sleep(1)
    if not all([start_lat, start_lon, ziel_lat, ziel_lon]): return None
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{ziel_lon},{ziel_lat}?overview=false"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('code') == 'Ok':
            duration_minutes = int(data['routes'][0]['duration'] / 60)
            fahrzeit_cache[ziel_adresse] = duration_minutes
            print(f"  → Fahrzeit nach '{ziel_adresse.split(',')[0]}': {duration_minutes} min")
            return duration_minutes
    except Exception: pass
    return None
    
def hole_hallen_info(hallen_nr, spielplan_url):
    if hallen_nr in hallen_cache: return hallen_cache[hallen_nr]
    fallback = f"Halle {hallen_nr}"
    try:
        soup = BeautifulSoup(requests.get(spielplan_url, timeout=5).text, "html.parser")
        hallen_link = soup.find("a", string=hallen_nr)
        if not (hallen_link and hallen_link.get("href")): return fallback
        hallen_url = hallen_link["href"]
        if not hallen_url.startswith("http"): hallen_url = spielplan_url.split("/cgi-bin/")[0] + hallen_url
        
        hallen_soup = BeautifulSoup(requests.get(hallen_url, timeout=5).text, "html.parser")
        hallen_name, adresse = "", ""
        if title_tag := hallen_soup.find("title"):
            if "(" in (title_text := title_tag.get_text()):
                if extracted_name := title_text.split("(")[0].strip():
                    if "unbekannt" not in extracted_name.lower(): hallen_name = extracted_name
        if adresse_header := hallen_soup.find("h2", string=lambda t: t and "adresse" in t.lower()):
            if adresse_elem := adresse_header.find_next_sibling():
                adresse = adresse_elem.get_text(separator=" ", strip=True).split("[")[0].strip()
        
        result = ", ".join(filter(None, [hallen_name, adresse])) or fallback
        hallen_cache[hallen_nr] = result
        print(f"  → Halle {hallen_nr}: {result}")
        return result
    except Exception: return fallback

def erstelle_kalender(config):
    name, url, output = config["name"], config["url"], config["output"]
    puffer_min = config.get("puffer_min", 60)
    immer_fahrzeit = config.get("immer_fahrzeit_berechnen", False)

    print(f"\n{'='*60}\nErstelle Kalender für: {name} (Puffer: {puffer_min}min)\n{'='*60}")
    
    try: response = requests.get(url, timeout=10); html = response.text
    except Exception as e: print(f"✗ Fehler: {e}"); return False
    
    tables = BeautifulSoup(html, "html.parser").find_all("table")
    if not tables: return False
    table = next((t for t in tables if any("mannschaft" in h.text.lower() for h in t.find_all("th"))), tables[0])
    
    spiele, aktuelles_datum = [], None
    print("Extrahiere Spiele und berechne Zeiten...")
    
    for row in table.select("tbody tr"):
        tds = row.find_all("td") # Get all <td> elements
        cols = [c.get_text(strip=True) for c in tds]
        
        if len(cols) < 8: continue

        # --- NEU: Kürzel auslesen ---
        spiel_info = None
        if len(cols) >= 9:
            # Layout mit 9 Spalten: Tag, Datum, Zeit, Kürzel, Halle, Nr, Heim, Gast, Erg.
            kuerzel_td = tds[3]
            if title := kuerzel_td.get('title'):
                spiel_info = title.strip()
            
            # Variablen für den Rest zuweisen
            tag, datum_str, zeit, hallen_nr, spiel_nr, heim, gast, ergebnis = cols[0], cols[1], cols[2], cols[4], cols[5], cols[6], cols[7], cols[8]
        else:
            # Fallback auf altes 8-Spalten-Layout
            tag, datum_str, zeit, hallen_nr, spiel_nr, heim, gast, ergebnis = cols[:8]
        
        if datum_str: aktuelles_datum = datum_str
        if not aktuelles_datum or "spielfrei" in heim.lower() or "spielfrei" in gast.lower() or name not in f"{heim} {gast}": continue

        hallen_info = hole_hallen_info(hallen_nr, url)
        spieltyp = "Heimspiel" if name in heim else "Auswärts"
        gegner = gast if spieltyp == "Heimspiel" else heim

        try:
            start = ZEITZONE.localize(datetime.strptime(f"{aktuelles_datum} {zeit.split()[0]}", "%d.%m.%Y %H:%M"))
            fahrzeit = hole_fahrzeit(hallen_info.split(',')[-1].strip()) if spieltyp == "Auswärts" or immer_fahrzeit else 0
            
            spiele.append({
                "beginn": start, "gegner": gegner, "spieltyp": spieltyp, "ort": hallen_info,
                "fahrzeit": fahrzeit, "puffer_min": puffer_min, "spiel_info": spiel_info # NEU
            })
        except (ValueError, IndexError): continue
    
    print(f"✓ {len(spiele)} Spiele gefunden")
    
    cal = Calendar()
    for s in spiele:
        e, beschreibung_teams = Event(), ""
        if s["spieltyp"] == "Heimspiel":
            e.name = f"🏠 {name} - {s['gegner']}"; beschreibung_teams = f"{name} vs. {s['gegner']}"
        else:
            e.name = f"✈️ {s['gegner']} - {name}"; beschreibung_teams = f"{s['gegner']} vs. {name}"
        
        e.begin, e.location, e.duration = s["beginn"], s["ort"], timedelta(hours=1, minutes=30)
        
        treffzeit_an_halle = s['beginn'] - timedelta(minutes=s['puffer_min'])
        zeit_info = f"Treffzeit Halle: {treffzeit_an_halle.strftime('%H:%M Uhr')} ({s['puffer_min']} min vorher)"
        
        if s.get('fahrzeit'):
            abfahrtszeit = treffzeit_an_halle - timedelta(minutes=s['fahrzeit'])
            zeit_info = f"Abfahrt Nümbrecht: {abfahrtszeit.strftime('%H:%M Uhr')}\nFahrzeit: ca. {s['fahrzeit']} min\n{zeit_info}"
        
        # --- NEU: Beschreibung dynamisch zusammensetzen ---
        beschreibung = (f"Handballspiel ({s['spieltyp']})\n{beschreibung_teams}\n\n"
                        f"== Zeiten ==\n{zeit_info}\n\n"
                        f"== Ort ==\n{s['ort']}")
        
        if s.get('spiel_info'):
            beschreibung += f"\n\n== Info ==\n{s['spiel_info']}"

        e.description = beschreibung
        cal.events.add(e)

    with open(output, "w", encoding="utf-8") as f: f.writelines(cal)
    print(f"✓ {output} erfolgreich erstellt")
    return True

if __name__ == "__main__":
    print("="*60 + "\nHANDBALL KALENDER GENERATOR\n" + "="*60)
    results = [erstelle_kalender(config) for config in KALENDER_CONFIG]
    print(f"\n{'='*60}\nZUSAMMENFASSUNG\n{'='*60}\nErfolgreich: {sum(1 for r in results if r)} | Fehler: {sum(1 for r in results if not r)}")
    sys.exit(0)

import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime
import pytz
import sys

# --- Konfiguration ---
KALENDER_CONFIG = [
    {
        "name": "SSV Nümbrecht Handball",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424244",
        "output": "handball_wjc.ics"
    },
    {
        "name": "SSV Nümbrecht Handball",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424217",
        "output": "handball_mjd1.ics"
    },
    {
        "name": "SSV Nümbrecht Handball",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424113",
        "output": "handball_mjd2.ics"
    },
    {
        "name": "SSV Nümbrecht Handball III",
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424114",
        "output": "handball_h3.ics"
    }
]

ZEITZONE = pytz.timezone("Europe/Berlin")

# Cache für Hallen-Informationen, um wiederholte Abfragen zu vermeiden
hallen_cache = {}

def hole_hallen_info(hallen_nr, spielplan_url):
    """
    Holt die Halleninformationen (Name + Adresse) von liga.nu
    """
    if hallen_nr in hallen_cache:
        return hallen_cache[hallen_nr]
    
    # Fallback-Wert, falls nichts gefunden wird
    fallback = f"Halle {hallen_nr}"
    
    try:
        # Die Hallen-URL aus dem Spielplan-Link auf der Seite extrahieren
        # Normalerweise sind die Hallennummern verlinkt
        response = requests.get(spielplan_url, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Suche nach Link mit der Hallennummer
        hallen_link = soup.find("a", string=hallen_nr)
        if not hallen_link or not hallen_link.get("href"):
            hallen_cache[hallen_nr] = fallback
            return fallback
        
        # Vollständige URL konstruieren
        hallen_url = hallen_link["href"]
        if not hallen_url.startswith("http"):
            # Relative URL zu absoluter URL machen
            base_url = spielplan_url.split("/cgi-bin/")[0]
            hallen_url = base_url + hallen_url
        
        # Hallen-Detailseite abrufen
        hallen_response = requests.get(hallen_url, timeout=5)
        hallen_soup = BeautifulSoup(hallen_response.text, "html.parser")
        
        # Hallenname aus dem Titel oder Header extrahieren
        hallen_name = "Unbekannte Halle"
        title_tag = hallen_soup.find("title")
        if title_tag:
            # Format: "Hallenname (Nummer) - nuLiga"
            title_text = title_tag.get_text()
            if "(" in title_text:
                hallen_name = title_text.split("(")[0].strip()
        
        # Adresse extrahieren
        adresse = ""
        adresse_header = hallen_soup.find("h2", string=lambda t: t and "adresse" in t.lower())
        if adresse_header:
            # Die Adresse steht normalerweise direkt nach dem Header
            adresse_elem = adresse_header.find_next_sibling()
            if adresse_elem:
                adresse_text = adresse_elem.get_text(separator=" ", strip=True)
                # Entferne "[Routenplaner...]" und ähnliches
                adresse = adresse_text.split("[")[0].strip()
        
        # Ergebnis zusammensetzen
        if adresse:
            result = f"{hallen_name}, {adresse}"
        else:
            result = hallen_name
        
        hallen_cache[hallen_nr] = result
        return result
        
    except Exception as e:
        print(f"⚠ Konnte Hallen-Info für {hallen_nr} nicht abrufen: {e}")
        hallen_cache[hallen_nr] = fallback
        return fallback

def erstelle_kalender(team_name, url, output_datei):
    """Erstellt einen Kalender für ein Team"""
    
    print(f"\n{'='*60}")
    print(f"Erstelle Kalender für: {team_name}")
    print(f"{'='*60}")
    
    # Webseite abrufen
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        html = response.text
        print(f"✓ Webseite geladen")
    except requests.exceptions.RequestException as e:
        print(f"✗ Fehler beim Abrufen: {e}")
        return False
    
    # HTML parsen
    soup = BeautifulSoup(html, "html.parser")
    
    # Tabelle finden
    tables = soup.find_all("table")
    if not tables:
        print("✗ Keine Tabelle gefunden!")
        return False
    
    table = None
    for t in tables:
        headers = [th.get_text(strip=True) for th in t.find_all("th")]
        if any("mannschaft" in h.lower() or "datum" in h.lower() for h in headers):
            table = t
            break
    
    if not table:
        table = tables[0]
    
    # Spiele extrahieren
    spiele = []
    aktuelles_datum = None
    
    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]
    
    for row in rows:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        
        if len(cols) < 8:
            continue
        
        tag, datum_str, zeit, hallen_nr, spiel_nr, heim, gast, ergebnis = cols[:8]
        
        if datum_str:
            aktuelles_datum = datum_str
        
        if not aktuelles_datum:
            continue
        
        if "spielfrei" in heim.lower() or "spielfrei" in gast.lower():
            continue
        
        if team_name not in heim and team_name not in gast:
            continue
        
        # Hallen-Information abrufen
        hallen_info = hole_hallen_info(hallen_nr, url)
        
        # Gegner bestimmen
        if team_name in heim:
            gegner = gast
            ort = f"Heimspiel – {hallen_info}"
        else:
            gegner = heim
            ort = f"Auswärts – {hallen_info}"
        
        # Datum parsen
        try:
            zeit_bereinigt = zeit.split()[0] if zeit else "00:00"
            start = datetime.strptime(f"{aktuelles_datum} {zeit_bereinigt}", "%d.%m.%Y %H:%M")
            start = ZEITZONE.localize(start)
            
            spiele.append({
                "beginn": start,
                "gegner": gegner,
                "ort": ort,
            })
        except (ValueError, IndexError) as e:
            print(f"⚠ Fehler beim Parsen: {aktuelles_datum} {zeit}")
            continue
    
    print(f"✓ {len(spiele)} Spiele gefunden")
    
    # Kalender erstellen
    cal = Calendar()
    
    if spiele:
        for s in spiele:
            e = Event()
            e.name = f"{team_name} vs. {s['gegner']}" if "Heimspiel" in s["ort"] else f"{s['gegner']} vs. {team_name}"
            e.begin = s["beginn"]
            e.location = s["ort"]
            e.description = f"Handballspiel: {e.name}\nOrt: {s['ort']}"
            e.duration = {"hours": 1, "minutes": 30}
            cal.events.add(e)
    
    # Kalender speichern
    with open(output_datei, "w", encoding="utf-8") as f:
        f.writelines(cal)
    
    print(f"✓ {output_datei} erfolgreich erstellt")
    return True

# --- Hauptprogramm ---
print("="*60)
print("HANDBALL KALENDER GENERATOR")
print("="*60)

erfolg_counter = 0
fehler_counter = 0

for config in KALENDER_CONFIG:
    if erstelle_kalender(config["name"], config["url"], config["output"]):
        erfolg_counter += 1
    else:
        fehler_counter += 1

print(f"\n{'='*60}")
print(f"ZUSAMMENFASSUNG")
print(f"{'='*60}")
print(f"Erfolgreich erstellt: {erfolg_counter}")
print(f"Fehler: {fehler_counter}")
print(f"Hallen im Cache: {len(hallen_cache)}")
print(f"{'='*60}\n")

if fehler_counter > 0:
    print("⚠️ Es gab Fehler, aber bereits erstellte Kalender werden trotzdem gespeichert.")

sys.exit(0)

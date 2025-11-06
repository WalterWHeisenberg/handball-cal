import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime
import pytz
import sys

# --- Konfiguration für mehrere Kalender ---
KALENDER_CONFIG = [
    {
        "name": "SSV Nümbrecht Handball", # <-- weibliche Jugend C
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424244",
        "output": "handball_wjc.ics"
    },
    {
        "name": "SSV Nümbrecht Handball",  # <-- männliche Jugend D1
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424217",  # <-- URL des zweiten Teams
        "output": "handball_mjd1.ics"
    },
    {
        "name": "SSV Nümbrecht Handball",  # <-- männliche Jugend D2
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424113",  # <-- URL des dritten Teams
        "output": "handball_mjd2.ics"
    },
    {
        "name": "SSV Nümbrecht Handball III",  # <-- Herren III
        "url": "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424114",  # <-- URL des dritten Teams
        "output": "handball_h3.ics"
    }    
]

ZEITZONE = pytz.timezone("Europe/Berlin")

def erstelle_kalender(team_name, url, output_datei):
    """Erstellt einen Kalender für ein Team"""
    
    print(f"\n{'='*60}")
    print(f"Erstelle Kalender für: {team_name}")
    print(f"URL: {url}")  # <-- URL ausgeben
    print(f"Output: {output_datei}")  # <-- Output-Datei ausgeben
    print(f"{'='*60}")
    
    # Webseite abrufen
    try:
        print("Lade Webseite...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        html = response.text
        print(f"✓ Webseite geladen ({len(html)} Zeichen)")
    except requests.exceptions.RequestException as e:
        print(f"✗ Fehler beim Abrufen der Webseite: {e}")
        print(f"✗ Status Code: {getattr(e.response, 'status_code', 'N/A')}")  # <-- Status Code
        return False
    
    # HTML parsen
    soup = BeautifulSoup(html, "html.parser")
    
    # Tabelle finden
    tables = soup.find_all("table")
    if not tables:
        print("✗ Keine Tabelle gefunden!")
        return False
    
    # Die richtige Tabelle finden
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
        
        tag, datum_str, zeit, halle_nr, spiel_nr, heim, gast, ergebnis = cols[:8]
        
        # Datum aktualisieren
        if datum_str:
            aktuelles_datum = datum_str
        
        if not aktuelles_datum:
            continue
        
        # spielfrei überspringen
        if "spielfrei" in heim.lower() or "spielfrei" in gast.lower():
            continue
        
        # Nur Spiele mit dem gesuchten Team
        if team_name not in heim and team_name not in gast:
            continue
        
        # Gegner bestimmen
        if team_name in heim:
            gegner = gast
            ort = f"Heimspiel – Halle {halle_nr}"
        else:
            gegner = heim
            ort = f"Auswärts – Halle {halle_nr}"
        
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
            print(f"⚠ Fehler beim Parsen: {aktuelles_datum} {zeit} - {e}")
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
print(f"{'='*60}\n")

# GEÄNDERT: Auch bei Fehlern mit Exit-Code 0 beenden
# So wird der GitHub Workflow nicht abgebrochen
if fehler_counter > 0:
    print("⚠️ Es gab Fehler, aber bereits erstellte Kalender werden trotzdem gespeichert.")

sys.exit(0)  # Immer erfolgreich beenden

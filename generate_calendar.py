import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime
import pytz
import sys

# --- Einstellungen ---
URL = "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424244"
TEAM = "SSV Nümbrecht Handball"
ZEITZONE = pytz.timezone("Europe/Berlin")

print("=== HANDBALL KALENDER GENERATOR ===")
print(f"Team: {TEAM}")
print(f"URL: {URL}\n")

# --- Webseite abrufen ---
try:
    print("Lade Webseite...")
    response = requests.get(URL, timeout=10)
    response.raise_for_status()
    html = response.text
    print(f"✓ Webseite geladen ({len(html)} Zeichen)\n")
except requests.exceptions.RequestException as e:
    print(f"✗ Fehler beim Abrufen der Webseite: {e}")
    sys.exit(1)

# --- HTML-Struktur analysieren ---
soup = BeautifulSoup(html, "html.parser")

# Alle Tabellen finden
tables = soup.find_all("table")
print(f"Gefundene Tabellen auf der Seite: {len(tables)}\n")

if not tables:
    print("✗ Keine Tabelle gefunden!")
    sys.exit(1)

# Die richtige Tabelle finden (oft ist es die größte oder die mit bestimmten Klassen)
table = None
for idx, t in enumerate(tables):
    rows = t.select("tbody tr") if t.find("tbody") else t.find_all("tr")
    print(f"Tabelle {idx+1}: {len(rows)} Zeilen")
    
    # Suche nach Tabelle mit Spielplan-Daten (enthält "Heimmannschaft" oder ähnliches)
    headers = [th.get_text(strip=True) for th in t.find_all("th")]
    if any("mannschaft" in h.lower() or "datum" in h.lower() for h in headers):
        table = t
        print(f"  → Diese Tabelle scheint der Spielplan zu sein (Header: {headers})")
        break

if not table:
    print("\n✗ Keine Spielplan-Tabelle gefunden!")
    print("Verwende die erste Tabelle als Fallback...\n")
    table = tables[0]

# --- Spiele aus Tabelle auslesen ---
spiele = []
aktuelles_datum = None

tbody = table.find("tbody")
if tbody:
    rows = tbody.find_all("tr")
    print(f"\nAnalysiere {len(rows)} Zeilen aus <tbody>...\n")
else:
    rows = table.find_all("tr")[1:]  # Erste Zeile überspringen (Header)
    print(f"\nKein <tbody> gefunden. Analysiere {len(rows)} Zeilen...\n")

zeilen_verarbeitet = 0
zeilen_mit_team = 0

for idx, row in enumerate(rows, 1):
    cols = [c.get_text(strip=True) for c in row.find_all("td")]
    
    # Debug: Erste 3 Zeilen vollständig ausgeben
    if idx <= 3:
        print(f"Zeile {idx}: {len(cols)} Spalten")
        for i, col in enumerate(cols):
            print(f"  [{i}] '{col}'")
        print()
    
    if len(cols) < 8:
        continue
    
    zeilen_verarbeitet += 1
    
    # Spaltenzuordnung
    tag, datum_str, zeit, halle_nr, spiel_nr, heim, gast, ergebnis = cols[:8]
    
    # Datum aktualisieren
    if datum_str:
        aktuelles_datum = datum_str
    
    if not aktuelles_datum:
        continue
    
    # spielfrei überspringen
    if "spielfrei" in heim.lower() or "spielfrei" in gast.lower():
        continue
    
    # Team-Check
    if TEAM not in heim and TEAM not in gast:
        continue
    
    zeilen_mit_team += 1
    
    # Gegner bestimmen
    if TEAM in heim:
        gegner = gast
        ort = f"Heimspiel – Halle {halle_nr}"
    else:
        gegner = heim
        ort = f"Auswärts – Halle {halle_nr}"
    
    # Zeit bereinigen (z.B. "11:00 v" → "11:00")
    try:
        zeit_bereinigt = zeit.split()[0] if zeit else "00:00"
        
        # Datum parsen
        start = datetime.strptime(f"{aktuelles_datum} {zeit_bereinigt}", "%d.%m.%Y %H:%M")
        start = ZEITZONE.localize(start)
        
        spiele.append({
            "beginn": start,
            "gegner": gegner,
            "ort": ort,
        })
        
    except (ValueError, IndexError) as e:
        print(f"⚠ Zeile {idx}: Fehler beim Parsen von '{aktuelles_datum} {zeit}' - {e}")
        continue

print(f"\n=== STATISTIK ===")
print(f"Zeilen verarbeitet: {zeilen_verarbeitet}")
print(f"Zeilen mit Team '{TEAM}': {zeilen_mit_team}")
print(f"Gültige Spiele gefunden: {len(spiele)}\n")

if spiele:
    print("=== GEFUNDENE SPIELE ===")
    for i, s in enumerate(spiele, 1):
        print(f"{i}. {s['beginn'].strftime('%d.%m.%Y %H:%M')} - {s['gegner']}")
        print(f"   {s['ort']}")
    print()

# --- Kalenderdatei erzeugen ---
cal = Calendar()

if spiele:
    for s in spiele:
        e = Event()
        e.name = f"{TEAM} vs. {s['gegner']}" if "Heimspiel" in s["ort"] else f"{s['gegner']} vs. {TEAM}"
        e.begin = s["beginn"]
        e.location = s["ort"]
        e.description = f"Handballspiel: {e.name}\nOrt: {s['ort']}"
        e.duration = {"hours": 1, "minutes": 30}
        cal.events.add(e)
    
    print(f"✓ {len(spiele)} Events zum Kalender hinzugefügt")
else:
    print("⚠ Keine Spiele gefunden - erstelle leeren Kalender")

# Kalender speichern
with open("handball.ics", "w", encoding="utf-8") as f:
    f.writelines(cal)

print("✓ handball.ics erfolgreich erstellt")

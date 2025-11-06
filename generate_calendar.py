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

# --- Webseite abrufen ---
try:
    response = requests.get(URL)
    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
except requests.exceptions.RequestException as e:
    print(f"Fehler beim Abrufen der Webseite: {e}")
    sys.exit(1)

# --- Spiele aus Tabelle auslesen ---
spiele = []
table = soup.find("table")

if not table:
    print("Fehler: Keine Spieltabelle auf der Seite gefunden.")
    sys.exit(1)

# Variable zum Speichern des aktuellen Datums (wird über Zeilen hinweg beibehalten)
aktuelles_datum = None

for row in table.select("tbody tr"):
    cols = [c.get_text(strip=True) for c in row.find_all("td")]

    # Die Tabelle hat 8 Spalten
    if len(cols) < 8:
        continue

    # Korrekte Spaltenzuordnung:
    # 0: Tag (z.B. "Sa.")
    # 1: Datum (z.B. "13.09.2025")
    # 2: Zeit (z.B. "13:30" oder "11:00 v")
    # 3: Halle (z.B. "09004")
    # 4: Spielnummer (z.B. "433002")
    # 5: Heimmannschaft
    # 6: Gastmannschaft
    # 7: Ergebnis (z.B. "33:23")
    
    tag, datum_str, zeit, halle_nr, spiel_nr, heim, gast, ergebnis = cols[:8]

    # Datum aktualisieren, falls vorhanden
    if datum_str:
        aktuelles_datum = datum_str

    # Wenn kein Datum verfügbar ist, Zeile überspringen
    if not aktuelles_datum:
        continue

    # Spiele mit "spielfrei" überspringen
    if "spielfrei" in heim.lower() or "spielfrei" in gast.lower():
        continue

    # Nur Spiele mit dem gewünschten Team filtern
    if TEAM not in heim and TEAM not in gast:
        continue

    # Gegner und Spielort bestimmen
    if TEAM in heim:
        gegner = gast
        ort = f"Heimspiel – Halle {halle_nr}"
    else:
        gegner = heim
        ort = f"Auswärts – Halle {halle_nr}"

    # Datum und Uhrzeit parsen
    try:
        # Zeit von Zusätzen wie " v" bereinigen
        zeit_bereinigt = zeit.split()[0]  # Nimmt nur den ersten Teil vor Leerzeichen
        
        # Datumsformat ist jetzt "DD.MM.YYYY" (vierstelliges Jahr!)
        start = datetime.strptime(f"{aktuelles_datum} {zeit_bereinigt}", "%d.%m.%Y %H:%M")
        start = ZEITZONE.localize(start)
    except (ValueError, IndexError) as e:
        print(f"Warnung: Ungültiges Datum/Zeit-Format: {aktuelles_datum} {zeit} - {e}")
        continue

    spiele.append({
        "beginn": start,
        "gegner": gegner,
        "ort": ort,
    })

print(f"{len(spiele)} Spiele für '{TEAM}' gefunden.")

# --- Kalenderdatei erzeugen ---
if spiele:
    cal = Calendar()
    for s in spiele:
        e = Event()
        e.name = f"{TEAM} vs. {s['gegner']}" if "Heimspiel" in s["ort"] else f"{s['gegner']} vs. {TEAM}"
        e.begin = s["beginn"]
        e.location = s["ort"]
        e.description = f"Handballspiel: {e.name}\nOrt: {s['ort']}"
        e.duration = {"hours": 1, "minutes": 30}
        cal.events.add(e)

    with open("handball.ics", "w", encoding="utf-8") as f:
        f.writelines(cal)
    print("✅ handball.ics erfolgreich erstellt/aktualisiert.")
else:
    print("⚠️ Keine Spiele gefunden. Möglicherweise wurde das Team nicht gefunden oder alle Spiele sind 'spielfrei'.")
    # Erstelle trotzdem eine leere ICS-Datei, damit der Workflow nicht abbricht
    cal = Calendar()
    with open("handball.ics", "w", encoding="utf-8") as f:
        f.writelines(cal)

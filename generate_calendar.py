# generate_calendar.py

import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime
import pytz

# --- Einstellungen ---
URL = "https://hvnb-handball.liga.nu/cgi-bin/WebObjects/nuLigaHBDE.woa/wa/groupPage?displayTyp=vorrunde&displayDetail=meetings&championship=OB+25%2F26&group=424244"
TEAM = "SSV Nümbrecht Handball"
ZEITZONE = pytz.timezone("Europe/Berlin")

# --- Webseite abrufen ---
try:
    html = requests.get(URL).text
    soup = BeautifulSoup(html, "html.parser")
except requests.exceptions.RequestException as e:
    print(f"Fehler beim Abrufen der Webseite: {e}")
    exit(1)

# --- Spiele aus Tabelle auslesen ---
spiele = []
# Die Tabelle hat keine "result-set"-Klasse mehr. Wir suchen die erste Tabelle im Dokument.
table = soup.find("table")

if not table:
    print("Fehler: Keine Spieltabelle auf der Seite gefunden.")
    exit(1)

# Die relevanten Daten sind in <tbody>-Zeilen
for row in table.select("tbody tr"):
    cols = [c.get_text(strip=True) for c in row.find_all("td")]

    # Die Struktur der Tabelle hat sich geändert und hat nun mehr Spalten.
    if len(cols) < 8:
        continue

    # Neue Spaltenzuordnung
    datum_str, zeit, halle_nr, _, heim, gast, tore, ergebnis = cols[:8]

    # Nur Spiele mit dem gewünschten Team filtern
    if TEAM not in heim and TEAM not in gast:
        continue

    # Gegner und Spielort bestimmen
    if TEAM in heim:
        gegner = gast
        # Der Hallenname ist komplexer zu parsen; wir verwenden vorerst die Hallennummer.
        ort = f"Heimspiel – Halle {halle_nr}"
    else:
        gegner = heim
        ort = f"Auswärts – Halle {halle_nr}"

    # Datum und Uhrzeit parsen (das Format hat sich geändert)
    try:
        # Das Format ist jetzt z.B. "Sa, 05.10.25". Wir extrahieren das Datum.
        start_datum = datum_str.split(',')[1].strip()
        # Das Jahr ist nur zweistellig (%y statt %Y)
        start = datetime.strptime(f"{start_datum} {zeit}", "%d.%m.%y %H:%M")
        start = ZEITZONE.localize(start)
    except (ValueError, IndexError):
        # Zeilen ohne gültiges Datum werden übersprungen
        continue

    spiele.append({
        "beginn": start,
        "gegner": gegner,
        "ort": ort,
    })

print(f"{len(spiele)} Spiele für {TEAM} gefunden.")

# --- Kalenderdatei erzeugen ---
if spiele:
    cal = Calendar()
    for s in spiele:
        e = Event()
        e.name = f"{TEAM} vs. {s['gegner']}" if "Heimspiel" in s["ort"] else f"{s['gegner']} vs. {TEAM}"
        e.begin = s["beginn"]
        e.location = s["ort"]
        e.description = f"Handballspiel: {e.name}\nOrt: {s['ort']}"
        # Ungefähre Spieldauer
        e.duration = {"hours": 1, "minutes": 30}
        cal.events.add(e)

    with open("handball.ics", "w", encoding="utf-8") as f:
        f.writelines(cal)
    print("✅ handball.ics erfolgreich erstellt.")
else:
    print("Keine Spiele gefunden, um einen Kalender zu erstellen.")


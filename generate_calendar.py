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
html = requests.get(URL).text
soup = BeautifulSoup(html, "html.parser")

# --- Spiele aus Tabelle auslesen ---
# Auf liga.nu liegen die Spieltermine meist in einer Tabelle mit <table class="result-set">
spiele = []

for row in soup.select("table.result-set tr"):
    cols = [c.get_text(strip=True) for c in row.find_all("td")]
    if len(cols) < 6:
        continue

    datum, zeit, halle, heim, gast, ergebnis = cols[:6]

    # Nur Spiele mit unserem Team
    if TEAM not in heim and TEAM not in gast:
        continue

    # Gegner bestimmen
    if TEAM in heim:
        gegner = gast
        ort = "Heimspiel – " + halle
    else:
        gegner = heim
        ort = "Auswärts – " + halle

    # Datum + Uhrzeit parsen
    try:
        start = datetime.strptime(datum + " " + zeit, "%d.%m.%Y %H:%M")
        start = ZEITZONE.localize(start)
    except ValueError:
        continue  # ggf. unvollständige Angaben überspringen

    spiele.append({
        "beginn": start,
        "gegner": gegner,
        "ort": ort,
    })

print(f"{len(spiele)} Spiele für {TEAM} gefunden.")

# --- Kalenderdatei erzeugen ---
cal = Calendar()

for s in spiele:
    e = Event()
    e.name = f"{TEAM} vs. {s['gegner']}" if "Heimspiel" in s["ort"] else f"{s['gegner']} vs. {TEAM}"
    e.begin = s["beginn"]
    e.location = s["ort"]
    e.description = f"Handballspiel: {e.name}\nOrt: {s['ort']}"
    e.duration = {"hours": 1, "minutes": 30}  # ca. Spieldauer
    cal.events.add(e)

with open("handball.ics", "w", encoding="utf-8") as f:
    f.writelines(cal)

print("✅ handball.ics erfolgreich erstellt.")

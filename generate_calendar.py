import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime
import pytz
import sys

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
    
    # Fallback: Nur die Hallennummer
    fallback = f"Halle {hallen_nr}"
    
    try:
        # Die Hallen-URL aus dem Spielplan-Link auf der Seite extrahieren
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
            base_url = spielplan_url.split("/cgi-bin/")[0]
            hallen_url = base_url + hallen_url
        
        # Hallen-Detailseite abrufen
        hallen_response = requests.get(hallen_url, timeout=5)
        hallen_soup = BeautifulSoup(hallen_response.text, "html.parser")
        
        # Hallenname aus dem Titel extrahieren
        hallen_name = ""
        title_tag = hallen_soup.find("title")
        if title_tag:
            title_text = title_tag.get_text()
            # Format: "Hallenname (Nummer) - nuLiga"
            if "(" in title_text:
                extracted_name = title_text.split("(")[0].strip()
                # Nur verwenden wenn es NICHT "Unbekannte Halle" ist
                if extracted_name and "unbekannt" not in extracted_name.lower():
                    hallen_name = extracted_name
        
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
        if hallen_name and adresse:
            # Beides vorhanden: Name + Adresse
            result = f"{hallen_name}, {adresse}"
        elif adresse:
            # Nur Adresse (Hallenname war "Unbekannte Halle" oder leer)
            result = adresse
        elif hallen_name:
            # Nur Name (keine Adresse gefunden)
            result = hallen_name
        else:
            # Nichts gefunden: Fallback auf Hallennummer
            result = fallback
        
        hallen_cache[hallen_nr] = result
        print(f"  → Halle {hallen_nr}: {result}")
        return result
        
    except Exception as e:
        # Bei Fehler: Nur Hallennummer verwenden
        hallen_cache[hallen_nr] = fallback
        return fallback

def erstelle_kalender(team_name, url, output_datei):
    """Erstellt einen Kalender für ein Team"""
    
    print(f"\n{'='*60}")
    print(f"Erstelle Kalender für: {team_name}")
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
    
    print("Extrahiere Spiele und Hallen-Informationen...")
    
    for row in rows:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        
        if len(cols) < 8:
            continue
        
        tag, datum_str, zeit, hallen_nr, spiel_nr, heim, gast, ergebnis = cols[:8]
        
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
        
        # Hallen-Information abrufen (mit Cache)
        hallen_info = hole_hallen_info(hallen_nr, url)
        
        # Gegner und Spieltyp bestimmen
        if team_name in heim:
            gegner = gast
            spieltyp = "Heimspiel"
            ort = hallen_info  # Nur Hallen-Info, ohne "Heimspiel –"
        else:
            gegner = heim
            spieltyp = "Auswärts"
            ort = hallen_info  # Nur Hallen-Info, ohne "Auswärts –"
        
        # Datum parsen
        try:
            zeit_bereinigt = zeit.split()[0] if zeit else "00:00"
            start = datetime.strptime(f"{aktuelles_datum} {zeit_bereinigt}", "%d.%m.%Y %H:%M")
            start = ZEITZONE.localize(start)
            
            spiele.append({
                "beginn": start,
                "gegner": gegner,
                "spieltyp": spieltyp,
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
            # SUMMARY: Heimteam - Gastteam (immer in dieser Reihenfolge)
            if s["spieltyp"] == "Heimspiel":
                e.name = f"{team_name} - {s['gegner']}"
                beschreibung_teams = f"{team_name} - {s['gegner']}"
            else:
                e.name = f"{s['gegner']} - {team_name}"
                beschreibung_teams = f"{s['gegner']} - {team_name}"  # KORRIGIERT: Gleiche Reihenfolge
            
            e.begin = s["beginn"]
            e.location = s["ort"]
            e.description = f"Handballspiel ({s['spieltyp']})\n{beschreibung_teams}\n\nOrt: {s['ort']}"
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

sys.exit(0)  # Immer erfolgreich beenden

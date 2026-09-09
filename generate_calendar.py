import os
import re
import sys
import time
import tempfile
import unicodedata
from datetime import timedelta
from math import atan2, ceil, cos, radians, sin, sqrt
from pathlib import Path
from urllib.parse import quote

import requests
from ics import Calendar
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# GLOBALE EINSTELLUNGEN
# ============================================================

START_ADRESSE = "Gouvieuxstraße 2, 51588 Nümbrecht, Deutschland"

# Verzeichnis für die erzeugten Kalender.
# Standardmäßig wird in das aktuelle Arbeitsverzeichnis geschrieben.
OUTPUT_VERZEICHNIS = Path(
    os.environ.get("OUTPUT_VERZEICHNIS", ".")
).resolve()

HTTP_TIMEOUT_SEKUNDEN = 15

# Bei einer reinen Luftlinien-Schätzung wird die Entfernung mit diesem
# Faktor auf eine angenäherte Straßenentfernung hochgerechnet.
STRASSENFAKTOR_LUFTLINIE = 1.25

# Durchschnittsgeschwindigkeit für die Fahrzeitschätzung.
GESCHAETZTE_GESCHWINDIGKEIT_KMH = 45

# Nominatim soll möglichst nicht öfter als einmal pro Sekunde
# aufgerufen werden.
NOMINATIM_MINDESTABSTAND_SEKUNDEN = 1.1

# Kontaktadresse kann in GitHub als Variable oder Secret gesetzt werden.
# Beispiel:
# NOMINATIM_CONTACT_EMAIL=max.mustermann@example.de
NOMINATIM_CONTACT_EMAIL = os.environ.get(
    "NOMINATIM_CONTACT_EMAIL",
    ""
).strip()

# Verhalten, wenn bei einem Kalender keine passenden Spiele gefunden werden:
#
# True:
#   Der Kalender gilt als fehlerhaft und die GitHub Action endet mit Exit-Code 1.
#
# False:
#   Der Kalender wird übersprungen, die Verarbeitung gilt aber nicht als Fehler.
KEINE_TREFFER_SIND_FEHLER = True


# ============================================================
# OPENROUTESERVICE
# ============================================================

# GitHub:
# Settings -> Secrets and variables -> Actions -> ORS_API_KEY
ORS_API_KEY = os.environ.get("ORS_API_KEY", "").strip()

ORS_GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
ORS_DIRECTIONS_URL = (
    "https://api.openrouteservice.org/v2/directions/driving-car"
)


# ============================================================
# ZEITZONENMODI
# ============================================================

# Verwenden, wenn handball.net eine lokale deutsche Uhrzeit liefert,
# diese aber fälschlich als UTC kennzeichnet.
ZEITMODUS_LOKAL_FALSCH_ALS_UTC = "lokal_falsch_als_utc"

# Verwenden, wenn der Feed echte UTC-Zeiten liefert.
ZEITMODUS_ECHTES_UTC = "echtes_utc"

# Zeitangabe unverändert übernehmen.
ZEITMODUS_UNVERAENDERT = "unveraendert"


# ============================================================
# KALENDERKONFIGURATION
# ============================================================

# fahrzeit_modus:
#
# "auswaerts":
#   Fahrzeit nur für erkannte Auswärtsspiele berechnen.
#
# "immer":
#   Fahrzeit für jedes Spiel mit Hallenadresse berechnen.
#
# "nie":
#   Keine Fahrzeit berechnen.
#
# Die beiden männlichen D-Jugendmannschaften sind getrennt aufgeführt:
# - männliche D1: Teamkalender 95226
# - männliche D2: Ligakalender 10014

HANDBALLNET_CONFIG = [
    {
        "bezeichnung": "Herren 3",
        "url": "https://www.handball.net/kalender/liga/8053.ics",
        "filter_team": "Nümbrecht",
        "output": "handball_h3.ics",
        "puffer_min": 60,
        "fahrzeit_modus": "auswaerts",
        "zeitmodus": ZEITMODUS_LOKAL_FALSCH_ALS_UTC,
    },
    {
        "bezeichnung": "Männliche D-Jugend 1",
        "url": "https://www.handball.net/kalender/team/95226.ics",
        "filter_team": "Nümbrecht",
        "output": "handball_mjd1.ics",
        "puffer_min": 60,
        "fahrzeit_modus": "auswaerts",
        "zeitmodus": ZEITMODUS_LOKAL_FALSCH_ALS_UTC,
    },
    {
        "bezeichnung": "Männliche D-Jugend 2",
        "url": (
            "https://www.handball.net/kalender/liga/10014.ics"
            "?season_id=2627&fed_id=148"
        ),
        "filter_team": "Nümbrecht",
        "output": "handball_mjd2.ics",
        "puffer_min": 60,
        "fahrzeit_modus": "auswaerts",
        "zeitmodus": ZEITMODUS_LOKAL_FALSCH_ALS_UTC,
    },
    {
        "bezeichnung": "Weibliche B-Jugend",
        "url": (
            "https://www.handball.net/kalender/liga/10012.ics"
            "?season_id=2627&fed_id=148"
        ),
        "filter_team": "Nümbrecht",
        "output": "handball_wjb.ics",
        "puffer_min": 60,
        "fahrzeit_modus": "auswaerts",
        "zeitmodus": ZEITMODUS_LOKAL_FALSCH_ALS_UTC,
    },
    {
        "bezeichnung": "Weibliche C-Jugend HSG",
        "url": (
            "https://www.handball.net/kalender/liga/6108.ics"
            "?season_id=2627&fed_id=20"
        ),
        "filter_team": "Köln",
        "output": "handball_wjc-hsg.ics",
        "puffer_min": 60,
        "fahrzeit_modus": "immer",
        "zeitmodus": ZEITMODUS_LOKAL_FALSCH_ALS_UTC,
    },
]


# ============================================================
# MANUELLE HALLEN-OVERRIDES
# ============================================================

# Schlüsselwörter immer kleingeschrieben angeben.
#
# Beispiel:
#
# HALLEN_KOORDINATEN_MANUELL = {
#     "wiehl": (50.9530, 7.4550),
#     "schulzentrum nümbrecht": (50.9040, 7.5400),
# }

HALLEN_KOORDINATEN_MANUELL = {
    # "wiehl": (50.9530, 7.4550),
}


# ============================================================
# STATUSÜBERSETZUNGEN
# ============================================================

STATUS_UEBERSETZUNG = {
    "pendiente": "Ausstehend",
    "finalizado": "Beendet",
    "en curso": "Laufend",
    "en juego": "Laufend",
    "aplazado": "Verschoben",
    "cancelado": "Abgesagt",
    "suspendido": "Abgebrochen",
}


# ============================================================
# TITELTRENNER
# ============================================================

TITEL_TRENNER = [
    " - ",
    " – ",
    " — ",
    " vs. ",
    " vs ",
    " : ",
]


# ============================================================
# CACHES UND LAUFZEITSTATUS
# ============================================================

koordinaten_cache = {}
fahrzeit_cache = {}

letzter_nominatim_aufruf = 0.0


# ============================================================
# HTTP-SESSION
# ============================================================

def erstelle_http_session():
    """
    Erstellt eine HTTP-Session mit Wiederholungsversuchen bei
    vorübergehenden Server- oder Verbindungsproblemen.
    """
    session = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    user_agent = "HandballKalenderGenerator/2.0"

    if NOMINATIM_CONTACT_EMAIL:
        user_agent += f" ({NOMINATIM_CONTACT_EMAIL})"

    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "*/*",
    })

    return session


HTTP_SESSION = erstelle_http_session()


# ============================================================
# ALLGEMEINE HILFSFUNKTIONEN
# ============================================================

def normalisiere_text(text):
    """
    Normalisiert Text für robuste Vergleiche.

    Dabei bleiben Umlaute erhalten. Groß- und Kleinschreibung werden
    über casefold() vereinheitlicht.
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", str(text))
    text = re.sub(r"\s+", " ", text).strip()

    return text.casefold()


def cache_schluessel(text):
    """
    Erzeugt einen einheitlichen Cache-Schlüssel.
    """
    return normalisiere_text(text)


def kuerze_text(text, laenge=60):
    """
    Kürzt Texte ausschließlich für die Konsolenausgabe.
    """
    if not text:
        return ""

    text = re.sub(r"\s+", " ", str(text)).strip()

    if len(text) <= laenge:
        return text

    return text[: laenge - 3] + "..."


def extrahiere_plz(adresse):
    """
    Extrahiert die erste deutsche fünfstellige Postleitzahl.
    """
    if not adresse:
        return None

    match = re.search(r"\b(\d{5})\b", adresse)

    return match.group(1) if match else None


def uebersetze_status(text):
    """
    Übersetzt bekannte spanische Statusangaben ins Deutsche.
    """
    if not text:
        return ""

    ergebnis = str(text)

    for spanisch, deutsch in STATUS_UEBERSETZUNG.items():
        ergebnis = re.sub(
            rf"(?<!\w){re.escape(spanisch)}(?!\w)",
            deutsch,
            ergebnis,
            flags=re.IGNORECASE,
        )

    return ergebnis.strip()


def zerlege_titel(titel):
    """
    Versucht, den Veranstaltungstitel in Heim- und Gastmannschaft
    aufzuteilen.
    """
    if not titel:
        return None, None

    titel_normalisiert = re.sub(r"\s+", " ", str(titel)).strip()

    for trenner in TITEL_TRENNER:
        if trenner.casefold() in titel_normalisiert.casefold():
            pattern = re.compile(
                re.escape(trenner),
                flags=re.IGNORECASE,
            )

            teile = pattern.split(titel_normalisiert, maxsplit=1)

            if len(teile) == 2:
                heim = teile[0].strip()
                gast = teile[1].strip()

                if heim and gast:
                    return heim, gast

    return None, None


def team_passt(filter_team, titel, beschreibung=""):
    """
    Prüft, ob das gesuchte Team zu einem Spiel gehört.

    Der Hallenort wird bewusst nicht durchsucht. Dadurch wird verhindert,
    dass beispielsweise der Filter 'Köln' nur deshalb anschlägt, weil
    die Halle in Köln liegt.
    """
    filter_normalisiert = normalisiere_text(filter_team)

    if not filter_normalisiert:
        return False

    heim, gast = zerlege_titel(titel)

    if heim and gast:
        return (
            filter_normalisiert in normalisiere_text(heim)
            or filter_normalisiert in normalisiere_text(gast)
        )

    # Fallback für ungewöhnlich formatierte Titel.
    fallback_text = normalisiere_text(
        f"{titel or ''} {beschreibung or ''}"
    )

    return filter_normalisiert in fallback_text


def bestimme_spieltyp(titel, filter_team):
    """
    Bestimmt, ob es sich um ein Heim- oder Auswärtsspiel handelt.
    """
    heim, gast = zerlege_titel(titel)

    if not heim or not gast:
        return "unbekannt"

    filter_normalisiert = normalisiere_text(filter_team)

    heim_passt = filter_normalisiert in normalisiere_text(heim)
    gast_passt = filter_normalisiert in normalisiere_text(gast)

    if heim_passt and not gast_passt:
        return "heim"

    if gast_passt and not heim_passt:
        return "auswaerts"

    return "unbekannt"


# ============================================================
# ZEITZONENBEHANDLUNG
# ============================================================

def korrigiere_zeitzone(arrow_zeit, zeitmodus):
    """
    Behandelt die Zeitangaben des ICS-Feeds.

    lokal_falsch_als_utc:
        Eine als UTC markierte Uhrzeit wird als deutsche Lokalzeit
        interpretiert. Die angezeigte Uhrzeit bleibt gleich.

    echtes_utc:
        Eine echte UTC-Zeit wird nach Europe/Berlin umgerechnet.

    unveraendert:
        Die Zeitangabe wird nicht verändert.
    """
    if arrow_zeit is None:
        return None

    if zeitmodus == ZEITMODUS_UNVERAENDERT:
        return arrow_zeit

    if zeitmodus == ZEITMODUS_ECHTES_UTC:
        return arrow_zeit.to("Europe/Berlin")

    if zeitmodus == ZEITMODUS_LOKAL_FALSCH_ALS_UTC:
        offset = arrow_zeit.utcoffset()

        if offset is not None and offset.total_seconds() == 0:
            return arrow_zeit.replace(tzinfo="Europe/Berlin")

        return arrow_zeit

    raise ValueError(f"Unbekannter Zeitmodus: {zeitmodus}")


# ============================================================
# ADRESSBEHANDLUNG
# ============================================================

def bereinige_adresse(adresse):
    """
    Entfernt typische Zusatzinformationen aus Hallenadressen.

    Die Bereinigung wird nur als Fallback verwendet. Zunächst wird immer
    versucht, die unveränderte Originaladresse zu geokodieren.
    """
    if not adresse:
        return ""

    original = str(adresse).strip()
    bereinigt = original

    # Zeilenumbrüche und typische Trenner vereinheitlichen.
    bereinigt = bereinigt.replace("\r", " ")
    bereinigt = bereinigt.replace("\n", ", ")

    # Telefonnummern, Faxnummern, E-Mail-Adressen und URLs entfernen.
    bereinigt = re.sub(
        r"\b(?:Tel(?:efon)?|Fax)\.?\s*:?\s*[\d\s/+()\-]+",
        "",
        bereinigt,
        flags=re.IGNORECASE,
    )

    bereinigt = re.sub(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        "",
        bereinigt,
    )

    bereinigt = re.sub(
        r"https?://\S+",
        "",
        bereinigt,
        flags=re.IGNORECASE,
    )

    # Mehrfache Kommas und Leerzeichen bereinigen.
    bereinigt = re.sub(r"\s+", " ", bereinigt)
    bereinigt = re.sub(r"\s*,\s*", ", ", bereinigt)
    bereinigt = re.sub(r"(,\s*){2,}", ", ", bereinigt)
    bereinigt = bereinigt.strip(" ,;-")

    if (
        bereinigt
        and "deutschland" not in bereinigt.casefold()
        and "germany" not in bereinigt.casefold()
    ):
        bereinigt += ", Deutschland"

    if bereinigt != original:
        print(
            "  🔧 Adresse für Fallback bereinigt:\n"
            f"     vorher: {kuerze_text(original, 90)}\n"
            f"     nachher: {kuerze_text(bereinigt, 90)}"
        )

    return bereinigt


def koordinaten_gueltig(lat, lon):
    """
    Prüft, ob gültige Koordinaten vorhanden sind.
    """
    if lat is None or lon is None:
        return False

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False

    return -90 <= lat <= 90 and -180 <= lon <= 180


def postleitzahl_passt(gefundene_plz, erwartete_plz):
    """
    Vergleicht gefundene und erwartete Postleitzahl.

    Wenn keine PLZ erwartet wird, gilt der Treffer als passend.
    """
    if not erwartete_plz:
        return True

    if not gefundene_plz:
        return False

    return str(gefundene_plz).strip() == str(erwartete_plz).strip()


# ============================================================
# GEOCODING: OPENROUTESERVICE
# ============================================================

def geocode_ors(adresse, erwartete_plz=None):
    """
    Geokodiert eine Adresse über OpenRouteService.

    Bei vorhandener erwarteter PLZ wird ausschließlich ein Treffer mit
    übereinstimmender PLZ akzeptiert.
    """
    if not ORS_API_KEY or not adresse:
        return None, None

    params = {
        "api_key": ORS_API_KEY,
        "text": adresse,
        "boundary.country": "DE",
        "size": 5,
    }

    try:
        response = HTTP_SESSION.get(
            ORS_GEOCODE_URL,
            params=params,
            timeout=HTTP_TIMEOUT_SEKUNDEN,
        )
        response.raise_for_status()
        daten = response.json()

    except requests.exceptions.RequestException as exc:
        print(f"  ⚠ ORS-Geocoding fehlgeschlagen: {exc}")
        return None, None

    except ValueError as exc:
        print(f"  ⚠ ORS lieferte kein gültiges JSON: {exc}")
        return None, None

    features = daten.get("features", [])

    if not features:
        return None, None

    passende_features = []

    for feature in features:
        properties = feature.get("properties", {})
        gefundene_plz = properties.get("postalcode")

        if postleitzahl_passt(gefundene_plz, erwartete_plz):
            passende_features.append(feature)

    if erwartete_plz and not passende_features:
        print(
            f"  ⚠ ORS: kein Treffer mit der erwarteten PLZ "
            f"{erwartete_plz}"
        )
        return None, None

    feature = passende_features[0] if passende_features else features[0]
    geometry = feature.get("geometry", {})
    koordinaten = geometry.get("coordinates", [])

    if len(koordinaten) < 2:
        return None, None

    lon, lat = koordinaten[0], koordinaten[1]

    if not koordinaten_gueltig(lat, lon):
        return None, None

    print(
        f"  ✓ ORS-Geocoding erfolgreich: "
        f"{kuerze_text(adresse, 65)}"
    )

    return float(lat), float(lon)


# ============================================================
# GEOCODING: NOMINATIM
# ============================================================

def warte_auf_nominatim():
    """
    Stellt einen Mindestabstand zwischen Nominatim-Aufrufen sicher.
    """
    global letzter_nominatim_aufruf

    vergangen = time.monotonic() - letzter_nominatim_aufruf
    wartezeit = NOMINATIM_MINDESTABSTAND_SEKUNDEN - vergangen

    if wartezeit > 0:
        time.sleep(wartezeit)

    letzter_nominatim_aufruf = time.monotonic()


def geocode_nominatim(adresse, erwartete_plz=None):
    """
    Geokodiert eine Adresse über Nominatim.

    Bei einer erwarteten PLZ werden nur Treffer mit identischer PLZ
    übernommen.
    """
    if not adresse:
        return None, None

    warte_auf_nominatim()

    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": adresse,
        "format": "jsonv2",
        "countrycodes": "de",
        "limit": 5,
        "addressdetails": 1,
    }

    if NOMINATIM_CONTACT_EMAIL:
        params["email"] = NOMINATIM_CONTACT_EMAIL

    try:
        response = HTTP_SESSION.get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT_SEKUNDEN,
        )
        response.raise_for_status()
        daten = response.json()

    except requests.exceptions.RequestException as exc:
        print(f"  ⚠ Nominatim fehlgeschlagen: {exc}")
        return None, None

    except ValueError as exc:
        print(f"  ⚠ Nominatim lieferte kein gültiges JSON: {exc}")
        return None, None

    if not daten:
        return None, None

    passende_treffer = []

    for treffer in daten:
        adressdaten = treffer.get("address", {})
        gefundene_plz = adressdaten.get("postcode")

        if postleitzahl_passt(gefundene_plz, erwartete_plz):
            passende_treffer.append(treffer)

    if erwartete_plz and not passende_treffer:
        print(
            f"  ⚠ Nominatim: kein Treffer mit der erwarteten PLZ "
            f"{erwartete_plz}"
        )
        return None, None

    treffer = passende_treffer

    lat = treffer.get("lat")
    lon = treffer.get("lon")

    if not koordinaten_gueltig(lat, lon):
        return None, None

    print(
        f"  ✓ Nominatim-Geocoding erfolgreich: "
        f"{kuerze_text(adresse, 65)}"
    )

    return float(lat), float(lon)


# ============================================================
# GEOCODING: PHOTON
# ============================================================

def geocode_photon(adresse, erwartete_plz=None):
    """
    Letzter Geocoding-Fallback über Photon.

    Es werden ausschließlich deutsche Treffer akzeptiert. Bei bekannter
    PLZ muss auch diese übereinstimmen.
    """
    if not adresse:
        return None, None

    url = f"https://photon.komoot.io/api/?q={quote(adresse)}&limit=5"

    try:
        response = HTTP_SESSION.get(
            url,
            timeout=HTTP_TIMEOUT_SEKUNDEN,
        )
        response.raise_for_status()
        daten = response.json()

    except requests.exceptions.RequestException as exc:
        print(f"  ⚠ Photon fehlgeschlagen: {exc}")
        return None, None

    except ValueError as exc:
        print(f"  ⚠ Photon lieferte kein gültiges JSON: {exc}")
        return None, None

    features = daten.get("features", [])

    for feature in features:
        properties = feature.get("properties", {})

        countrycode = normalisiere_text(
            properties.get("countrycode", "")
        )

        if countrycode and countrycode not in {"de", "deu"}:
            continue

        gefundene_plz = properties.get("postcode")

        if not postleitzahl_passt(gefundene_plz, erwartete_plz):
            continue

        geometry = feature.get("geometry", {})
        koordinaten = geometry.get("coordinates", [])

        if len(koordinaten) < 2:
            continue

        lon, lat = koordinaten[0], koordinaten[1]

        if not koordinaten_gueltig(lat, lon):
            continue

        print(
            f"  ✓ Photon-Geocoding erfolgreich: "
            f"{kuerze_text(adresse, 65)}"
        )

        return float(lat), float(lon)

    if erwartete_plz:
        print(
            f"  ⚠ Photon: kein deutscher Treffer mit PLZ "
            f"{erwartete_plz}"
        )

    return None, None


# ============================================================
# ZENTRALE KOORDINATENERMITTLUNG
# ============================================================

def get_coords(adresse):
    """
    Ermittelt Koordinaten über folgende Reihenfolge:

    1. manueller Override
    2. ORS mit Originaladresse
    3. Nominatim mit Originaladresse
    4. ORS mit bereinigter Adresse
    5. Nominatim mit bereinigter Adresse
    6. Photon mit bereinigter Adresse
    """
    if not adresse:
        return None, None

    schluessel = cache_schluessel(adresse)

    if schluessel in koordinaten_cache:
        return koordinaten_cache[schluessel]

    adresse_normalisiert = normalisiere_text(adresse)

    for stichwort, koordinaten in HALLEN_KOORDINATEN_MANUELL.items():
        if normalisiere_text(stichwort) in adresse_normalisiert:
            lat, lon = koordinaten

            if koordinaten_gueltig(lat, lon):
                koordinaten_cache[schluessel] = (
                    float(lat),
                    float(lon),
                )

                print(
                    f"  ✓ Manueller Hallen-Override verwendet: "
                    f"{stichwort}"
                )

                return koordinaten_cache[schluessel]

    erwartete_plz = extrahiere_plz(adresse)

    # 1. ORS mit Originaladresse
    lat, lon = geocode_ors(adresse, erwartete_plz)

    if koordinaten_gueltig(lat, lon):
        koordinaten_cache[schluessel] = (lat, lon)
        return lat, lon

    # 2. Nominatim mit Originaladresse
    lat, lon = geocode_nominatim(adresse, erwartete_plz)

    if koordinaten_gueltig(lat, lon):
        koordinaten_cache[schluessel] = (lat, lon)
        return lat, lon

    bereinigte_adresse = bereinige_adresse(adresse)

    # Bereinigte Adresse nur erneut prüfen, wenn sie sich tatsächlich
    # von der Originaladresse unterscheidet.
    if normalisiere_text(bereinigte_adresse) != normalisiere_text(adresse):

        # 3. ORS mit bereinigter Adresse
        lat, lon = geocode_ors(
            bereinigte_adresse,
            erwartete_plz,
        )

        if koordinaten_gueltig(lat, lon):
            koordinaten_cache[schluessel] = (lat, lon)
            return lat, lon

        # 4. Nominatim mit bereinigter Adresse
        lat, lon = geocode_nominatim(
            bereinigte_adresse,
            erwartete_plz,
        )

        if koordinaten_gueltig(lat, lon):
            koordinaten_cache[schluessel] = (lat, lon)
            return lat, lon

    # 5. Photon als letzter Fallback
    photon_adresse = bereinigte_adresse or adresse

    lat, lon = geocode_photon(
        photon_adresse,
        erwartete_plz,
    )

    if koordinaten_gueltig(lat, lon):
        koordinaten_cache[schluessel] = (lat, lon)
        return lat, lon

    print(
        f"  ✗ Keine verlässlichen Koordinaten gefunden: "
        f"{kuerze_text(adresse, 75)}"
    )

    koordinaten_cache[schluessel] = (None, None)

    return None, None


# ============================================================
# ENTFERNUNGSBERECHNUNG
# ============================================================

def haversine_km(lat1, lon1, lat2, lon2):
    """
    Berechnet die Luftlinienentfernung zweier Koordinaten.
    """
    erdradius_km = 6371.0

    lat1 = radians(float(lat1))
    lon1 = radians(float(lon1))
    lat2 = radians(float(lat2))
    lon2 = radians(float(lon2))

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)))

    return erdradius_km * c


# ============================================================
# ROUTING: OPENROUTESERVICE
# ============================================================

def route_ors(start_lat, start_lon, ziel_lat, ziel_lon):
    """
    Berechnet die Fahrzeit über OpenRouteService.
    """
    if not ORS_API_KEY:
        return None

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = {
        "coordinates": [
            [float(start_lon), float(start_lat)],
            [float(ziel_lon), float(ziel_lat)],
        ],
        "instructions": False,
    }

    try:
        response = HTTP_SESSION.post(
            ORS_DIRECTIONS_URL,
            json=body,
            headers=headers,
            timeout=HTTP_TIMEOUT_SEKUNDEN,
        )
        response.raise_for_status()
        daten = response.json()

        routen = daten.get("routes", [])

        if not routen:
            return None

        summary = routen[0].get("summary", {})
        dauer_sekunden = summary.get("duration")

        if dauer_sekunden is None:
            return None

        return max(1, ceil(float(dauer_sekunden) / 60))

    except requests.exceptions.RequestException as exc:
        print(f"  ⚠ ORS-Routing fehlgeschlagen: {exc}")
        return None

    except (ValueError, TypeError, KeyError, IndexError) as exc:
        print(f"  ⚠ Ungültige ORS-Routingantwort: {exc}")
        return None


# ============================================================
# ROUTING: OSRM
# ============================================================

def route_osrm(start_lat, start_lon, ziel_lat, ziel_lon):
    """
    Fallback-Routing über den öffentlichen OSRM-Demo-Server.
    """
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{float(start_lon)},{float(start_lat)};"
        f"{float(ziel_lon)},{float(ziel_lat)}"
        "?overview=false&steps=false"
    )

    try:
        response = HTTP_SESSION.get(
            url,
            timeout=HTTP_TIMEOUT_SEKUNDEN,
        )
        response.raise_for_status()
        daten = response.json()

        if daten.get("code") != "Ok":
            return None

        routen = daten.get("routes", [])

        if not routen:
            return None

        dauer_sekunden = routen[0].get("duration")

        if dauer_sekunden is None:
            return None

        return max(1, ceil(float(dauer_sekunden) / 60))

    except requests.exceptions.RequestException as exc:
        print(f"  ⚠ OSRM-Routing fehlgeschlagen: {exc}")
        return None

    except (ValueError, TypeError, KeyError, IndexError) as exc:
        print(f"  ⚠ Ungültige OSRM-Routingantwort: {exc}")
        return None


# ============================================================
# FAHRZEIT
# ============================================================

def fahrzeit_plausibel(dauer_minuten, luftlinie_km):
    """
    Prüft die Fahrzeit anhand einer impliziten Durchschnittsgeschwindigkeit.

    Bei kurzen Strecken wird eine niedrige Durchschnittsgeschwindigkeit
    akzeptiert, da Stadtverkehr realistisch sein kann.
    """
    if dauer_minuten is None:
        return False

    if dauer_minuten <= 0:
        return False

    if luftlinie_km <= 0:
        return True

    implizierte_kmh = luftlinie_km / (dauer_minuten / 60)

    # Extrem hohe Durchschnittsgeschwindigkeiten sind immer verdächtig.
    if implizierte_kmh > 130:
        return False

    # Eine sehr geringe Geschwindigkeit wird erst ab einer Luftlinie
    # von mehr als 10 km als unplausibel eingestuft.
    if luftlinie_km > 10 and implizierte_kmh < 15:
        return False

    return True


def schaetze_fahrzeit(luftlinie_km):
    """
    Schätzt die Fahrzeit aus der Luftlinienentfernung.
    """
    geschaetzte_strassenstrecke_km = (
        luftlinie_km * STRASSENFAKTOR_LUFTLINIE
    )

    dauer_minuten = ceil(
        geschaetzte_strassenstrecke_km
        / GESCHAETZTE_GESCHWINDIGKEIT_KMH
        * 60
    )

    return max(5, dauer_minuten)


def hole_fahrzeit(ziel_adresse):
    """
    Ermittelt die Fahrzeit von der globalen Startadresse zur Zielhalle.
    """
    if not ziel_adresse:
        return None

    schluessel = cache_schluessel(ziel_adresse)

    if schluessel in fahrzeit_cache:
        return fahrzeit_cache[schluessel]

    start_lat, start_lon = get_coords(START_ADRESSE)
    ziel_lat, ziel_lon = get_coords(ziel_adresse)

    if not koordinaten_gueltig(start_lat, start_lon):
        print("  ⚠ Startadresse konnte nicht geokodiert werden.")
        fahrzeit_cache[schluessel] = None
        return None

    if not koordinaten_gueltig(ziel_lat, ziel_lon):
        print("  ⚠ Zieladresse konnte nicht geokodiert werden.")
        fahrzeit_cache[schluessel] = None
        return None

    luftlinie_km = haversine_km(
        start_lat,
        start_lon,
        ziel_lat,
        ziel_lon,
    )

    dauer_minuten = route_ors(
        start_lat,
        start_lon,
        ziel_lat,
        ziel_lon,
    )
    quelle = "ORS"

    if dauer_minuten is None:
        dauer_minuten = route_osrm(
            start_lat,
            start_lon,
            ziel_lat,
            ziel_lon,
        )
        quelle = "OSRM"

    if not fahrzeit_plausibel(dauer_minuten, luftlinie_km):
        if dauer_minuten is not None:
            implizierte_kmh = (
                luftlinie_km / (dauer_minuten / 60)
                if dauer_minuten > 0
                else 0
            )

            print(
                f"  ⚠ Unplausible Fahrzeit von {quelle}: "
                f"{dauer_minuten} Minuten bei "
                f"{luftlinie_km:.1f} km Luftlinie "
                f"({implizierte_kmh:.0f} km/h)"
            )

        dauer_minuten = schaetze_fahrzeit(luftlinie_km)
        quelle = "Schätzung"

    fahrzeit_cache[schluessel] = dauer_minuten

    print(
        f"  → Fahrzeit {quelle}: {dauer_minuten} Minuten "
        f"({luftlinie_km:.1f} km Luftlinie)"
    )

    return dauer_minuten


# ============================================================
# FAHRZEITMODUS
# ============================================================

def soll_fahrzeit_berechnet_werden(
    fahrzeit_modus,
    spieltyp,
    ort,
):
    """
    Entscheidet anhand der Kalenderkonfiguration, ob eine Fahrzeit
    berechnet werden soll.
    """
    if not ort:
        return False

    if fahrzeit_modus == "nie":
        return False

    if fahrzeit_modus == "immer":
        return True

    if fahrzeit_modus == "auswaerts":
        return spieltyp in {"auswaerts", "unbekannt"}

    raise ValueError(
        f"Unbekannter Fahrzeitmodus: {fahrzeit_modus}"
    )


# ============================================================
# ICS-DOWNLOAD
# ============================================================

def lade_ics_feed(url):
    """
    Lädt einen ICS-Feed und gibt dessen Text zurück.
    """
    try:
        response = HTTP_SESSION.get(
            url,
            timeout=HTTP_TIMEOUT_SEKUNDEN,
        )
        response.raise_for_status()

    except requests.exceptions.RequestException as exc:
        print(f"✗ Fehler beim Abrufen des ICS-Feeds: {exc}")
        return None

    try:
        return response.content.decode("utf-8-sig")

    except UnicodeDecodeError:
        encoding = response.apparent_encoding or "utf-8"

        try:
            return response.content.decode(
                encoding,
                errors="replace",
            )
        except (LookupError, UnicodeDecodeError):
            return response.text


# ============================================================
# KALENDERDATEI SCHREIBEN
# ============================================================

def schreibe_kalender_atomisch(kalender, zielpfad):
    """
    Schreibt einen Kalender zunächst in eine temporäre Datei und ersetzt
    danach die Zieldatei.

    Dadurch wird vermieden, dass bei einem Schreibfehler eine vorhandene
    Kalenderdatei beschädigt oder geleert wird.
    """
    zielpfad = Path(zielpfad)
    zielpfad.parent.mkdir(parents=True, exist_ok=True)

    temp_datei = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=zielpfad.parent,
            prefix=f".{zielpfad.name}.",
            suffix=".tmp",
            delete=False,
        ) as datei:
            temp_datei = Path(datei.name)
            datei.writelines(kalender.serialize_iter())

        os.replace(temp_datei, zielpfad)

    except OSError:
        if temp_datei and temp_datei.exists():
            temp_datei.unlink(missing_ok=True)

        raise


# ============================================================
# BESCHREIBUNG ERWEITERN
# ============================================================

def erstelle_zusatzbeschreibung(
    ort,
    beginn,
    puffer_min,
    spieltyp,
    fahrzeit_modus,
):
    """
    Erstellt die zusätzlichen Angaben zu Halle, Treffzeit und Abfahrt.
    """
    zeilen = []

    if ort:
        zeilen.append(f"Halle: {ort}")

    if beginn is None:
        return zeilen

    treffzeit = beginn - timedelta(minutes=puffer_min)

    zeilen.append(
        f"Treffzeit an der Halle: "
        f"{treffzeit.strftime('%H:%M Uhr')}"
    )

    if soll_fahrzeit_berechnet_werden(
        fahrzeit_modus,
        spieltyp,
        ort,
    ):
        fahrzeit = hole_fahrzeit(ort)

        if fahrzeit is not None:
            abfahrtszeit = treffzeit - timedelta(
                minutes=fahrzeit
            )

            zeilen.insert(
                0,
                f"Abfahrt von Nümbrecht: "
                f"{abfahrtszeit.strftime('%H:%M Uhr')}",
            )

            zeilen.insert(
                1,
                f"Voraussichtliche Fahrzeit: "
                f"ca. {fahrzeit} Minuten",
            )

    return zeilen


# ============================================================
# EINZELNEN HANDBALLKALENDER VERARBEITEN
# ============================================================

def verarbeite_handballnet_kalender(config):
    """
    Lädt, filtert und erweitert einen handball.net-Kalender.
    """
    bezeichnung = config["bezeichnung"]
    url = config["url"]
    filter_team = config["filter_team"]
    output = config["output"]

    puffer_min = int(config.get("puffer_min", 60))
    fahrzeit_modus = config.get(
        "fahrzeit_modus",
        "auswaerts",
    )
    zeitmodus = config.get(
        "zeitmodus",
        ZEITMODUS_UNVERAENDERT,
    )

    output_pfad = OUTPUT_VERZEICHNIS / output

    print()
    print("=" * 70)
    print(f"Kalender: {bezeichnung}")
    print(f"Teamfilter: {filter_team}")
    print(f"Ausgabe: {output_pfad}")
    print("=" * 70)

    ics_text = lade_ics_feed(url)

    if not ics_text:
        return {
            "erfolg": False,
            "bezeichnung": bezeichnung,
            "treffer": 0,
            "fehler": "ICS-Feed konnte nicht geladen werden",
        }

    try:
        quell_cal = Calendar(ics_text)

    except Exception as exc:
        print(f"✗ ICS-Feed konnte nicht geparst werden: {exc}")

        return {
            "erfolg": False,
            "bezeichnung": bezeichnung,
            "treffer": 0,
            "fehler": "ICS-Feed konnte nicht geparst werden",
        }

    print(
        f"  → {len(quell_cal.events)} Spiele im Feed gefunden"
    )

    ziel_cal = Calendar()
    treffer = 0

    # Sortierung dient einer nachvollziehbaren Konsolenausgabe.
    # Falls ein Termin keinen Beginn hat, wird er nach hinten sortiert.
    events = sorted(
        quell_cal.events,
        key=lambda event: (
            event.begin is None,
            event.begin.isoformat() if event.begin else "",
            event.name or "",
        ),
    )

    for event in events:
        titel = (event.name or "").strip()
        beschreibung_original = uebersetze_status(
            event.description or ""
        )
        ort = (event.location or "").strip()

        if not team_passt(
            filter_team,
            titel,
            beschreibung_original,
        ):
            continue

        treffer += 1

        try:
            event.begin = korrigiere_zeitzone(
                event.begin,
                zeitmodus,
            )

            if event.end is not None:
                event.end = korrigiere_zeitzone(
                    event.end,
                    zeitmodus,
                )

        except (ValueError, AttributeError) as exc:
            print(
                f"  ⚠ Zeitzone konnte nicht korrigiert werden: "
                f"{titel}: {exc}"
            )

        spieltyp = bestimme_spieltyp(
            titel,
            filter_team,
        )

        if spieltyp == "unbekannt":
            print(
                f"  ⚠ Heim/Gast nicht eindeutig erkannt: "
                f"{titel}"
            )

        zusatzzeilen = erstelle_zusatzbeschreibung(
            ort=ort,
            beginn=event.begin,
            puffer_min=puffer_min,
            spieltyp=spieltyp,
            fahrzeit_modus=fahrzeit_modus,
        )

        beschreibungsteile = []

        if beschreibung_original:
            beschreibungsteile.append(
                beschreibung_original.strip()
            )

        if zusatzzeilen:
            beschreibungsteile.append(
                "== Zeiten & Ort ==\n"
                + "\n".join(zusatzzeilen)
            )

        event.description = "\n\n".join(
            beschreibungsteile
        ).strip()

        event.location = ort

        ziel_cal.events.add(event)

        print(
            f"  ✓ {titel} "
            f"({spieltyp}, "
            f"{event.begin.format('DD.MM.YYYY HH:mm') if event.begin else 'ohne Termin'})"
        )

    if treffer == 0:
        print(
            f"  ⚠ Keine Spiele für den Teamfilter "
            f"'{filter_team}' gefunden."
        )

        print("  → Beispieltitel aus dem Feed:")

        for event in events[:5]:
            print(
                f"     - {event.name or '(ohne Titel)'}"
            )

        print(
            "  → Eine eventuell vorhandene Kalenderdatei "
            "wird nicht überschrieben."
        )

        return {
            "erfolg": not KEINE_TREFFER_SIND_FEHLER,
            "bezeichnung": bezeichnung,
            "treffer": 0,
            "fehler": (
                "Keine passenden Spiele gefunden"
                if KEINE_TREFFER_SIND_FEHLER
                else None
            ),
        }

    try:
        schreibe_kalender_atomisch(
            ziel_cal,
            output_pfad,
        )

    except OSError as exc:
        print(
            f"✗ Kalenderdatei konnte nicht geschrieben werden: "
            f"{exc}"
        )

        return {
            "erfolg": False,
            "bezeichnung": bezeichnung,
            "treffer": treffer,
            "fehler": "Kalenderdatei konnte nicht geschrieben werden",
        }

    print(
        f"✓ {treffer} Spiele übernommen: {output_pfad}"
    )

    return {
        "erfolg": True,
        "bezeichnung": bezeichnung,
        "treffer": treffer,
        "fehler": None,
    }


# ============================================================
# KONFIGURATION PRÜFEN
# ============================================================

def pruefe_konfiguration():
    """
    Prüft die Kalenderkonfiguration vor der Verarbeitung.
    """
    fehler = []
    verwendete_outputs = set()

    erlaubte_fahrzeitmodi = {
        "auswaerts",
        "immer",
        "nie",
    }

    erlaubte_zeitmodi = {
        ZEITMODUS_LOKAL_FALSCH_ALS_UTC,
        ZEITMODUS_ECHTES_UTC,
        ZEITMODUS_UNVERAENDERT,
    }

    erforderliche_felder = {
        "bezeichnung",
        "url",
        "filter_team",
        "output",
    }

    for nummer, config in enumerate(
        HANDBALLNET_CONFIG,
        start=1,
    ):
        fehlende_felder = erforderliche_felder - config.keys()

        if fehlende_felder:
            fehler.append(
                f"Konfiguration {nummer}: fehlende Felder "
                f"{sorted(fehlende_felder)}"
            )
            continue

        output = config["output"]

        if output in verwendete_outputs:
            fehler.append(
                f"Konfiguration {nummer}: doppelte Ausgabedatei "
                f"'{output}'"
            )

        verwendete_outputs.add(output)

        if not str(output).lower().endswith(".ics"):
            fehler.append(
                f"Konfiguration {nummer}: Ausgabe muss auf "
                f"'.ics' enden"
            )

        fahrzeit_modus = config.get(
            "fahrzeit_modus",
            "auswaerts",
        )

        if fahrzeit_modus not in erlaubte_fahrzeitmodi:
            fehler.append(
                f"Konfiguration {nummer}: unbekannter "
                f"Fahrzeitmodus '{fahrzeit_modus}'"
            )

        zeitmodus = config.get(
            "zeitmodus",
            ZEITMODUS_UNVERAENDERT,
        )

        if zeitmodus not in erlaubte_zeitmodi:
            fehler.append(
                f"Konfiguration {nummer}: unbekannter "
                f"Zeitmodus '{zeitmodus}'"
            )

        try:
            puffer_min = int(config.get("puffer_min", 60))

            if puffer_min < 0:
                raise ValueError

        except (TypeError, ValueError):
            fehler.append(
                f"Konfiguration {nummer}: ungültiger "
                f"Zeitpuffer"
            )

    return fehler


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():
    """
    Startet die Verarbeitung aller konfigurierten Kalender.
    """
    print("=" * 70)
    print("HANDBALL-KALENDER-GENERATOR")
    print("=" * 70)
    print(f"Startadresse: {START_ADRESSE}")
    print(f"Ausgabeverzeichnis: {OUTPUT_VERZEICHNIS}")

    if ORS_API_KEY:
        print(
            "✓ ORS_API_KEY gefunden – OpenRouteService wird "
            "als primäre Quelle verwendet."
        )
    else:
        print(
            "⚠ Kein ORS_API_KEY gefunden – Geocoding und Routing "
            "verwenden die öffentlichen Fallback-Dienste."
        )

    konfigurationsfehler = pruefe_konfiguration()

    if konfigurationsfehler:
        print()
        print("✗ Fehler in der Kalenderkonfiguration:")

        for fehler in konfigurationsfehler:
            print(f"  - {fehler}")

        return 1

    ergebnisse = []

    for config in HANDBALLNET_CONFIG:
        try:
            ergebnis = verarbeite_handballnet_kalender(
                config
            )

        except Exception as exc:
            # Letztes Sicherheitsnetz, damit die weiteren Kalender
            # trotzdem verarbeitet werden.
            print(
                f"✗ Unerwarteter Fehler bei "
                f"'{config.get('bezeichnung', 'Unbekannt')}': "
                f"{exc}"
            )

            ergebnis = {
                "erfolg": False,
                "bezeichnung": config.get(
                    "bezeichnung",
                    "Unbekannt",
                ),
                "treffer": 0,
                "fehler": f"Unerwarteter Fehler: {exc}",
            }

        ergebnisse.append(ergebnis)

    erfolgreiche_kalender = [
        ergebnis
        for ergebnis in ergebnisse
        if ergebnis["erfolg"]
    ]

    fehlerhafte_kalender = [
        ergebnis
        for ergebnis in ergebnisse
        if not ergebnis["erfolg"]
    ]

    print()
    print("=" * 70)
    print("ZUSAMMENFASSUNG")
    print("=" * 70)

    for ergebnis in ergebnisse:
        status = "✓" if ergebnis["erfolg"] else "✗"

        zeile = (
            f"{status} {ergebnis['bezeichnung']}: "
            f"{ergebnis} Spiele"
        )

        if ergebnis["fehler"]:
            zeile += f" – {ergebnis['fehler']}"

        print(zeile)

    print("-" * 70)
    print(
        f"Erfolgreich: {len(erfolgreiche_kalender)} | "
        f"Fehler: {len(fehlerhafte_kalender)}"
    )
    print(
        f"Koordinaten im Cache: {len(koordinaten_cache)} | "
        f"Fahrzeiten im Cache: {len(fahrzeit_cache)}"
    )
    print("=" * 70)

    # Sobald ein Kalender fehlschlägt, erhält die GitHub Action
    # einen Fehlerstatus. Erfolgreich erzeugte Kalender bleiben erhalten.
    if fehlerhafte_kalender:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

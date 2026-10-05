"""
Fetcher für die Luftdaten des Umweltbundesamtes via REST-API.
Dokumentation des UBA: 
http://www.uba.de/m99517de 
https://luftdaten.umweltbundesamt.de/api/air-data/v4/doc

Die API-Abfrage liefert die Daten ganzjährig in MEZ, die Abfrage arbeitet daher
konsequent in MEZ und nicht der Systemzeit.

Inhalt:
* Festlegung von URL, Abfragezeiträumen und Stationszuordnung für aktuelle Werte und Prognosen
* Unterfunktion zum Abruf der UBA-Stationen für aktuelle Werte und Prognosen
* Unterfunktion zum Auffinden der neuesten Messwerte
* Unterfunktion zum Erstellen der Prognosereihen
* Einstieg Scheduler: Datenupdate wird bei Fehler übersprungen
* Hauptfunktion zum Datenupdate
* main mit Startprozessen und Schedule
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
import schedule

from config import STATION, STATION_O3, STATION_SO2, UBA_TIMEOUT

#Logger mit Rotating File Handler
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    handlers=[
        RotatingFileHandler(
            "Logging_Files/Logger_uba.log",
            maxBytes=1_000_000,   #maximal 1 MB pro Log-Datei
            backupCount=10,       #10 Logs werden archiviert
            encoding="utf-8",
        )
    ],
)

# Abfrage URL für aktuelle und Prognosewerte
URL_CURRENT = "https://luftdaten.umweltbundesamt.de/api/air-data/v4/airquality/json"
URL_FORECAST = "https://luftdaten.umweltbundesamt.de/api/air-data/v4/airqualityforecast/json"

# JSON im gleichen Verzeichnis
JSON_PATH = Path(__file__).parent / "airdata.json"

# Abfragezeitraum mit 2h Puffer zu UBA_TIMEOUT in config.py, damit nach einem Ausfall wieder aufgeholt wird.
WINDOW_HOURS = UBA_TIMEOUT + 2

#Zuordnung der einzelnen Schadstoffe zu Stations-ID und Schadstoff-ID laut UBA-Dokumentation
POLLUTANTS = {
    "PM2_5": (STATION,     9),
    "PM10":  (STATION,     1),
    "NO2":   (STATION,     5),
    "O3":    (STATION_O3,  3),
    "SO2":   (STATION_SO2, 4),
}

# Prognosen liegen nur für PM2.5, PM10, NO2 und Ozon vor, nicht für SO2
FORECAST_POLLUTANTS = {
    "PM2_5": (STATION,     9),
    "PM10":  (STATION,     1),
    "NO2":   (STATION,     5),
    "O3":    (STATION_O3,  3),
}

# Definition fehlender Werte
EMPTY = {"zeit": None, "wert": None, "lqi": None, "lqi_float": None}

# --- Hilfsfunktion Abruf aller benötigten Stationen
# +++ erstellt mit KI-Hilfe
# jede Station nur einmal abrufen, die API liefert alle Schadstoffe der Station in einem Durchgang
# Bei Fehler wird für die Station ein leeres dict eingetragen
def fetch_stations(url, params, pollutants):
    station_data = {}   # Zwischenspeicher: Station -> Zeitreihe
    for station, comp_id in pollutants.values():
        if station in station_data:
            continue   # Station bereits abgerufen, weiter mit dem nächsten Schadstoff
        try:
            response = requests.get(url, params={**params, "station": station}, timeout=10)
            response.raise_for_status()
            station_data[station] = response.json().get("data", {}).get(station, {})
        except requests.RequestException as error:
            logging.warning("Station %s nicht abrufbar: %s", station, error)
            station_data[station] = {}
    return station_data

# --- Hilfsfunktion Auswertung aktueller Daten
# +++ erstellt mit KI-Hilfe
# Rückwärtssuche vom jüngsten Eintrag: die jüngste Stunde liegt an der Stunden-
# grenze bereits vor, einzelne Komponenten fehlen darin aber noch.
# Der Schlüssel der Zeitreihe ist der Beginn der Messstunde, Position 0 des
# Eintrags ihr Ende ("date end" nach UBA-Konvention). Zurückgegeben wird das
# Ende, weil uba_veraltet() in functions.py damit das Alter prüft. Die
# Sortierung über den Schlüssel bleibt gültig, weil Beginn und Ende dieselbe
# Reihenfolge ergeben.
def latest_value(series, comp_id):
    for timestamp in sorted(series, reverse=True):
        entry = series[timestamp]
        for component in entry[3:]:   # ab Position 3 folgen die Schadstoffe
            if len(component) >= 3 and component[0] == comp_id \
                    and component[1] is not None:
                # Konvertierung des Gleitkomma-LQI der API von string zu float
                try:
                    lqi_float = float(str(component[3]).replace(",", "."))
                except (IndexError, ValueError):
                    lqi_float = None   # bei fehlendem oder fehlerhaftem Wert None zurückgeben
                return {"zeit": entry[0],        # Position 0: Zeitstempel Ende der Messung
                        "wert": component[1],    # Position 1: Messwert
                        "lqi":  component[2],    # Position 2: Index als int
                        "lqi_float": lqi_float}  # Position 3: Index als float
    return dict(EMPTY)

# --- Hilfsfunktion Auswertung Prognosedaten
# +++ erstellt mit KI-Hilfe
# Vollständige Indexreihe einer Komponente, chronologisch sortiert.
# Der Prognose-Eintrag führt ein Feld mehr als airquality: auf das Ende der Stunde folgt
# der Zeitpunkt des Modelllaufs, erst danach kommen die Schadstoffe.
# Auch hier ist der Schlüssel der Stundenbeginn; für den Vergleich in calculate_trend()
# wird das Ende gebildet. Die Umrechnung über datetime vermeidet die Schreibweise 24:00:00,
# die den Stringvergleich über Mitternacht hinweg verfälschen würde.
def forecast_series(series, comp_id):
    forecast = []
    for timestamp in sorted(series):
        for component in series[timestamp][4:]:   # ab Position 4 folgen die Schadstoffe
            if len(component) >= 3 and component[0] == comp_id:
                end = (datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                       + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
                forecast.append([end, component[2]])   # Zeit + Index
                break
    return forecast

# --- Einstiegspunkt des Schedules
# Bei Fehler in data_update wird dieses übersprungen statt Programmende
def safe_data_update():
    try:
        data_update()
    except Exception:
        logging.exception("Update übersprungen:")

# --- Hauptablauf des API-Updates
# +++ erstellt mit KI-Hilfe
def data_update():
    # -- 1) Abruf aktueller Messdaten
    # Da die API-Daten stets in MEZ geführt werden erfolgt die Abfrage ebenfalls ganzjährig in MEZ (UTC+1)
    # Das UBA benennt jede Messstunde nach ihrem Ende, die Stunden laufen von 1 bis 24.
    # Die um Mitternacht endende Stunde heißt daher 24 Uhr und gehört noch zum Vortag.
    # Gerechnet wird deshalb mit dem Beginn der Messstunde: dessen Datum, dessen Stunde + 1.
    # Abgefragt wird bis zum Beginn der aktuellen Stunde
    CET = timezone(timedelta(hours=1)) # Festlegung auf MEZ (UTC+1)
    now = datetime.now(CET)
    first = now - timedelta(hours=WINDOW_HOURS + 1)   # liegt in der ältesten abgefragten Messstunde
    last = now - timedelta(hours=1)                    # liegt in der jüngsten abgeschlossenen Messstunde
    window = {
        "date_from": first.date().isoformat(), "time_from": str(first.hour + 1),
        "date_to":   last.date().isoformat(),  "time_to":   str(last.hour + 1),
    }

    # kein component und kein scope bei airquality
    current_data = fetch_stations(URL_CURRENT, window, POLLUTANTS)

    results = {}
    for name, (station, comp_id) in POLLUTANTS.items():
        results[name] = latest_value(current_data[station], comp_id)

    # -- 2) Im Falle einer leeren Datenübertragung ist der letzte gültige Wert zu erhalten
    # aktuellen Stand der JSON laden, um komplettes Überschreiben zu verhindern
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            airdata = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        airdata = {}
    previous = airdata.get("uba", {}).get("schadstoffe", {})

    for name, entry in results.items():
        #Prüfen, ob aktuelles Ergebnis leer und vorheriges Ergebnis nicht leer
        if entry["wert"] is None and previous.get(name, {}).get("wert") is not None:
            results[name] = dict(previous[name])

    # -- 3) Abruf Prognosedaten
    forecast_data = fetch_stations(URL_FORECAST, {}, FORECAST_POLLUTANTS)

    forecasts = {}
    for name, (station, comp_id) in FORECAST_POLLUTANTS.items():
        forecasts[name] = forecast_series(forecast_data[station], comp_id)

    # Prognose in Ergebnisse übertragen, ohne Prognose (SO2) wird None eingetragen
    for name in results:
        results[name]["Prognose"] = forecasts.get(name)

    # -- 4) JSON nur in der Kategorie UBA schreiben und alten Inhalt ersetzen
    airdata["uba"] = {"schadstoffe": results}

    #JSON als temporäre Datei schreiben, danach "airdata.json" in einem Stück ersetzen
    tmp_path = JSON_PATH.with_suffix(".uba.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(airdata, f, indent=2, ensure_ascii=False)
    tmp_path.replace(JSON_PATH)

# --- main
def main():
    try:
        logging.info("Programm gestartet")

        # API-Update bei Programmstart
        safe_data_update()

        # API-Update zum Schedule
        schedule.every(10).minutes.at(":46").do(safe_data_update)

        while True:
            schedule.run_pending()
            time.sleep(1)

    except Exception:
        logging.exception("Fehler:")

    except KeyboardInterrupt:
        logging.info("Strg + C")

    finally:
        logging.info("Programm beendet")


if __name__ == "__main__":
    main()

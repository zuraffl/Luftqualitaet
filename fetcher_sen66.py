"""
Fetcher für Messwerte des SEN66 via I2C auf Basis der SEN6x adafruit Bibliothek.
Dokumentation auf circuitpython:
https://docs.circuitpython.org/projects/sen6x/en/latest/index.html

Der Sensor ist konstant in Betrieb, um neues Anlaufen der Aufwärmzeit zu verhindern.

Inhalt:
* Einstieg Scheduler: Datenabruf wird bei Fehler übersprungen
* Hauptfunktion zum Datenabruf mit Datenupdate
* main mit Startprozessen und Schedule
"""
import time
import json
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

import board
import adafruit_sen6x
import schedule

from config import WARMUP

# Verzeichnis des Codes
BASE_PATH = Path(__file__).parent

# Logger mit Rotating File Handler
(BASE_PATH / "Logging_Files").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    handlers=[
        RotatingFileHandler(
            BASE_PATH / "Logging_Files/Logger_sen66.log",
            maxBytes=1_000_000,   # maximal ~1 MB pro Log-Datei
            backupCount=10,       # 10 Logs werden archiviert
            encoding="utf-8",
        )
    ],
)

# JSON im gleichen Verzeichnis
JSON_PATH = BASE_PATH / "airdata.json"

# --- Im Fehlerfall wird das Update übersprungen statt Programmende
def safe_data_update(sensor):
    try:
        data_update(sensor)
    except Exception:
        logging.exception("Update übersprungen:")

# --- Datenabruf
def data_update(sensor):
    if sensor.data_ready:
        # Datenabruf
        data = sensor.all_measurements()
        data["time"] = time.time() # fügt den Messwerten aktuelle Zeit hinzu

        # aktuellen Stand der JSON laden, um komplettes Überschreiben zu verhindern
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                airdata = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            airdata = {}

        # JSON nur in der Kategorie sensor schreiben und alten Inhalt ersetzen
        airdata["sensor"] = data

        # JSON als temporäre Datei schreiben, danach "airdata.json" in einem Stück ersetzen
        tmp_path = JSON_PATH.with_suffix(".sen.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(airdata, f, indent=2)
        tmp_path.replace(JSON_PATH)

# --- main
def main():
    logging.info("Programm gestartet")

    try:
        # I2C und Sensor festlegen
        i2c = board.I2C()
        sensor = adafruit_sen6x.SEN66(i2c)

        # Sensor starten mit Warmup, dann erste Messung
        sensor.start_measurement()
        time.sleep(WARMUP)
        safe_data_update(sensor)

        # Schedule
        schedule.every().minute.at(":57").do(safe_data_update, sensor)

        # Schedule-Schleife
        while True:
            schedule.run_pending()
            time.sleep(1)

    except Exception:
        logging.exception("Fehler:")

    except KeyboardInterrupt:
        logging.info("Strg + C")

    finally:
        # Sensor bei programmende in idle versetzen
        try:
            sensor.stop_measurement()
        # falls Sensor nicht ansprechbar
        except Exception:
            logging.exception("Sensor konnte nicht gestoppt werden.")
        logging.info("Programm beendet")

if __name__ == "__main__":
    main()
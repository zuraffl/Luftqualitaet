"""
Main Code

Inhalt:
* Initialisierung von Display, Fonts, Trendpfeilen etc.
* Einstieg Scheduler: Datenupdate wird bei Fehler übersprungen
* Einstieg Scheduler: Full Refresh wird bei Fehler übersprungen (Funktion Full Refresh in graphics.py)
* Datenupdate mit Funktionen, Partial Refresh und CSV-Logging
* Namensgebung CSV-Log
* main mit Startprozessen und Schedule
"""
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ePaper_Treiber import epd2in9_V2
import schedule

from config import CSV_LOGGING, CSV_LOGGING_INTERVAL, DISPLAY_INTERVAL
from functions import convert_json_data, calculate_lqi_in, calculate_overall_index, calculate_trend, fresh_air_algorithm, csv_init, csv_append, sen_veraltet, uba_veraltet
from graphics import display_cleanup, draw_startup, draw_static_image, draw_dynamic_image

# Verzeichnis des Codes
BASE_PATH = Path(__file__).parent

# Logger mit Rotating File Handler
(BASE_PATH / "Logging_Files").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    handlers=[
        RotatingFileHandler(
            BASE_PATH / "Logging_Files/Logger_main.log",
            maxBytes=1_000_000,   # ca. 1MB Maximalgröße
            backupCount=10,       # Archiv der zehn letzten Logs
            encoding="utf-8",
        )
    ],
)

# Zähler initialisieren
counter_csv = counter_uba = counter_sen66 = counter_display = -1

# Initialisierung des Bildformates
Display = epd2in9_V2.EPD()
Vertical_Image = Image.new('1', (Display.width, Display.height), 255) 
draw = ImageDraw.Draw(Vertical_Image)

# Fonts
fonts = {
    'f12': ImageFont.truetype(str(BASE_PATH / "Fonts/Roboto-Bold.ttf"), 12),
    'f14': ImageFont.truetype(str(BASE_PATH / "Fonts/Roboto-Bold.ttf"), 14),
    'fNB14': ImageFont.truetype(str(BASE_PATH / "Fonts/Roboto-BoldCondensed.ttf"), 14),
    'f16': ImageFont.truetype(str(BASE_PATH / "Fonts/Roboto-Bold.ttf"), 16),
    'fNB16': ImageFont.truetype(str(BASE_PATH / "Fonts/Roboto-BoldCondensed.ttf"), 16)
}

# Trendpfeile
arrows = {
    angle: Image.open(BASE_PATH / "Medien" / f"Arrow_{angle:03d}.png").convert("1")
    for angle in range(0, 181, 30)
}

# --- Im Fehlerfall wird das Datenupdate übersprungen statt Programmende
def safe_data_update(static_snapshot):
    try:
        data_update(static_snapshot)
    except Exception:
        logging.exception("Update der Messwerte übersprungen:")

# --- Im Fehlerfall wird der Full Refresh des Displays übersprungen statt Programmende
def safe_draw_static():
    try:
        draw_static_image(Display, Vertical_Image, draw, fonts) # in graphics.py
    except Exception:
        logging.exception("Display-Update der statischen Elemente übersprungen:")

# --- Minütliches Datenupdate und Partial Refresh des Displays
def data_update(static_snapshot):
    global counter_csv, counter_uba, counter_sen66, counter_display

    # Uhrzeit
    time_now = time.strftime("%H:%M", time.localtime())

    # JSON-Daten abrufen und in dict konvertieren
    with open(BASE_PATH / "airdata.json", "r", encoding="utf-8") as f:
        daten = json.load(f)

    data_in, data_out, lqi_out, lqi_out_float = convert_json_data(daten)

    # Prüfen, ob SEN66-Daten veraltet
    veraltet, counter_sen66 = sen_veraltet(daten, counter_sen66)
    if veraltet:
        data_in = {k: None for k in data_in}
    # Prüfen, ob UBA-Daten veraltet
    stale, counter_uba = uba_veraltet(daten, counter_uba)
    for k in stale:
        data_out[k] = None
        lqi_out[k]  = None
        lqi_out_float[k] = None

    # Berechnungen
    lqi_in, lqi_in_float = calculate_lqi_in(data_in)            # LQI innen
    overall = calculate_overall_index(lqi_out, lqi_in)          # Gesamt LQI außen und innen
    trend = calculate_trend(lqi_out, daten)                     # Prognose außen
    fresh_air = fresh_air_algorithm(lqi_out_float, lqi_in_float)# Empfehlung zum Lüften

    # CSV Log mit Zähler (Standard alle 5 Minuten)
    # +++ erstellt mit KI-Hilfe
    if CSV_LOGGING:
        counter_csv += 1
        if counter_csv % CSV_LOGGING_INTERVAL == 0:
            dashboard_data = [data_in, data_out, lqi_out, lqi_in, overall, trend, fresh_air, time_now, lqi_out_float, lqi_in_float]
            csv_append(csv_file_name(), dashboard_data)

    # Display Partial Update mit Zähler (Standard jede Minute)
    counter_display += 1
    if counter_display % DISPLAY_INTERVAL == 0:
        Vertical_Image.paste(static_snapshot, (0, 0)) # dynamischen Bildteil auf den statischen Hintergrund zurücksetzen für partial refresh
        draw_dynamic_image(
            Display, Vertical_Image, draw, fonts, data_out, data_in, lqi_out, lqi_in, overall, arrows, trend, fresh_air, time_now) # in graphics.py

# --- Zeitabhängiger Dateiname der CSV wird festgelegt
# +++ erstellt mit KI-Hilfe
def csv_file_name():
    present_month = datetime.now().strftime("%y%m")
    CSV_PATH = BASE_PATH / "Logging_Files" / f"csv_log_{present_month}.csv"
    csv_init(CSV_PATH)
    return CSV_PATH

# --- main
def main():
    logging.info("Programm gestartet")

    try:    
        # Display bereinigen und Startbildschirm
        display_cleanup(Display)
        time.sleep(10)
        draw_startup(Display, Vertical_Image, draw, fonts)
        time.sleep(10)

        # Fixierter Bildteil, dann dynamischer
        draw_static_image(Display, Vertical_Image, draw, fonts)
        static_snapshot = Vertical_Image.copy()   # statischen Hintergrund merken für partial refresh
        safe_data_update(static_snapshot)

        # Schedule
        schedule.every().minute.at(":00").do(safe_data_update, static_snapshot)
        schedule.every().hour.at("59:49").do(safe_draw_static) #Full refresh, muss vor Partial Update um :00 fertig sein

        while True:
            schedule.run_pending()
            time.sleep(1)

    except Exception:
        logging.exception("Fehler:")
    
    except KeyboardInterrupt:
        logging.info("Strg + C")

    finally:
        try:
            Display.init()
            Display.Clear()
            Display.sleep()
        # falls Display nicht ansprechbar
        except Exception:
            logging.exception("Display Clear nicht möglich.")
        logging.info("Programm beendet")

if __name__ == "__main__":
    main()
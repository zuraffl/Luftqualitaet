"""
Aus main ausgelagerte Funktionen.

Inhalt:
* Transferieren der JSON-Daten in ein dict
* Alter der Sensordaten prüfen
* Alter der API-Daten prüfen
* LQI der Einzelwerte des Innenbereichs ermitteln
* Gesamt LQI innen und außen ermitteln
* Trendpfeile berechnen
* Lüftungsempfehlung ermitteln
* CSV anlegen
* CSV schreiben
"""
from datetime import datetime, timedelta, timezone
import csv
import time
import math

import logging
from shapely.geometry import Point, Polygon

from config import SEN66_TIMEOUT, PM2_5_FACTOR, PM10_FACTOR, UBA_TIMEOUT, FORECAST_FROM, FORECAST_TO

# UBA-JSON ist immer in Winterzeit (MEZ/CET), die Zeit der UBA-Werte wird im Code daher auf UTC+1 (= MEZ) festgelegt
CET = timezone(timedelta(hours=1))

# --- JSON-Daten in kategorisierte dicts konvertieren
def convert_json_data(data):

    # Korrekturfunktion für Feinstaubwerte
    def correction(raw_value, factor):
        return round(raw_value * factor, 1) if raw_value is not None else None

    # Zugriff auf beide Kategorien der JSON
    values_in = data.get("sensor", {})
    values_out = data.get("uba", {}).get("pollutants", {})

    # Messwerte innen
    data_in = {
        "PM2_5_raw":    values_in.get("pm2_5"),                             # unkorrigiert
        "PM10_raw":     values_in.get("pm10"),                              # unkorrigiert
        "PM2_5":        correction(values_in.get("pm2_5"), PM2_5_FACTOR),   # korrigiert
        "PM10":         correction(values_in.get("pm10"),  PM10_FACTOR),    # korrigiert
        "NOx":          values_in.get("nox_index"),
        "VOC":          values_in.get("voc_index"),
        "CO2":          values_in.get("co2"),
        "Temperature":  values_in.get("temperature"),
        "Humidity":     values_in.get("humidity"),
    }

    # Messwerte außen
    data_out = {
        "PM2_5":    values_out.get("PM2_5", {}).get("value"),
        "PM10":     values_out.get("PM10", {}).get("value"),
        "NO2":      values_out.get("NO2", {}).get("value"),
        "SO2":      values_out.get("SO2", {}).get("value"),
        "O3":       values_out.get("O3", {}).get("value"),
    }

    # Luftqualitätsindizes außen als int
    lqi_out = {
        "PM2_5":    values_out.get("PM2_5", {}).get("lqi"),
        "PM10":     values_out.get("PM10", {}).get("lqi"),
        "NO2":      values_out.get("NO2", {}).get("lqi"),
        "SO2":      values_out.get("SO2", {}).get("lqi"),
        "O3":       values_out.get("O3", {}).get("lqi"),
    }

    # Luftqualitätsindizes außen als float
    lqi_out_float = {
        "PM2_5":    values_out.get("PM2_5", {}).get("lqi_float"),
        "PM10":     values_out.get("PM10", {}).get("lqi_float"),
        "NO2":      values_out.get("NO2", {}).get("lqi_float"),
        "SO2":      values_out.get("SO2", {}).get("lqi_float"),
        "O3":       values_out.get("O3", {}).get("lqi_float"),
    }

    # Rückgabe der dicts an main
    return data_in, data_out, lqi_out, lqi_out_float

# --- Prüfen des Alters der SEN66-Daten
def sen_outdated(data, counter_sen66):

    # Zeitstempel abrufen
    sensor_time = data.get("sensor", {}).get("time")

    # Ausschluss-Kriterien: Zeitstempel nicht vorhanden oder Datenalter über gesetztem Limit
    outdated_sen66 = sensor_time is None or time.time() - sensor_time > SEN66_TIMEOUT * 60

    # Zähler: um Überfüllung des Logs zu vermeiden ein Eintrag pro Stunde
    if outdated_sen66:
        counter_sen66 += 1
        if counter_sen66 == 60:
            counter_sen66 = 0
        if counter_sen66 == 0:
            logging.warning("SEN66-Daten veraltet")
    else:
        counter_sen66 = -1

    # Rückgabe ob veraltet und Zählerstand an main
    return outdated_sen66, counter_sen66

# --- Prüfen des Alters der UBA-Daten
# +++ erstellt mit KI-Hilfe
def uba_outdated(data, counter_uba):

    # UBA-Daten abrufen und in MEZ betrachten, Set veralteter Werte definieren
    pollutants = data.get("uba", {}).get("pollutants", {})
    now = datetime.now(CET)
    outdated_pollutants = set()

    # Prüfschleife
    for name, entry in pollutants.items():
        time_str = entry.get("time")
        if not time_str:
            outdated_pollutants.add(name); continue         # kein Zeitstempel -> Wert veraltet
        try:
            # UBA-Konvention: 24:00 = Tagesende
            if " 24:" in time_str:
                timestamp = datetime.strptime(time_str[:10], "%Y-%m-%d") + timedelta(days=1)
            else:
                timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            timestamp = timestamp.replace(tzinfo=CET)
        except ValueError:
            outdated_pollutants.add(name); continue         # unparsbar -> Wert veraltet
        if now - timestamp > timedelta(hours=UBA_TIMEOUT):
            outdated_pollutants.add(name)                   # Zeitstempel über gesetztem Limit -> Wert veraltet

    # Zähler: um Überfüllung des Logs zu vermeiden ein Eintrag pro Stunde
    if outdated_pollutants:
        counter_uba += 1
        if counter_uba == 60:
            counter_uba = 0
        if counter_uba == 0:
            logging.warning("UBA veraltet: %s", ", ".join(sorted(outdated_pollutants)))
    else:
        counter_uba = -1

    # Rückgabe veralteter Messgrößen und Zählerstand an main
    return outdated_pollutants, counter_uba

# --- LQI im Innenbereich ermitteln
def calculate_lqi_in(data_in):

    # Festlegung der Grenzwerte
    border_values = {
        "PM2_5": [0, 5, 15, 30, 50, 70],
        "PM10": [0, 9, 27, 54, 90, 126],
        "NOx": [1, 20, 150, 300, 400, 500],
        "VOC": [1, 150, 250, 400, 450, 500],
        "CO2": [400, 800, 1000, 1400, 2000, 2600],
    }

    lqi_in = {}         # dict für int
    lqi_in_float = {}   # dict für float

    # Schleife zur Bestimmung pro Messgröße
    # +++ erstellt mit KI-Hilfe
    for pollutant, borders in border_values.items():
        value = data_in.get(pollutant)

        # fehlender Messwert gibt None aus
        if value is None:
            lqi_in[pollutant] = None
            lqi_in_float[pollutant] = None
            continue

        # Grenzwerte durchgehen, bis der Wert unter der nächsten Grenze liegt (höchstens Klasse 4)
        i = 0
        while i < 4 and value >= borders[i + 1]:
            i += 1

        # Fließkommazahl: Klasse + Anteil innerhalb der Klasse, bei 5.0 gedeckelt
        # Ganzzahl: Klasse
        lqi_in_float[pollutant] = min(i + (value - borders[i]) / (borders[i + 1] - borders[i]), 5.0)
        lqi_in[pollutant] = i

    # Rückgabe als dict an main
    return lqi_in, lqi_in_float

# --- Gesamt-Index für Innen- und Außenbereich ermitteln
def calculate_overall_index(lqi_out, lqi_in):

    # Schlechtester Einzelwert außen und innen
    valid_out = [v for v in lqi_out.values()
                if v is not None]                               # ungültige Werte filtern
    worst_out = max(valid_out) if len(valid_out) >= 2 else None # mindestens zwei gültige Werte

    valid_in = [v for k, v in lqi_in.items()
                if k != "PM10"                                  # PM10 vom Gesamtindex ausgeschlossen
                and v is not None]                              # ungültige Werte filtern
    worst_in = max(valid_in) if len(valid_in) >= 2 else None    # mindestens zwei gültige Werte

    # Gesamtindex außen und innen ableiten, als string und int
    if worst_out is None:   index_out, index_out_no = "-", None
    elif worst_out == 0:    index_out, index_out_no = "sehr\ngut", 0
    elif worst_out == 1:    index_out, index_out_no = "gut", 1
    elif worst_out == 2:    index_out, index_out_no = "mäßig", 2
    elif worst_out == 3:    index_out, index_out_no = "schlecht", 3
    else:                   index_out, index_out_no = "sehr\nschlecht", 4

    if worst_in is None:    index_in, index_in_no = "-", None
    elif worst_in == 0:     index_in, index_in_no = "sehr\ngut", 0
    elif worst_in == 1:     index_in, index_in_no = "gut", 1
    elif worst_in == 2:     index_in, index_in_no = "mäßig", 2
    elif worst_in == 3:     index_in, index_in_no = "schlecht", 3
    else:                   index_in, index_in_no = "sehr\nschlecht", 4

    # Rückgabe als dict an main
    return {
        "overall_out": index_out,
        "overall_in": index_in,
        "overall_out_no": index_out_no,
        "overall_in_no": index_in_no,
    }

# --- Trendpfeile zur Luftqualität berechnen
def calculate_trend(lqi_out, data):

    # Prognosefenster mit Daten aus config.py eingrenzen
    now = datetime.now(CET)
    window_start = (now + timedelta(hours=FORECAST_FROM)).strftime("%Y-%m-%d %H:%M:%S")
    window_end   = (now + timedelta(hours=FORECAST_TO)).strftime("%Y-%m-%d %H:%M:%S")

    # schlechtester Prognose-Index im Zeitfenster je Schadstoff
    def worst_forecast(series):
        # Prüfen, ob Prognosereihe vorhanden
        if not series:
            return None
        indices = [index for timestamp, index in series
                   if window_start <= timestamp <= window_end]   # Intervall eingrenzen
        # Prüfen, ob Indizes vorhanden
        if not indices:
            return None
        return max(indices)                                      # Maximalwert (schlechtester Index im Zeitfenster)

    # Trend (Prognose − aktuell) in einen Pfeilwinkel übersetzen
    def trend_to_angle(current, forecast):
        if current is None or forecast is None:
            return None                     # kein Pfeil ohne beide Werte
        trend = forecast - current
        if trend <= -3:
            return 180                      # maximale Auslenkung nach unten
        if trend >= 3:
            return 0                        # maximale Auslenkung nach oben
        return 90 - trend * 30              # alle anderen Fälle: Zwischenstellungen je 30° berechnen

    # je Schadstoff aktuellen Index mit Worst-Case-Prognose vergleichen
    pollutants = data.get("uba", {}).get("pollutants", {})
    trend_arrows = {}
    for name in ("PM2_5", "PM10", "NO2", "O3"):
        forecast = worst_forecast(pollutants.get(name, {}).get("forecast"))
        trend_arrows[name] = trend_to_angle(lqi_out.get(name), forecast)

    return trend_arrows

# --- Lüftungsempfehlung
def fresh_air_algorithm(lqi_out_float: dict, lqi_in_float: dict) -> str:

    # Prüfung: Wurde dict übergeben?
    if not isinstance(lqi_out_float, dict) or not isinstance(lqi_in_float, dict):
        return "-"

    # Prüfung: nur gültige numerische Werte herausfiltern
    valid_out = [
        v
        for v in lqi_out_float.values()
        if isinstance(v, (int, float)) and not math.isnan(v) # schließt None und NaN aus
    ]
    valid_in = [
        v
        for k, v in lqi_in_float.items()
        if k != "PM10" # PM10 wird ausgeschlossen
        and isinstance(v, (int, float)) and not math.isnan(v) # schließt None und NaN aus
    ]

    # Prüfung: Mindestens zwei gültige Werte pro Dictionary erforderlich
    if len(valid_out) < 2 or len(valid_in) < 2:
        return "-"

    # Höchsten float-Einzelwert ermitteln (x für außen, y für innen)
    x_out = max(valid_out)
    y_in = max(valid_in)

    # Shapely Koordinate erstellen
    coordinate = Point(x_out, y_in)

    # Zonen als Polygone definieren
    zones = [
        (Polygon([(0, 0), (2, 0), (2, 1.7), (3, 2.7), (2.7, 3), (1.7, 2), (0, 2),]),
        "Lüften optional",
        ),
        (Polygon([(2, 0), (3, 0), (3, 2.7), (2, 1.7)]),
        "Lüften nicht empf.",
        ),
        (Polygon([(0, 2), (1.7, 2), (2.7, 3), (0, 3)]),
        "Lüften empfohlen",
        ),
        (Polygon([(2.7, 3), (3, 2.7), (5, 3.3), (5, 5), (3.3, 5)]),
        "Stoßlüften!",
        ),
        (Polygon([(3, 0), (5, 0), (5, 3.3), (3, 2.7)]),
        "Nicht lüften!",
        ),
        (Polygon([(0, 3), (2.7, 3), (3.3, 5), (0, 5)]),
        "Dringend lüften!",
        ),
    ]

    # Prüfen, ob und in welchem Polygon der Punkt liegt
    for poly, fresh_air in zones:
        if poly.intersects(coordinate):
            return fresh_air

    # Unerwarteter Fall: Punkt liegt außerhalb der Polygone
    return "-"

# --- CSV-Logger
# +++ erstellt mit KI-Hilfe
# Tabelle der Kopfspalten als Liste
CSV_HEADER = [
    "Zeitstempel",
    "out_PM2_5", "out_PM10", "out_NO2", "out_SO2", "out_O3",
    "in_PM2_5_raw", "in_PM10_raw", "in_PM2_5", "in_PM10", "in_NOx", "in_VOC", "in_CO2", "in_Temp", "in_Hum",
    "lqi_out_PM2_5", "lqi_out_PM10", "lqi_out_NO2", "lqi_out_SO2", "lqi_out_O3",
    "lqi_in_PM2_5", "lqi_in_PM10", "lqi_in_NOx", "lqi_in_VOC", "lqi_in_CO2",
    "lqi_out_PM2_5_float", "lqi_out_PM10_float", "lqi_out_NO2_float", "lqi_out_SO2_float", "lqi_out_O3_float",
    "lqi_in_PM2_5_float", "lqi_in_PM10_float", "lqi_in_NOx_float", "lqi_in_VOC_float", "lqi_in_CO2_float",
    "overall_out", "overall_in",
    "trend_PM2_5", "trend_PM10", "trend_NO2", "trend_O3",
    "fresh_air",
]

# --- Prüfen, ob CSV existiert, wenn nicht neu anlegen
def csv_init(csv_path):
    if csv_path.exists():
        return
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";")
        writer.writeheader()

# --- Neue Zeile mit aktuellen Werten hinzufügen
def csv_append(csv_path, dashboard_data):
    data_in, data_out, lqi_out, lqi_in, overall, trend, fresh_air, _, lqi_out_float, lqi_in_float = dashboard_data

    # zu beschreibende Datenreihe als dict
    row = {
        "Zeitstempel":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "out_PM2_5":    data_out["PM2_5"],
        "out_PM10":     data_out["PM10"],
        "out_NO2":      data_out["NO2"],
        "out_SO2":      data_out["SO2"],
        "out_O3":       data_out["O3"],
        "in_PM2_5_raw": data_in["PM2_5_raw"],
        "in_PM10_raw":  data_in["PM10_raw"],
        "in_PM2_5":     data_in["PM2_5"],
        "in_PM10":      data_in["PM10"],
        "in_NOx":       data_in["NOx"],
        "in_VOC":       data_in["VOC"],
        "in_CO2":       data_in["CO2"],
        "in_Temp":      data_in["Temperature"],
        "in_Hum":       data_in["Humidity"],
        "lqi_out_PM2_5":lqi_out["PM2_5"],
        "lqi_out_PM10": lqi_out["PM10"],
        "lqi_out_NO2":  lqi_out["NO2"],
        "lqi_out_SO2":  lqi_out["SO2"],
        "lqi_out_O3":   lqi_out["O3"],
        "lqi_in_PM2_5": lqi_in["PM2_5"],
        "lqi_in_PM10":  lqi_in["PM10"],
        "lqi_in_NOx":   lqi_in["NOx"],
        "lqi_in_VOC":   lqi_in["VOC"],
        "lqi_in_CO2":   lqi_in["CO2"],
        "lqi_out_PM2_5_float": lqi_out_float["PM2_5"],
        "lqi_out_PM10_float":  lqi_out_float["PM10"],
        "lqi_out_NO2_float":   lqi_out_float["NO2"],
        "lqi_out_SO2_float":   lqi_out_float["SO2"],
        "lqi_out_O3_float":    lqi_out_float["O3"],
        "lqi_in_PM2_5_float":  lqi_in_float["PM2_5"],
        "lqi_in_PM10_float":   lqi_in_float["PM10"],
        "lqi_in_NOx_float":    lqi_in_float["NOx"],
        "lqi_in_VOC_float":    lqi_in_float["VOC"],
        "lqi_in_CO2_float":    lqi_in_float["CO2"],
        "overall_out":  overall["overall_out_no"],
        "overall_in":   overall["overall_in_no"],
        "trend_PM2_5":  trend["PM2_5"],
        "trend_PM10":   trend["PM10"],
        "trend_NO2":    trend["NO2"],
        "trend_O3":     trend["O3"],
        "fresh_air":    fresh_air,
    }

    # Schreiben (append-Modus)
    with csv_path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";")
        writer.writerow(row)
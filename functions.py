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

#UBA-JSON ist immer in Winterzeit (MEZ), die Zeit der UBA-Werte wird im Code daher auf UTC+1 (= MEZ) festgelegt
MEZ = timezone(timedelta(hours=1))

# --- json Daten in dict konvertieren
def convert_json_data(daten):

    #Korrekturfunktion für Feinstaubwerte
    def correction(raw_value, factor):
        return round(raw_value * factor, 1) if raw_value is not None else None

    values_in = daten.get("sensor", {})
    values_out = daten.get("uba", {}).get("schadstoffe", {})

    data_in = {
        "PM2_5_raw":    values_in.get("pm2_5"), # unkorrigiert
        "PM10_raw":     values_in.get("pm10"), # unkorrigiert
        "PM2_5":        correction(values_in.get("pm2_5"), PM2_5_FACTOR), # korrigiert
        "PM10":         correction(values_in.get("pm10"),  PM10_FACTOR), # korrigiert
        "NOx":          values_in.get("nox_index"),
        "VOC":          values_in.get("voc_index"),
        "CO2":          values_in.get("co2"),
        "Temperature":  values_in.get("temperature"),
        "Humidity":     values_in.get("humidity"),
    }

    data_out = {
        "PM2_5":    values_out.get("PM2_5", {}).get("wert"),
        "PM10":     values_out.get("PM10", {}).get("wert"),
        "NO2":      values_out.get("NO2", {}).get("wert"),
        "SO2":      values_out.get("SO2", {}).get("wert"),
        "O3":       values_out.get("O3", {}).get("wert"),
    }

    lqi_out = {
        "PM2_5":    values_out.get("PM2_5", {}).get("lqi"),
        "PM10":     values_out.get("PM10", {}).get("lqi"),
        "NO2":      values_out.get("NO2", {}).get("lqi"),
        "SO2":      values_out.get("SO2", {}).get("lqi"),
        "O3":       values_out.get("O3", {}).get("lqi"),
    }

    lqi_out_float = {
        "PM2_5":    values_out.get("PM2_5", {}).get("lqi_float"),
        "PM10":     values_out.get("PM10", {}).get("lqi_float"),
        "NO2":      values_out.get("NO2", {}).get("lqi_float"),
        "SO2":      values_out.get("SO2", {}).get("lqi_float"),
        "O3":       values_out.get("O3", {}).get("lqi_float"),
    }

    return data_in, data_out, lqi_out, lqi_out_float

# --- Prüfen des Alters der SEN66-Daten
def sen_veraltet(daten, counter_sen66):
    sensor_time = daten.get("sensor", {}).get("zeit")
    # Kriterien: Zeitstempel nicht vorhanden oder Datenalter über gesetztem Limit
    veraltet_sen66 = sensor_time is None or time.time() - sensor_time > SEN66_TIMEOUT * 60
    if veraltet_sen66:
        # Zähler: um Überfüllung des Logs zu vermeiden ein Eintrag pro Stunde
        counter_sen66 += 1
        if counter_sen66 == 60:
            counter_sen66 = 0
        if counter_sen66 == 0:
            logging.warning("SEN66-Daten veraltet")
    else:
        counter_sen66 = -1
    return veraltet_sen66, counter_sen66

# --- Prüfen des Alters der UBA-Daten
# +++ erstellt mit KI-Hilfe
def uba_veraltet(daten, counter_uba):
    schadstoffe = daten.get("uba", {}).get("schadstoffe", {})
    jetzt = datetime.now(MEZ)
    veraltet_uba = set()
    for name, s in schadstoffe.items():
        zeit_str = s.get("zeit")
        if not zeit_str:
            veraltet_uba.add(name); continue
        try:
            if " 24:" in zeit_str:                 # UBA-Konvention: 24:00 = Tagesende
                zeit = datetime.strptime(zeit_str[:10], "%Y-%m-%d") + timedelta(days=1)
            else:
                zeit = datetime.strptime(zeit_str, "%Y-%m-%d %H:%M:%S")
            zeit = zeit.replace(tzinfo=MEZ)
        except ValueError:
            veraltet_uba.add(name); continue               # unparsbar -> sicherheitshalber veraltet
        if jetzt - zeit > timedelta(hours=UBA_TIMEOUT):
            veraltet_uba.add(name)
    if veraltet_uba:
        # Zähler: um Überfüllung des Logs zu vermeiden ein Eintrag pro Stunde
        counter_uba += 1
        if counter_uba == 60:
            counter_uba = 0
        if counter_uba == 0:
            logging.warning("UBA veraltet: %s", ", ".join(sorted(veraltet_uba)))
    else:
        counter_uba = -1
    return veraltet_uba, counter_uba

# --- LQI im Innenbereich ermitteln
def calculate_lqi_in(data_in):

    border_values = {
        "PM2_5": [0, 5, 15, 30, 50, 70],
        "PM10": [0, 9, 27, 54, 90, 126],
        "NOx": [1, 20, 150, 300, 400, 500],
        "VOC": [1, 150, 250, 400, 450, 500],
        "CO2": [400, 800, 1000, 1400, 2000, 2600],
    }

    lqi_in = {}
    lqi_in_float = {}

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

    return lqi_in, lqi_in_float

#Gesamt-Index für Innen- und Außenbereich ermitteln
def calculate_overall_index(lqi_out, lqi_in):

    # Schlechtester Einzelwert außen
    gueltige_out = [v for v in lqi_out.values() if v is not None]       # ungültige Werte filtern
    worst_out = max(gueltige_out) if len(gueltige_out) >= 2 else None   # mindestens zwei gültige Werte

    # Schlechtester Einzelwert innen
    gueltige_in = [v for k, v in lqi_in.items()
                   if k != "PM10"                                       # PM10 vom Gesamtindex ausgeschlossen
                   and v is not None]                                   # ungültige Werte filtern
    worst_in = max(gueltige_in) if len(gueltige_in) >= 2 else None      # mindestens zwei gültige Werte

    # Gesamtindex ableiten, als string und int
    if worst_out is None:   Index_out, Index_out_no = "-", None
    elif worst_out == 0:    Index_out, Index_out_no = "sehr\ngut", 0
    elif worst_out == 1:    Index_out, Index_out_no = "gut", 1
    elif worst_out == 2:    Index_out, Index_out_no = "mäßig", 2
    elif worst_out == 3:    Index_out, Index_out_no = "schlecht", 3
    else:                   Index_out, Index_out_no = "sehr\nschlecht", 4

    if worst_in is None:    Index_in, Index_in_no = "-", None
    elif worst_in == 0:     Index_in, Index_in_no = "sehr\ngut", 0
    elif worst_in == 1:     Index_in, Index_in_no = "gut", 1
    elif worst_in == 2:     Index_in, Index_in_no = "mäßig", 2
    elif worst_in == 3:     Index_in, Index_in_no = "schlecht", 3
    else:                   Index_in, Index_in_no = "sehr\nschlecht", 4

    return {
        "overall_out": Index_out,
        "overall_in": Index_in,
        "overall_out_no": Index_out_no,
        "overall_in_no": Index_in_no,
    }

#Trendpfeile zur Luftqualität berechnen
def calculate_trend(lqi_out, daten):

    # Prognosefenster mit Daten aus config.py eingrenzen
    now = datetime.now(MEZ)
    window_start = (now + timedelta(hours=FORECAST_FROM)).strftime("%Y-%m-%d %H:%M:%S")
    window_end   = (now + timedelta(hours=FORECAST_TO)).strftime("%Y-%m-%d %H:%M:%S")

    #schlechtester Prognose-Index im Zeitfenster je Schadstoff
    def worst_forecast(series):
        #Prüfen, ob Prognosereihe vorhanden
        if not series:
            return None
        indices = [index for timestamp, index in series
                   if window_start <= timestamp <= window_end]   # Intervall eingrenzen
        #Prüfen, ob Indizes vorhanden
        if not indices:
            return None
        return max(indices)                                      # Maximalwert (schlechtester Index im Zeitfenster)

    #Trend (Prognose − aktuell) in einen Pfeilwinkel übersetzen
    def trend_to_angle(current, forecast):
        if current is None or forecast is None:
            return None                     # kein Pfeil ohne beide Werte
        trend = forecast - current
        if trend <= -3:
            return 180                      # maximale Auslenkung nach unten
        if trend >= 3:
            return 0                        # maximale Auslenkung nach oben
        return 90 - trend * 30              # alle anderen Fälle: Zwischenstellungen je 30° berechnen

    #je Schadstoff aktuellen Index mit Worst-Case-Prognose vergleichen
    pollutants = daten.get("uba", {}).get("schadstoffe", {})
    trend_arrows = {}
    for name in ("PM2_5", "PM10", "NO2", "O3"):
        forecast = worst_forecast(pollutants.get(name, {}).get("Prognose"))
        trend_arrows[name] = trend_to_angle(lqi_out.get(name), forecast)

    return trend_arrows

#Lüftungsempfehlung
def fresh_air_algorithm(lqi_out_float: dict, lqi_in_float: dict) -> str:

    # Prüfung: Wenn keine Dictionaries übergeben wurden
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
        if k != "PM10" #PM10 wird ausgeschlossen
        and isinstance(v, (int, float)) and not math.isnan(v)# schließt None und NaN aus
    ]

    # Prüfung: Mindestens zwei gültige Werte pro Dictionary erforderlich
    if len(valid_out) < 2 or len(valid_in) < 2:
        return "-"

    # Höchsten Einzelwert ermitteln (x für außen, y für innen)
    x_out = max(valid_out)
    y_in = max(valid_in)

    # Shapely Koordinate erstellen
    coordinate = Point(x_out, y_in)

    # Zonen als Polygone definieren
    zonen = [
        (
            Polygon([(0, 0), (2, 0), (2, 1.7), (3, 2.7), (2.7, 3), (1.7, 2), (0, 2),]),
            "Lüften optional",
        ),
        (
            Polygon([(2, 0), (3, 0), (3, 2.7), (2, 1.7)]),
            "Lüften nicht empf.",
        ),
        (
            Polygon([(0, 2), (1.7, 2), (2.7, 3), (0, 3)]),
            "Lüften empfohlen",
        ),
        (
            Polygon([(2.7, 3), (3, 2.7), (5, 3.3), (5, 5), (3.3, 5)]),
            "Stoßlüften!",
        ),
        (
            Polygon([(3, 0), (5, 0), (5, 3.3), (3, 2.7)]),
            "Nicht lüften!",
        ),
        (
            Polygon([(0, 3), (2.7, 3), (3.3, 5), (0, 5)]),
            "Dringend lüften!",
        ),
    ]

    # Prüfen, in welchem Polygon der Punkt liegt
    for poly, fresh_air in zonen:
        if poly.intersects(coordinate):
            return fresh_air

    # Falls der Punkt unerwartet außerhalb der Polygone liegt
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

def csv_init(CSV_PATH):
    if CSV_PATH.exists():
        return
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";")
        writer.writeheader()

def csv_append(CSV_PATH, dashboard_data):
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

    with CSV_PATH.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, delimiter=";")
        writer.writerow(row)
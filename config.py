"""
Eingabe grundlegender Parameter zum Betrieb des Dashboards
"""
#Display
DISPLAY_INTERVAL = 1 #Minuten, Standard 1, Refresh-Intervall des Dashboards

#SEN66 Daten
WARMUP = 60         #in Sekunden, Empfehlung 60
SEN66_TIMEOUT = 5   #Minuten, Standard 5, Bestimmt Gültigkeitsdauer der Daten
PM2_5_FACTOR = 3.9  #In Messreihe ermittelter Korrekturfaktor 3.9
PM10_FACTOR = 4.2   #In Messreihe ermittelter Korrekturfaktor 4.2

#UBA Daten
#https://www.umweltbundesamt.de/daten/luft/luftdaten - Karte der Messstationen
#https://luftdaten.umweltbundesamt.de/api/air-data/v4/stations/json?use=airquality&lang=de - Stations-ID unter Punkt 0
STATION = '168'     #ID für PM2,5, PM10 und NO2
STATION_O3 = '121'  #ID für Ozon
STATION_SO2 = '21'  #ID für Schwefeldioxid
UBA_TIMEOUT = 4     #Stunden, Standard 4, Bestimmt Gültigkeitsdauer der Daten
FORECAST_FROM = 3   #Intervall der Trendpfeile in Stunden, Standard 3-12, max 24h
FORECAST_TO = 12

#Logging
CSV_LOGGING = True          #speichert Dashboard-Werte in csv, "True" oder "False"
CSV_LOGGING_INTERVAL = 5    #Minuten, Standard 5
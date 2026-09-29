"""
Layout des ePaper mit statischem und dynamischem Bildteil
Hochformat (SPI Interface oben), 128*296 Pixel

Inhalt
* Bereinigen des Displays zum Systemstart
* Startbildschirm
* Zeichnen statischer Anzeigeelemente (v. a. Geometrie)
* Zeichnen dynamischer Anzeigeelemente (Werte) und ggf. Invertierung
"""
from PIL import Image, ImageDraw, ImageChops

import logging

from config import DISPLAY_INTERVAL, STATION, STATION_O3, STATION_SO2

# Displaygeometrie
ROW_SPACE = 38
ROW_1 = round(1.5 * ROW_SPACE)
ROW_2 = ROW_1 + ROW_SPACE
ROW_3 = ROW_2 + ROW_SPACE
ROW_4 = ROW_3 + ROW_SPACE
ROW_5 = ROW_4 + ROW_SPACE
ROW_6 = ROW_5 + ROW_SPACE
ROW_7 = round(0.8 * ROW_SPACE + ROW_6)
MID_COLUMN = 64

# --- Bereinigen des Displays bei Systemstart
def display_cleanup(Display):
    Display.init() # ePaper ggf. aufwecken
    Display.Clear() # ePaper bereinigen

# --- Startbildschirm
def draw_startup(Display, Vertical_Image, draw, fonts):
    Display.init() # ePaper ggf. aufwecken
    Display.Clear() # ePaper bereinigen
    draw.rectangle((0, 0, Display.width, Display.height), fill=255) # PIL bereinigen
    text = (
        f'git:\nzuraffl\n/Luftqualitaet\n\n'
        f'Anzeige-\nintervall\n{DISPLAY_INTERVAL} min\n'
        f'Station:\n{STATION}\n'
        f'Station O3:\n{STATION_O3}\n'
        f'Station SO2:\n{STATION_SO2}'
    )
    draw.text(
        (MID_COLUMN, 15),
        text,
        font=fonts['f16'], fill=0, anchor='ma', align='center'
    )
    Display.display_Base(Display.getbuffer(Vertical_Image)) # Darstellen

# --- Feste Bildelemente mit Übergabe von Bildformat und Fonts aus main
def draw_static_image(Display, Vertical_Image, draw, fonts):

    Display.init() # ePaper ggf. aufwecken
    Display.Clear() # ePaper bereinigen
    draw.rectangle((0, 0, Display.width, Display.height), fill=255) # PIL bereinigen

    #Horizontale Linien
    draw.line((0, ROW_1, 127, ROW_1), fill = 0, width = 2)
    draw.line((0, ROW_2, 127, ROW_2), fill = 0, width = 2)
    draw.line((0, ROW_3, 127, ROW_3), fill = 0, width = 2)
    draw.line((0, ROW_4, 127, ROW_4), fill = 0, width = 2)
    draw.line((0, ROW_5, 127, ROW_5), fill = 0, width = 2)
    draw.line((0, ROW_6, 127, ROW_6), fill = 0, width = 2)
    draw.line((0, ROW_7, 127, ROW_7), fill = 0, width = 2)
    
    #Vertikale Linien
    draw.line((MID_COLUMN, 0, MID_COLUMN, ROW_1), fill = 0, width = 2)
    draw.line((MID_COLUMN, ROW_2-8, MID_COLUMN, ROW_2), fill = 0, width = 2)
    draw.line((MID_COLUMN, ROW_3-8, MID_COLUMN, ROW_3), fill = 0, width = 2)
    draw.line((MID_COLUMN, ROW_3, MID_COLUMN, ROW_6), fill = 0, width = 2)
    draw.line((MID_COLUMN-21, ROW_7, MID_COLUMN-21, 295), fill = 0)
    draw.line((MID_COLUMN+21, ROW_7, MID_COLUMN+21, 295), fill = 0) 
    
    #Überschrift
    draw.text((MID_COLUMN-32, 0), 'Außenluft', font = fonts['fNB14'], fill = 0, anchor='ma')
    draw.text((MID_COLUMN+32, 0), 'Innenluft', font = fonts['fNB14'], fill = 0, anchor='ma')
    
    #Schadstofftitel
    draw.text((MID_COLUMN, ROW_1), 'PM2,5', font = fonts['f16'], fill = 0, anchor='ma')
    draw.text((MID_COLUMN, ROW_2), 'PM10', font = fonts['f16'], fill = 0, anchor='ma')
    draw.text((MID_COLUMN-2, ROW_3), 'NO₂', font = fonts['f16'], fill = 0, anchor='ra')
    draw.text((MID_COLUMN+4, ROW_3), 'NOx', font = fonts['f16'], fill = 0, anchor='la')
    draw.text((MID_COLUMN-2, ROW_4), 'O₃', font = fonts['f16'], fill = 0, anchor='ra')
    draw.text((MID_COLUMN+4, ROW_4), 'VOC', font = fonts['f16'], fill = 0, anchor='la')
    draw.text((MID_COLUMN-2, ROW_5), 'SO₂', font = fonts['f16'], fill = 0, anchor='ra')
    draw.text((MID_COLUMN+4, ROW_5), 'CO₂', font = fonts['f16'], fill = 0, anchor='la')

    Display.display_Base(Display.getbuffer(Vertical_Image)) # Full Refresh

# --- Aktualisierung dynamischer Bildelemente
def draw_dynamic_image(Display, Vertical_Image, draw, fonts, data_out, data_in, lqi_out, lqi_in, overall, arrows, trend, fresh_air, time_now):
    # Gesamtqualität
    draw.multiline_text((MID_COLUMN-32, ROW_1), f"{overall['overall_out']}", font = fonts['f16'], fill = 0, anchor = 'md', align = 'center',spacing = 2)
    draw.multiline_text((MID_COLUMN+32, ROW_1), f"{overall['overall_in']}", font = fonts['f16'], fill = 0, anchor = 'md', align = 'center',spacing = 2)
    
    # Messwerte außen
    draw.text((MID_COLUMN-5, ROW_2-2), f"{data_out['PM2_5']}" if data_out['PM2_5'] is not None else "-", font = fonts['f14'], fill = 0, anchor='rb')
    draw.text((MID_COLUMN-5, ROW_3-2), f"{data_out['PM10']}" if data_out['PM10'] is not None else "-", font = fonts['f14'], fill = 0, anchor='rb')
    draw.text((MID_COLUMN-5, ROW_4-2), f"{data_out['NO2']}" if data_out['NO2'] is not None else "-", font = fonts['f14'], fill = 0, anchor='rb')
    draw.text((MID_COLUMN-5, ROW_5-2), f"{data_out['O3']}" if data_out['O3'] is not None else "-", font = fonts['f14'], fill = 0, anchor='rb')
    draw.text((MID_COLUMN-5, ROW_6-2), f"{data_out['SO2']}" if data_out['SO2'] is not None else "-", font = fonts['f14'], fill = 0, anchor='rb')

    # Messwerte innen
    draw.text((MID_COLUMN+5, ROW_2-2), f"{data_in['PM2_5']:.0f}" if data_in['PM2_5'] is not None else "-", font = fonts['f14'], fill = 0, anchor='lb')
    draw.text((MID_COLUMN+5, ROW_3-2), f"{data_in['PM10']:.0f}" if data_in['PM10'] is not None else "-", font = fonts['f14'], fill = 0, anchor='lb')
    draw.text((MID_COLUMN+5, ROW_4-2), f"{data_in['NOx']:.0f}" if data_in['NOx'] is not None else "-", font = fonts['f14'], fill = 0, anchor='lb')
    draw.text((MID_COLUMN+5, ROW_5-2), f"{data_in['VOC']:.0f}" if data_in['VOC'] is not None else "-", font = fonts['f14'], fill = 0, anchor='lb')
    draw.text((MID_COLUMN+5, ROW_6-2), f"{data_in['CO2']:.0f}" if data_in['CO2'] is not None else "-", font = fonts['f14'], fill = 0, anchor='lb')
    
    # Indizes außen
    draw.text((3, ROW_1), f"{lqi_out['PM2_5']+1}" if lqi_out['PM2_5'] is not None else "-", font = fonts['f16'], fill = 0, anchor='la')
    draw.text((3, ROW_2), f"{lqi_out['PM10']+1}" if lqi_out['PM10'] is not None else "-", font = fonts['f16'], fill = 0, anchor='la')
    draw.text((3, ROW_3), f"{lqi_out['NO2']+1}" if lqi_out['NO2'] is not None else "-", font = fonts['f16'], fill = 0, anchor='la')
    draw.text((3, ROW_4), f"{lqi_out['O3']+1}" if lqi_out['O3'] is not None else "-", font = fonts['f16'], fill = 0, anchor='la')
    draw.text((3, ROW_5), f"{lqi_out['SO2']+1}" if lqi_out['SO2'] is not None else "-", font = fonts['f16'], fill = 0, anchor='la')

    # Indizes innen
    draw.text((124, ROW_1), f"{lqi_in['PM2_5']+1}" if lqi_in['PM2_5'] is not None else "-", font = fonts['f16'], fill = 0, anchor='ra')
    draw.text((124, ROW_2), f"{lqi_in['PM10']+1}" if lqi_in['PM10'] is not None else "-", font = fonts['f16'], fill = 0, anchor='ra')
    draw.text((124, ROW_3), f"{lqi_in['NOx']+1}" if lqi_in['NOx'] is not None else "-", font = fonts['f16'], fill = 0, anchor='ra')
    draw.text((124, ROW_4), f"{lqi_in['VOC']+1}" if lqi_in['VOC'] is not None else "-", font = fonts['f16'], fill = 0, anchor='ra')
    draw.text((124, ROW_5), f"{lqi_in['CO2']+1}" if lqi_in['CO2'] is not None else "-", font = fonts['f16'], fill = 0, anchor='ra')

    # Trendpfeile außen
    if trend["PM2_5"] is not None:
        Vertical_Image.paste(arrows[trend["PM2_5"]], (MID_COLUMN-50, ROW_1+3))
    if trend["PM10"] is not None:
        Vertical_Image.paste(arrows[trend["PM10"]] , (MID_COLUMN-50,ROW_2+3))
    if trend["NO2"] is not None:
        Vertical_Image.paste(arrows[trend["NO2"]] , (MID_COLUMN-50,ROW_3+3))
    if trend["O3"] is not None:   
        Vertical_Image.paste(arrows[trend["O3"]] , (MID_COLUMN-50,ROW_4+3)) 

    # Lüftempfehlung
    draw.text((MID_COLUMN, (ROW_6+ROW_7)/2), fresh_air if fresh_air is not None else "-", font = fonts['fNB16'], fill = 0, anchor='mm')

    #Temperatur, Uhrzeit, Luftfeuchte (rein informativ)
    draw.text((MID_COLUMN-43, (ROW_7+295)/2), f"{data_in['Temperature']:.1f}\u2009°C" if data_in['Temperature'] is not None else "-", font=fonts['f12'], fill=0, anchor='mm')
    draw.text((MID_COLUMN, (ROW_7+295)/2), time_now if time_now is not None else "-", font = fonts['f12'], fill = 0, anchor='mm')
    draw.text((MID_COLUMN+43, (ROW_7+295)/2), f"{data_in['Humidity']:.0f}\u2009%" if data_in['Humidity'] is not None else "-", font = fonts['f12'], fill = 0, anchor='mm')

    #Invertierung eines Wertes bei sehr schlechter Luftqualität
    #Liste von Tupeln mit Geometrien
    boxes = [
        (overall["overall_out_no"], (0, 0, MID_COLUMN, ROW_1), (0, ROW_1-20, MID_COLUMN, ROW_1)),
        (overall["overall_in_no"], (MID_COLUMN+2, 0, 128, ROW_1), (MID_COLUMN+2, ROW_1-20, 128, ROW_1)),
        (lqi_out["PM2_5"], (0, ROW_1+2, MID_COLUMN, ROW_2), (0, ROW_1+2, 13, ROW_2)),
        (lqi_out["PM10"], (0, ROW_2+2, MID_COLUMN, ROW_3), (0, ROW_2+2, 13, ROW_3)),
        (lqi_out["NO2"], (0, ROW_3+2, MID_COLUMN, ROW_4), (0, ROW_3+2, 13, ROW_4)),
        (lqi_out["O3"], (0, ROW_4+2, MID_COLUMN, ROW_5), (0, ROW_4+2, 13, ROW_5)),
        (lqi_out["SO2"], (0, ROW_5+2, MID_COLUMN, ROW_6), (0, ROW_5+2, 13, ROW_6)),
        (lqi_in["PM2_5"], (MID_COLUMN+2, ROW_1+2, 128, ROW_2), (114, ROW_1+2, 128, ROW_2)),
        (lqi_in["PM10"], (MID_COLUMN+2, ROW_2+2, 128, ROW_3), (114, ROW_2+2, 128, ROW_3)),
        (lqi_in["NOx"], (MID_COLUMN+2, ROW_3+2, 128, ROW_4), (114, ROW_3+2, 128, ROW_4)),
        (lqi_in["VOC"], (MID_COLUMN+2, ROW_4+2, 128, ROW_5), (114, ROW_4+2, 128, ROW_5)),
        (lqi_in["CO2"], (MID_COLUMN+2, ROW_5+2, 128, ROW_6), (114, ROW_5+2, 128, ROW_6)),
    ]

    #Die bereits geschriebenen Zellen werden invertiert
    for value, box_invert, box_part_invert in boxes:
        if value in (3, 4):
            Vertical_Image.paste(ImageChops.invert(Vertical_Image.crop(box_invert)), box_invert)
        elif value == 2:
            Vertical_Image.paste(ImageChops.invert(Vertical_Image.crop(box_part_invert)), box_part_invert)

    #Invertierung der Lüftungsempfehlung bei dringender Empfehlung
    fresh_air_box = (0, ROW_6+2, 128, ROW_7)

    if fresh_air in ("Dringend lüften!", "Nicht lüften!", "Stoßlüften!"):
        Vertical_Image.paste(ImageChops.invert(Vertical_Image.crop(fresh_air_box)), fresh_air_box)

    Display.display_Partial(Display.getbuffer(Vertical_Image)) # Partial Refresh
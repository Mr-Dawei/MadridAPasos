# -*- coding: utf-8 -*-
"""Configuración central de MadridAPasos.

Las claves se leen (en este orden) de st.secrets, de variables de entorno y, si no existen,
quedan vacías: la app sigue funcionando sin ellas (usa servicios públicos de respaldo).
NUNCA escribas claves ni contraseñas en el código.
"""
import os
from pathlib import Path

try:
    import streamlit as st
except ImportError:                      # scripts y tests sin Streamlit
    st = None


def _leer_clave(nombre, valor_local=""):
    if st is not None:
        try:
            if nombre in st.secrets:
                return str(st.secrets[nombre])
        except Exception:                # no hay secrets.toml
            pass
    return os.getenv(nombre, valor_local)


# ---------------- Claves y acceso ----------------
ORS_API_KEY = _leer_clave("ORS_API_KEY")
APP_PASSWORD = _leer_clave("APP_PASSWORD")        # vacío = sin pantalla de acceso

# ---------------- Marca ----------------
APP_NAME = "MadridAPasos"
APP_TAGLINE = "Rutas que respiran contigo"

# ---------------- Rutas de ficheros ----------------
RUTA_PROYECTO = Path(__file__).resolve().parent
RUTA_DATOS = RUTA_PROYECTO / "data"
ARCHIVO_MALLA_ARBOLADO = "arbolado_malla.npz"     # versión compacta del CSV (ver tools/preparar_arbolado.py)
ARCHIVO_ARBOLADO_CSV = "arbolado.csv"
ZONA_HORARIA = "Europe/Madrid"
BBOX_MADRID = (-3.90, 40.30, -3.50, 40.60)        # lon_min, lat_min, lon_max, lat_max

# ---------------- Clima: umbrales sobre la temperatura REAL (no dependen del mes) ----------------
UMBRALES = {"calor": 28.0, "frio": 8.0, "uv": 6.5, "lluvia": 1.0}    # °C, °C, índice UV, mm/h

# ---------------- Perfiles de paseo ----------------
PERFILES = {
    "tranquilo":          {"etiqueta": "Tranquilo",          "icono": "🌿", "ritmo_m_min": 55},   # ≈ 3,3 km/h
    "activo":             {"etiqueta": "Activo",             "icono": "🏃", "ritmo_m_min": 83},   # ≈ 5,0 km/h
    "movilidad_reducida": {"etiqueta": "Movilidad reducida", "icono": "♿", "ritmo_m_min": 45},   # ≈ 2,7 km/h
}
MIN_POR_PARADA = 5          # tiempo medio que se pasa en cada parada
FACTOR_CALLE = 1.3          # distancia por calle ≈ 1,3 × distancia en línea recta

# ---------------- Categorías de puntos de interés ----------------
# techo=True → cuenta como refugio (lluvia/calor). Los centros de mayores exigen carné de socio,
# por eso se muestran como interés pero no como refugio.
CATEGORIAS = {
    "parques":            {"fichero": "parques.geo",            "etiqueta": "Parques y jardines",  "icono": "🌳", "color": "#2E9E5B", "interes": 0.9, "techo": False},
    "monumentos":         {"fichero": "monumentos.geo",         "etiqueta": "Monumentos",          "icono": "🏛", "color": "#B45309", "interes": 0.5, "techo": False},
    "museos":             {"fichero": "museos.geo",             "etiqueta": "Museos",              "icono": "🖼", "color": "#7C3AED", "interes": 1.0, "techo": True},
    "bibliotecas":        {"fichero": "bibliotecas.geo",        "etiqueta": "Bibliotecas",         "icono": "📚", "color": "#0E7490", "interes": 0.6, "techo": True},
    "centros_culturales": {"fichero": "centros_culturales.geo", "etiqueta": "Centros culturales",  "icono": "🎭", "color": "#BE185D", "interes": 0.6, "techo": True},
    "centros_mayores":    {"fichero": "centros_mayores.geo",    "etiqueta": "Centros de mayores",  "icono": "👥", "color": "#EA580C", "interes": 0.3, "techo": False},
    "fuentes":            {"fichero": "fuentes.json",           "etiqueta": "Fuentes de agua",     "icono": "⛲", "color": "#0A84FF", "interes": 0.3, "techo": False},
}
REFUGIO_CATEGORIAS = tuple(k for k, v in CATEGORIAS.items() if v["techo"])
# Entradas de los feeds que son edificios públicos pero NO sirven de refugio para cualquier persona:
EXCLUIR_REFUGIO_PATRON = r"(?i)instalaci[oó]n deportiva|asesoramiento|juvenil"
CATEGORIAS_DEFECTO = ("parques", "monumentos", "museos", "bibliotecas", "centros_culturales")

# ---------------- Horarios ----------------
# Los feeds oficiales NO traen horarios estructurados (solo un enlace a madrid.es), así que se usan
# horarios estimados por categoría (minutos desde las 00:00). Se avisa siempre al usuario.
# lv = lunes-viernes, fs = sábado-domingo, cerrado = días (0=lunes … 6=domingo) en que no abre.
HORARIOS_DEFECTO = {
    "museos":             {"lv": (600, 1140), "fs": (600, 1140), "cerrado": (0,)},
    "bibliotecas":        {"lv": (510, 1260), "fs": (510, 900),  "cerrado": ()},
    "centros_culturales": {"lv": (540, 1260), "fs": (540, 1260), "cerrado": (5, 6)},
}
MARGEN_CIERRE_MIN = {"bibliotecas": 30, "museos": 75, "centros_culturales": 30}   # no mandar a alguien al límite

# ---------------- Lugares frecuentes y zona "centro" ----------------
LUGARES_MADRID = {
    "Puerta del Sol": (40.4169, -3.7035),
    "Parque del Retiro (Puerta de Alcalá)": (40.4199, -3.6887),
    "Estación de Atocha": (40.4065, -3.6896),
    "Templo de Debod": (40.4240, -3.7178),
    "Plaza Mayor": (40.4155, -3.7074),
    "Matadero Madrid (Madrid Río)": (40.3917, -3.6974),
    "Nuevos Ministerios": (40.4463, -3.6921),
}
CENTRO_LAT, CENTRO_LON, CENTRO_RADIO_M = 40.4169, -3.7035, 1200

# -*- coding: utf-8 -*-
"""Utilidades geográficas, horarios, clima y elevación."""
import os
import re
from datetime import datetime, time
from math import radians, cos, sin, asin, sqrt

import numpy as np
import pandas as pd

try:
    from config import OPEN_ELEVATION_KEY as _CFG_KEY
except ImportError:
    _CFG_KEY = os.getenv("OPEN_ELEVATION_KEY", "")

OPEN_ELEVATION_KEY = _CFG_KEY or os.getenv("OPEN_ELEVATION_KEY", "")


# ---------------- HAVERSINE ----------------
def haversine(lat1, lon1, lat2, lon2):
    r = 6371000
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def haversine_vec(lat1, lon1, lats2, lons2):
    r = 6371000.0
    lat1, lon1 = radians(lat1), radians(lon1)
    lat2 = np.radians(np.asarray(lats2, dtype=float))
    lon2 = np.radians(np.asarray(lons2, dtype=float))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


# ---------------- PERFIL CLIMÁTICO ----------------
def obtener_estacion(fecha=None):
    fecha = fecha or datetime.now()
    mes = fecha.month
    if mes in (3, 4, 5):
        return "primavera"
    if mes in (6, 7, 8):
        return "verano"
    if mes in (9, 10, 11):
        return "otono"
    return "invierno"


# Umbrales confirmados (calor a 28 °C en cualquier estación)
UMBRALES_CLIMA = {
    "primavera": {"temp_calor": 28.0, "temp_frio": None, "uv": None},
    "verano":    {"temp_calor": 28.0, "temp_frio": None, "uv": 6.5},
    "otono":     {"temp_calor": 28.0, "temp_frio": 8.0,  "uv": None},
    "invierno":  {"temp_calor": 28.0, "temp_frio": 8.0,  "uv": None},
}
UMBRAL_LLUVIA = 1.0   # mm/h


def necesita_refugio(temp, lluvia, uv, estacion):
    """True si las condiciones obligan a buscar refugio con techo."""
    u = UMBRALES_CLIMA[estacion]
    if lluvia is not None and lluvia > UMBRAL_LLUVIA:
        return True, "lluvia"
    if u["temp_calor"] is not None and temp is not None and temp >= u["temp_calor"]:
        return True, "calor"
    if u["uv"] is not None and uv is not None and uv >= u["uv"]:
        return True, "uv"
    if u["temp_frio"] is not None and temp is not None and temp < u["temp_frio"]:
        return True, "frio"
    return False, None


# ---------------- HORARIOS ----------------
def _parse_hhmm(txt):
    m = re.match(r"(\d{1,2})[:.](\d{2})", txt.strip())
    if not m:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def parsear_horario_texto(texto):
    if not texto:
        return None, None
    m = re.search(r"de\s+(\d{1,2}[:.]\d{2})\s+a\s+(\d{1,2}[:.]\d{2})", texto, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d{1,2}[:.]\d{2})\s*(?:h|hrs?)?\s*a\s*(\d{1,2}[:.]\d{2})", texto, re.IGNORECASE)
    if not m:
        return None, None
    return _parse_hhmm(m.group(1)), _parse_hhmm(m.group(2))


HORARIO_BIBLIOTECAS = {
    "lv": (time(8, 30), time(21, 0)),
    "lv_verano": (time(8, 30), time(20, 0)),
    "finde": (time(8, 30), time(15, 0)),
}


def en_horario(apertura, cierre, ahora, margen_min=0):
    if apertura is None or cierre is None:
        return True
    ahora_min = ahora.hour * 60 + ahora.minute
    ap_min = apertura.hour * 60 + apertura.minute
    ci_min = cierre.hour * 60 + cierre.minute - margen_min
    return ap_min <= ahora_min <= ci_min


def calcular_abierto_ahora(df, ahora):
    """Añade columna 'abierto_ahora'. Robusta ante tipos inesperados."""
    df = df.copy()
    ahora_min = ahora.hour * 60 + ahora.minute

    def _es_valido(x):
        if x is None:
            return False
        try:
            if pd.isna(x):
                return False
        except (ValueError, TypeError):
            return False
        return True

    resultados = []
    for _, r in df.iterrows():
        ap = r["apertura"]
        ci = r["cierre"]
        m = r.get("margen_min", 0)

        if not _es_valido(ap) or not _es_valido(ci):
            resultados.append(True)
            continue

        # Si por lo que sea llegasen como tuplas/listas, tomamos el primer elemento
        if isinstance(ap, (tuple, list)):
            ap = ap[0] if ap else None
        if isinstance(ci, (tuple, list)):
            ci = ci[0] if ci else None

        if not hasattr(ap, "hour") or not hasattr(ci, "hour"):
            resultados.append(True)
            continue

        try:
            m_int = int(m) if (m is not None and not pd.isna(m)) else 0
        except (ValueError, TypeError):
            m_int = 0

        ap_min = ap.hour * 60 + ap.minute
        ci_min = ci.hour * 60 + ci.minute - m_int
        resultados.append(ap_min <= ahora_min <= ci_min)

    df["abierto_ahora"] = resultados
    return df

# ---------------- ELEVACIÓN ----------------
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"


def cargar_elevacion(coords_latlon, key=None):
    """
    Consulta elevación de una lista [(lat, lon), ...].
    Devuelve lista de alturas (m) o None si falla algún punto.
    """
    import requests
    if not coords_latlon:
        return []
    clave = key or OPEN_ELEVATION_KEY
    headers = {"Accept": "application/json"}
    if clave:
        headers["Authorization"] = f"Token {clave}"

    alturas = []
    for i in range(0, len(coords_latlon), 100):
        lote = coords_latlon[i:i + 100]
        locations = [{"latitude": float(a), "longitude": float(b)} for a, b in lote]
        try:
            r = requests.post(OPEN_ELEVATION_URL, json={"locations": locations},
                              headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            alturas.extend([p["elevation"] for p in data.get("results", [])])
        except Exception:
            alturas.extend([None] * len(lote))
    return alturas
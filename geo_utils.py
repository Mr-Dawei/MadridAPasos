# -*- coding: utf-8 -*-
"""Geometría, coordenadas UTM, horarios y clima. Sin dependencias de Streamlit (se puede testear)."""
import re
from datetime import datetime
from math import radians, cos, sin, asin, sqrt

import numpy as np
import pandas as pd

from config import UMBRALES, ZONA_HORARIA


# ---------------- DISTANCIAS ----------------
def haversine(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos puntos."""
    r = 6371000
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def haversine_vec(lat1, lon1, lats2, lons2):
    """Distancia en metros de un punto a muchos (vectorizado)."""
    r = 6371000.0
    lat1, lon1 = radians(lat1), radians(lon1)
    lat2 = np.radians(np.asarray(lats2, dtype=float))
    lon2 = np.radians(np.asarray(lons2, dtype=float))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


# ---------------- UTM 30N (ETRS89) ↔ WGS84, solo numpy ----------------
# Los ficheros de arbolado y fuentes vienen en UTM; así no hace falta pyproj.
_A, _F, _K0 = 6378137.0, 1 / 298.257222101, 0.9996
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_LON0 = np.radians(-3.0)                       # meridiano central del huso 30


def latlon_a_utm(lat, lon):
    phi = np.radians(np.asarray(lat, dtype=float))
    lam = np.radians(np.asarray(lon, dtype=float))
    n = _A / np.sqrt(1 - _E2 * np.sin(phi) ** 2)
    t, c, a = np.tan(phi) ** 2, _EP2 * np.cos(phi) ** 2, (lam - _LON0) * np.cos(phi)
    m = _A * ((1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256) * phi
              - (3 * _E2 / 8 + 3 * _E2**2 / 32 + 45 * _E2**3 / 1024) * np.sin(2 * phi)
              + (15 * _E2**2 / 256 + 45 * _E2**3 / 1024) * np.sin(4 * phi)
              - (35 * _E2**3 / 3072) * np.sin(6 * phi))
    x = _K0 * n * (a + (1 - t + c) * a**3 / 6 + (5 - 18 * t + t**2 + 72 * c - 58 * _EP2) * a**5 / 120) + 500000.0
    y = _K0 * (m + n * np.tan(phi) * (a**2 / 2 + (5 - t + 9 * c + 4 * c**2) * a**4 / 24
                                      + (61 - 58 * t + t**2 + 600 * c - 330 * _EP2) * a**6 / 720))
    return x, y


def utm_a_latlon(x, y):
    mu = (np.asarray(y, dtype=float) / _K0) / (_A * (1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256))
    e1 = (1 - np.sqrt(1 - _E2)) / (1 + np.sqrt(1 - _E2))
    p = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * np.sin(2 * mu) + (21 * e1**2 / 16 - 55 * e1**4 / 32) * np.sin(4 * mu)
         + (151 * e1**3 / 96) * np.sin(6 * mu) + (1097 * e1**4 / 512) * np.sin(8 * mu))
    s, c, t = np.sin(p), np.cos(p), np.tan(p)
    n1, t1, c1 = _A / np.sqrt(1 - _E2 * s**2), t**2, _EP2 * c**2
    r1 = _A * (1 - _E2) / (1 - _E2 * s**2) ** 1.5
    d = (np.asarray(x, dtype=float) - 500000.0) / (n1 * _K0)
    lat = p - (n1 * t / r1) * (d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * _EP2) * d**4 / 24
                               + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * _EP2 - 3 * c1**2) * d**6 / 720)
    lon = _LON0 + (d - (1 + 2 * t1 + c1) * d**3 / 6
                   + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * _EP2 + 24 * t1**2) * d**5 / 120) / c
    return np.degrees(lat), np.degrees(lon)


# ---------------- HORA LOCAL ----------------
def ahora_madrid():
    """Hora local de Madrid (naive). El servidor suele estar en UTC: datetime.now() daría horarios erróneos."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(ZONA_HORARIA)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def formatear_hora(minutos):
    minutos = int(minutos)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


# ---------------- CLIMA ----------------
def evaluar_clima(temp, lluvia, uv):
    """Banderas de clima según umbrales de temperatura real.
    · lluvia → refugio OBLIGATORIO.   · calor/frío/uv → el refugio pesa más en el scoring."""
    u = UMBRALES
    f = {
        "lluvia": lluvia is not None and lluvia > u["lluvia"],
        "calor": temp is not None and temp >= u["calor"],
        "frio": temp is not None and temp < u["frio"],
        "uv": uv is not None and uv >= u["uv"],
    }
    f["refugio_ponderado"] = f["calor"] or f["frio"] or f["uv"]
    return f


# ---------------- HORARIOS ----------------
_RE_HORARIO = re.compile(r"(?:horario[^.]{0,40}?)?de\s+(\d{1,2})[:.](\d{2})\s*(?:h|hrs?)?\s*a\s*(\d{1,2})[:.](\d{2})", re.I)


def parsear_horario_texto(texto):
    """Franja 'de HH:MM a HH:MM' → (apertura_min, cierre_min) o (None, None). Solo formatos inequívocos."""
    if not texto:
        return None, None
    m = _RE_HORARIO.search(texto)
    if not m:
        return None, None
    ap, ci = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    return (ap, ci) if 360 <= ap < ci <= 1440 else (None, None)


def calcular_abierto_ahora(df, ahora):
    """Añade 'abierto_ahora' y 'cierra_min'. Vectorizado: tiene en cuenta día de la semana y margen de cierre.
    Lo que no tiene horario (parques, fuentes…) se considera siempre accesible."""
    df = df.copy()
    m, dow = ahora.hour * 60 + ahora.minute, ahora.weekday()
    fin_semana = dow >= 5
    ap = df["ap_fs" if fin_semana else "ap_min"].to_numpy(dtype=float)
    ci = df["ci_fs" if fin_semana else "ci_min"].to_numpy(dtype=float)
    margen = df["margen_min"].to_numpy(dtype=float)
    cerrado_hoy = ((df["cerrado_mask"].to_numpy(dtype=np.int64) >> dow) & 1).astype(bool)
    sin_horario = np.isnan(ap) | np.isnan(ci)
    abierto = np.where(sin_horario, True, (m >= ap) & (m <= ci - margen) & ~cerrado_hoy)
    df["abierto_ahora"] = abierto
    df["cierra_min"] = np.where(sin_horario, np.nan, ci)
    return df


def texto_estado(abierto, cierra_min, fuente):
    """Frase para la interfaz: 'Abierto hasta las 19:00 · horario orientativo'."""
    if fuente == "no_aplica":
        return "Acceso libre"
    base = f"Abierto hasta las {formatear_hora(cierra_min)}" if abierto else "Cerrado ahora"
    return base + (" · horario orientativo" if fuente == "estimado" else "")

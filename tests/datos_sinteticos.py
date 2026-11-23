# -*- coding: utf-8 -*-
"""Mundo sintético y pequeño para probar el planificador sin depender de los datos reales.
Origen en Sol. Hay un bosque de árboles al ESTE y ninguno al oeste: un buen scoring debe preferir el este."""
import math

import numpy as np
import pandas as pd

import _setup  # noqa: F401
import routing
from config import HORARIOS_DEFECTO, MARGEN_CIERRE_MIN, CATEGORIAS
from geo_utils import calcular_abierto_ahora, haversine, latlon_a_utm
from spatial import IndiceArbolado

LAT0, LON0 = 40.4169, -3.7035
MARTES_11 = pd.Timestamp("2026-11-24 11:00")
LUNES_11 = pd.Timestamp("2026-11-23 11:00")
MARTES_23 = pd.Timestamp("2026-11-24 23:00")


def _fila(cat, nombre, dx, dy):
    lat = LAT0 + dy / 111000
    lon = LON0 + dx / (111000 * math.cos(math.radians(LAT0)))
    x, y = latlon_a_utm(lat, lon)
    h = HORARIOS_DEFECTO.get(cat)
    nan = float("nan")
    return {"categoria": cat, "nombre": nombre, "lat": lat, "lon": lon, "x": float(x), "y": float(y), "descripcion": "", "url": "",
            "tiene_techo": CATEGORIAS[cat]["techo"], "ap_min": h["lv"][0] if h else nan, "ci_min": h["lv"][1] if h else nan,
            "ap_fs": h["fs"][0] if h else nan, "ci_fs": h["fs"][1] if h else nan,
            "cerrado_mask": sum(1 << d for d in h["cerrado"]) if h else 0, "margen_min": float(MARGEN_CIERRE_MIN.get(cat, 0)),
            "horario_fuente": "estimado" if h else "no_aplica"}


def registro(ahora=MARTES_11):
    filas = [_fila("museos", "Museo Este", 500, 100), _fila("museos", "Museo Oeste", -500, 50), _fila("museos", "Museo Sur", 0, -450),
             _fila("bibliotecas", "Biblioteca Norte", 50, 600), _fila("parques", "Parque Este", 650, -100),
             _fila("parques", "Parque Oeste", -650, -100), _fila("monumentos", "Estatua Este", 350, 300),
             _fila("monumentos", "Estatua Oeste", -350, 300), _fila("monumentos", "Estatua Sur", 150, -500),
             _fila("centros_culturales", "Centro Cultural Norte", -200, 500),
             _fila("fuentes", "Fuente 1", 400, 0), _fila("fuentes", "Fuente 2", 800, 50), _fila("fuentes", "Fuente 3", -300, 0)]
    return calcular_abierto_ahora(pd.DataFrame(filas), ahora)


def indice():
    ox, oy = latlon_a_utm(LAT0, LON0)
    rng = np.random.default_rng(0)
    x, y = ox + rng.uniform(150, 1300, 40000), oy + rng.uniform(-900, 900, 40000)
    return IndiceArbolado.desde_puntos(x, y, np.ones_like(x))


def router_falso(puntos, movilidad=False):
    coords = []
    for (a, b), (c, d) in zip(puntos, puntos[1:]):
        for t in np.linspace(0, 1, 15, endpoint=False):
            coords.append([b + (d - b) * t, a + (c - a) * t])
    coords.append([puntos[-1][1], puntos[-1][0]])
    km = sum(haversine(*p, *q) for p, q in zip(puntos, puntos[1:])) * 1.3 / 1000
    return routing.Ruta(coords, km, [{"texto": "Sigue", "distancia_m": km * 1000, "inicio_m": 0.0}], "ors", ascenso_m=10.0, frac_pendiente=0.0)


SIN_CLIMA = {"lluvia": False, "calor": False, "frio": False, "uv": False}

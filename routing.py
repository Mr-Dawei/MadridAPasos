# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
Rutas peatonales: ORS (con API key), FOSSGIS (fallback) y haversine (último recurso).
Soporta ruta directa, con parada y circular.
"""
import os
import requests
import streamlit as st

from geo_utils import haversine

try:
    from config import ORS_API_KEY as _CFG_ORS
except ImportError:
    _CFG_ORS = ""
ORS_API_KEY = _CFG_ORS or os.getenv("ORS_API_KEY", "")

ORS_BASE = "https://api.heigit.org/openrouteservice/v2/directions/foot-walking"


def _llamar_ors(coords_lonlat, body_extra=None):
    if not ORS_API_KEY:
        return None
    url = f"{ORS_BASE}/geojson"
    body = {"coordinates": coords_lonlat}
    if body_extra:
        body.update(body_extra)
    r = requests.post(url, json=body,
                      headers={"Authorization": ORS_API_KEY,
                               "Content-Type": "application/json"},
                      timeout=20)
    r.raise_for_status()
    f = r.json()["features"][0]
    km = f["properties"]["summary"]["distance"] / 1000
    minutos = max(1, int(f["properties"]["summary"]["duration"] / 60))
    return f["geometry"], km, minutos


def _llamar_fossgis(coords_lonlat):
    c = ";".join(f"{lon},{lat}" for lon, lat in coords_lonlat)
    url = f"https://routing.openstreetmap.de/routed-foot/route/v1/driving/{c}?overview=full&geometries=geojson"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    d = r.json()["routes"][0]
    return d["geometry"], d["distance"] / 1000, max(1, int(d["duration"] / 60))


def _fallback(coords_lonlat, origen, parada, destino):
    geom = {"type": "LineString", "coordinates": coords_lonlat}
    if parada is None:
        d = haversine(*origen, *destino)
    else:
        d = haversine(*origen, *parada) + haversine(*parada, *destino)
    return geom, d / 1000, max(1, int(d / 80))


@st.cache_data(ttl=600, show_spinner=False)
def calcular_ruta(origen, parada, destino):
    """Ruta peatonal. `parada=None` → ruta directa."""
    if parada is None:
        coords = [[origen[1], origen[0]], [destino[1], destino[0]]]
    else:
        coords = [[origen[1], origen[0]], [parada[1], parada[0]], [destino[1], destino[0]]]

    if ORS_API_KEY:
        try:
            return _llamar_ors(coords)
        except Exception as e:
            st.warning(f"ORS falló ({e}); probando FOSSGIS…")
    try:
        return _llamar_fossgis(coords)
    except Exception as e:
        st.warning(f"FOSSGIS falló ({e}); usando línea recta.")
    return _fallback(coords, origen, parada, destino)


@st.cache_data(ttl=600, show_spinner=False)
def calcular_ruta_circular(origen, duracion_min, seed=1):
    """
    Paseo circular: sale y vuelve al origen.
    Usa ORS round_trip. Si falla, genera un triángulo sintético como fallback.
    """
    if ORS_API_KEY:
        try:
            body_extra = {
                "options": {"round_trip": {"length": duracion_min * 80, "points": 3, "seed": seed}}
            }
            return _llamar_ors([[origen[1], origen[0]]], body_extra=body_extra)
        except Exception as e:
            st.warning(f"ORS circular falló ({e}); generando triángulo aproximado.")
    # Fallback: triángulo de ~duracion_min * 80 m de perímetro
    perim_m = duracion_min * 80
    lado_deg = (perim_m / 3) / 111000  # grados aprox
    lat0, lon0 = origen
    coords = [[lon0, lat0],
              [lon0 + lado_deg, lat0 + lado_deg * 0.7],
              [lon0 - lado_deg * 0.5, lat0 + lado_deg * 0.8],
              [lon0, lat0]]
    geom = {"type": "LineString", "coordinates": coords}
    return geom, perim_m / 1000, duracion_min


@st.cache_data(ttl=600, show_spinner=False)
def calcular_desnivel(geometria):
    """Desnivel acumulado en metros a partir de la geometría."""
    from geo_utils import cargar_elevacion
    coords = geometria.get("coordinates", []) if geometria else []
    if not coords:
        return 0.0
    # Muestrear cada 10 puntos para no saturar la API
    puntos = [(c[1], c[0]) for c in coords[::10]]
    e = cargar_elevacion(puntos)
    if not e:
        return 0.0
    subida = 0.0
    for i in range(1, len(e)):
        if e[i] is not None and e[i - 1] is not None:
            diff = e[i] - e[i - 1]
            if diff > 0:
                subida += diff
    return subida
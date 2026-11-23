# -*- coding: utf-8 -*-
"""Servicios cercanos por si hacen falta (farmacias, salud, desfibriladores, aseos, bancos) + aire y polen.

Fuentes abiertas y sin clave: OpenStreetMap (Overpass) y Open-Meteo. Sin dependencias de Streamlit.
Si un servicio externo no responde se devuelve None y la interfaz lo indica (nunca se inventan datos).
"""
import threading
import time

import requests

from geo_utils import haversine

OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
UA = {"User-Agent": "MadridAPasos/1.0 (demo datathon)"}

# clave: (etiqueta, icono, radio de búsqueda en m, filtro Overpass)
TIPOS = {
    "salud":    ("Centros de salud y hospitales", "🏥", 2500, 'nwr["amenity"~"^(hospital|clinic|doctors)$"]'),
    "farmacia": ("Farmacias", "💊", 1500, 'nwr["amenity"="pharmacy"]'),
    "dea":      ("Desfibriladores (DEA)", "❤️", 800, 'node["emergency"="defibrillator"]'),
    "aseos":    ("Aseos públicos", "🚻", 1000, 'nwr["amenity"="toilets"]'),
    "bancos":   ("Bancos para sentarse", "🪑", 400, 'node["amenity"="bench"]'),
}
SINGULAR = {"salud": "Centro de salud", "farmacia": "Farmacia", "dea": "Desfibrilador (DEA)",
            "aseos": "Aseo público", "bancos": "Banco"}
NIVELES_AQI = [(20, "Buena"), (40, "Razonable"), (60, "Moderada"), (80, "Mala"), (100, "Muy mala"), (10**9, "Extremadamente mala")]

_CACHE, _LOCK, _TTL = {}, threading.Lock(), 3600


def _consulta(lat, lon):
    cuerpo = "".join(f"{f}(around:{r},{lat},{lon});" for _, _, r, f in TIPOS.values())
    return f"[out:json][timeout:25];({cuerpo});out center 400;"


def _tipo(tags):
    a = tags.get("amenity")
    if a == "pharmacy":
        return "farmacia"
    if a in ("hospital", "clinic", "doctors"):
        return "salud"
    if a == "toilets":
        return "aseos"
    if a == "bench":
        return "bancos"
    if tags.get("emergency") == "defibrillator":
        return "dea"
    return None


def parsear_overpass(datos, lat, lon, max_por_tipo=3):
    """Respuesta de Overpass → {tipo: [{nombre, lat, lon, distancia_m}] ordenado por cercanía}."""
    out = {k: [] for k in TIPOS}
    for el in datos.get("elementos", datos.get("elements", [])):
        tags = el.get("tags", {})
        t = _tipo(tags)
        la = el.get("lat", el.get("center", {}).get("lat"))
        lo = el.get("lon", el.get("center", {}).get("lon"))
        if t is None or la is None or lo is None:
            continue
        d = haversine(lat, lon, la, lo)
        if d > TIPOS[t][2]:
            continue
        nombre = tags.get("name") or tags.get("operator") or tags.get("defibrillator:location") or SINGULAR[t]
        out[t].append({"nombre": nombre, "lat": la, "lon": lo, "distancia_m": round(d)})
    return {k: sorted(v, key=lambda x: x["distancia_m"])[:max_por_tipo] for k, v in out.items()}


def buscar_servicios(lat, lon, max_por_tipo=3):
    """Servicios cercanos o None si Overpass no responde. Caché de 1 h por zona (~100 m)."""
    k = (round(lat, 3), round(lon, 3))
    with _LOCK:
        hit = _CACHE.get(k)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": _consulta(lat, lon)}, headers=UA, timeout=30)
            r.raise_for_status()
            res = parsear_overpass(r.json(), lat, lon, max_por_tipo)
            with _LOCK:
                _CACHE[k] = (time.time(), res)
            return res
        except Exception:
            continue
    return None


def nivel_aqi(aqi):
    return next(nombre for tope, nombre in NIVELES_AQI if aqi <= tope)


def calidad_aire(lat, lon):
    """{'aqi', 'nivel', 'polen': {...}} con None donde no haya dato (el polen solo existe en temporada)."""
    out = {"aqi": None, "nivel": None, "polen": {}}
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    try:
        r = requests.get(url, timeout=8, headers=UA, params={"latitude": lat, "longitude": lon, "current": "european_aqi"})
        r.raise_for_status()
        aqi = r.json()["current"].get("european_aqi")
        if aqi is not None:
            out["aqi"], out["nivel"] = round(float(aqi)), nivel_aqi(float(aqi))
    except Exception:
        pass
    try:                                                  # petición aparte: si falla el polen no se pierde el aire
        r = requests.get(url, timeout=8, headers=UA, params={"latitude": lat, "longitude": lon,
                                                            "current": "grass_pollen,olive_pollen"})
        r.raise_for_status()
        c = r.json()["current"]
        out["polen"] = {n: c.get(k) for n, k in (("Gramíneas", "grass_pollen"), ("Olivo", "olive_pollen"))
                        if c.get(k) is not None}
    except Exception:
        pass
    return out

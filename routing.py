# -*- coding: utf-8 -*-
"""Rutas peatonales: OpenRouteService (con clave) → FOSSGIS/OSRM (sin clave) → línea recta.

Sin dependencias de Streamlit: qué servicio respondió viaja en Ruta.fuente / Ruta.avisos y la interfaz
decide cómo mostrarlo (nada de st.warning dentro de funciones cacheadas). Seguro para usar con hilos.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import requests

from config import BBOX_MADRID, FACTOR_CALLE, ORS_API_KEY
from geo_utils import haversine, latlon_a_utm

ORS_URL = "https://api.heigit.org/openrouteservice/v2/directions/foot-walking/geojson"
OSRM_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/driving"
ELEVACION_URL = "https://api.open-meteo.com/v1/elevation"
UA = {"User-Agent": "MadridAPasos/1.0 (demo datathon; contacto: ver README)"}


@dataclass
class Ruta:
    coords: list                                   # [[lon, lat] o [lon, lat, z], ...]
    km: float
    pasos: list = field(default_factory=list)      # [{"texto", "distancia_m", "inicio_m"}]
    fuente: str = "linea"                          # "ors" | "fossgis" | "linea"
    ascenso_m: Optional[float] = None
    descenso_m: Optional[float] = None
    frac_pendiente: Optional[float] = None         # fracción del recorrido con pendiente > 6 %
    avisos: List[str] = field(default_factory=list)

    def pts(self):
        return [(c[1], c[0]) for c in self.coords]


# ---------------- CACHÉ TTL (compartida y segura entre hilos) ----------------
_CACHE, _LOCK, _TTL, _MAX = {}, threading.Lock(), 3 * 3600, 300


def _cache_get(k):
    with _LOCK:
        v = _CACHE.get(k)
        if v and time.time() - v[0] < _TTL:
            return v[1]
        _CACHE.pop(k, None)
    return None


def _cache_set(k, ruta):
    with _LOCK:
        if len(_CACHE) >= _MAX:
            _CACHE.pop(min(_CACHE, key=lambda i: _CACHE[i][0]))
        _CACHE[k] = (time.time(), ruta)


def limpiar_cache():
    with _LOCK:
        _CACHE.clear()


def _resumen_error(e):
    """Texto corto del error, sin URL ni cabeceras (nunca debe filtrarse la clave)."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    return f"{type(e).__name__}{f' {code}' if code else ''}"


# ---------------- ALTIMETRÍA ----------------
def _perfil(z, d, paso=25.0):
    """(ascenso, descenso, fracción con pendiente > 6 %) a partir de cotas z y distancias acumuladas d."""
    if len(z) < 2 or d[-1] < 2 * paso:
        return 0.0, 0.0, 0.0
    g = np.arange(0, d[-1] + 1e-9, paso)
    zz = np.interp(g, d, z)
    if len(zz) >= 3:                                # media móvil de 3 para quitar ruido del MDT
        zz = np.convolve(np.pad(zz, 1, mode="edge"), np.ones(3) / 3, mode="valid")
    dz = np.diff(zz)
    frac = float((np.abs(zz[2:] - zz[:-2]) / (2 * paso) > 0.06).mean()) if len(zz) >= 3 else 0.0
    return float(dz[dz > 0].sum()), float(-dz[dz < 0].sum()), frac


def perfil_altimetrico(coords):
    """Perfil a partir de la coordenada z (ORS con elevation=true). (None,)*3 si no hay elevación."""
    if not coords or any(len(c) < 3 or c[2] is None for c in coords):
        return None, None, None
    a = np.asarray(coords, dtype=float)
    x, y = latlon_a_utm(a[:, 1], a[:, 0])
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    return _perfil(a[:, 2], d)


def _elevacion_open_meteo(coords, max_puntos=90):
    """Respaldo sin clave cuando la ruta no trae cotas (FOSSGIS). Una sola petición."""
    a = np.asarray([[c[0], c[1]] for c in coords], dtype=float)
    x, y = latlon_a_utm(a[:, 1], a[:, 0])
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    idx = np.unique(np.linspace(0, len(a) - 1, min(max_puntos, len(a))).astype(int))
    r = requests.get(ELEVACION_URL, timeout=8, headers=UA, params={
        "latitude": ",".join(f"{v:.5f}" for v in a[idx, 1]), "longitude": ",".join(f"{v:.5f}" for v in a[idx, 0])})
    r.raise_for_status()
    z = np.asarray(r.json()["elevation"], dtype=float)
    return _perfil(z, d[idx], paso=40.0)


# ---------------- PROVEEDORES ----------------
def _pasos_acumulados(textos_dist):
    pasos, acum = [], 0.0
    for texto, dist in textos_dist:
        pasos.append({"texto": texto, "distancia_m": float(dist), "inicio_m": acum})
        acum += float(dist)
    return pasos


def _ors(puntos, movilidad, clave):
    cuerpo = {"coordinates": [[lon, lat] for lat, lon in puntos], "language": "es",
              "elevation": True, "instructions": True}
    if movilidad:
        cuerpo["options"] = {"avoid_features": ["steps"]}
    cab = {"Authorization": clave, "Content-Type": "application/json"}
    r = requests.post(ORS_URL, json=cuerpo, headers=cab, timeout=20)
    if r.status_code == 400 and movilidad:          # por si 'steps' no estuviera admitido: reintento sin la opción
        cuerpo.pop("options")
        r = requests.post(ORS_URL, json=cuerpo, headers=cab, timeout=20)
    r.raise_for_status()
    f = r.json()["features"][0]
    props, coords = f["properties"], f["geometry"]["coordinates"]
    pasos = _pasos_acumulados((s["instruction"], s["distance"]) for seg in props["segments"] for s in seg["steps"])
    asc, desc, frac = perfil_altimetrico(coords)
    if props.get("ascent") is not None:             # cifra oficial de ORS si viene
        asc, desc = float(props["ascent"]), float(props.get("descent") or 0.0)
    return Ruta(coords, props["summary"]["distance"] / 1000, pasos, "ors", asc, desc, frac)


_MOD = {"left": "a la izquierda", "right": "a la derecha", "slight left": "ligeramente a la izquierda",
        "slight right": "ligeramente a la derecha", "sharp left": "girando mucho a la izquierda",
        "sharp right": "girando mucho a la derecha", "straight": "recto", "uturn": "dando la vuelta"}


def _texto_osrm(s):
    m = s.get("maneuver", {})
    tipo, mod, via = m.get("type", ""), _MOD.get(m.get("modifier", ""), ""), (s.get("name") or "").strip()
    en = f" por {via}" if via else ""
    if tipo == "depart":
        return f"Empieza a caminar{en}"
    if tipo == "arrive":
        return "Has llegado a tu parada"
    if tipo in ("roundabout", "rotary", "roundabout turn"):
        return f"En la rotonda, sigue{en}"
    if tipo in ("turn", "end of road", "fork", "on ramp", "off ramp") and mod:
        return f"Gira {mod}{en}"
    if mod and mod != "recto":
        return f"Continúa {mod}{en}"
    return f"Sigue recto{en}"


def _osrm(puntos):
    c = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in puntos)
    r = requests.get(f"{OSRM_URL}/{c}", timeout=15, headers=UA,
                     params={"overview": "full", "geometries": "geojson", "steps": "true"})
    r.raise_for_status()
    d = r.json()["routes"][0]
    pasos = _pasos_acumulados((_texto_osrm(s), s["distance"]) for leg in d["legs"] for s in leg["steps"])
    if pasos:
        pasos[-1]["texto"] = "Has llegado a tu destino"
    return Ruta(d["geometry"]["coordinates"], d["distance"] / 1000, pasos, "fossgis")


def _linea(puntos):
    coords = [[lon, lat] for lat, lon in puntos]
    km = sum(haversine(*a, *b) for a, b in zip(puntos, puntos[1:])) * FACTOR_CALLE / 1000
    return Ruta(coords, km, [{"texto": "Sin conexión con el servicio de rutas: sigue la línea marcada",
                              "distancia_m": km * 1000, "inicio_m": 0.0}], "linea",
                avisos=["No se pudo contactar con ningún servicio de rutas: se muestra una línea recta aproximada."])


# ---------------- API PÚBLICA ----------------
def calcular_ruta(puntos, movilidad=False, clave_ors=None):
    """Ruta a pie por los puntos [(lat, lon), …] (origen, paradas…, destino). Nunca lanza excepción de red."""
    puntos = [(float(a), float(b)) for a, b in puntos]
    clave = ORS_API_KEY if clave_ors is None else clave_ors
    k = (tuple((round(a, 5), round(b, 5)) for a, b in puntos), bool(movilidad), bool(clave))
    if (hit := _cache_get(k)) is not None:
        return hit
    avisos, ruta = [], None
    if clave:
        try:
            ruta = _ors(puntos, movilidad, clave)
        except Exception as e:
            avisos.append(f"OpenRouteService no respondió ({_resumen_error(e)}); uso el servidor público.")
    if ruta is None:
        try:
            ruta = _osrm(puntos)
        except Exception as e:
            avisos.append(f"El servidor público de rutas no respondió ({_resumen_error(e)}).")
    if ruta is None:
        ruta = _linea(puntos)
    elif ruta.ascenso_m is None:
        try:
            ruta.ascenso_m, ruta.descenso_m, ruta.frac_pendiente = _elevacion_open_meteo(ruta.coords)
        except Exception:
            pass                                    # sin altimetría: el scoring usa un valor neutro
    ruta.avisos = avisos + ruta.avisos
    if ruta.fuente != "linea":                      # la línea recta no se cachea: permite reintentar
        _cache_set(k, ruta)
    return ruta


# ---------------- GEOCODIFICACIÓN (buscar direcciones) ----------------
def _etiqueta(*partes):
    vistas, out = set(), []
    for p in partes:
        if p and p not in vistas:
            vistas.add(p); out.append(p)
    return ", ".join(out)


def _photon(texto, limite):
    lon0, lat0, lon1, lat1 = BBOX_MADRID
    r = requests.get("https://photon.komoot.io/api/", timeout=8, headers=UA,
                     params={"q": f"{texto}, Madrid", "limit": limite, "bbox": f"{lon0},{lat0},{lon1},{lat1}"})
    r.raise_for_status()
    res = []
    for f in r.json().get("features", []):
        p, (lon, lat) = f.get("properties", {}), f["geometry"]["coordinates"]
        calle = " ".join(x for x in (p.get("street"), p.get("housenumber")) if x)
        res.append({"nombre": _etiqueta(p.get("name") or calle, p.get("district") or p.get("locality"), p.get("city")),
                    "lat": float(lat), "lon": float(lon)})
    return res


def _nominatim(texto, limite):
    lon0, lat0, lon1, lat1 = BBOX_MADRID
    r = requests.get("https://nominatim.openstreetmap.org/search", timeout=8, headers=UA,
                     params={"q": texto, "format": "jsonv2", "limit": limite, "countrycodes": "es",
                             "viewbox": f"{lon0},{lat1},{lon1},{lat0}", "bounded": 1})
    r.raise_for_status()
    return [{"nombre": x["display_name"][:90], "lat": float(x["lat"]), "lon": float(x["lon"])} for x in r.json()]


def geocodificar(texto, limite=5):
    """Direcciones/lugares de Madrid que coinciden con el texto: [{nombre, lat, lon}]."""
    texto = (texto or "").strip()
    if len(texto) < 3:
        return []
    for proveedor in (_photon, _nominatim):
        try:
            res = proveedor(texto, limite)
            if res:
                return res
        except Exception:
            continue
    return []

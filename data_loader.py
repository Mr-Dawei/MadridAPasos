# -*- coding: utf-8 -*-
"""Carga y unificación de POIs + clima + emergencias."""
import json
import xml.etree.ElementTree as ET
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from geo_utils import parsear_horario_texto, HORARIO_BIBLIOTECAS

try:
    from pyproj import Transformer
    PYPROJ_OK = True
except ImportError:
    PYPROJ_OK = False

NS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "georss": "http://www.georss.org/georss",
    "geo":    "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "dc":     "http://purl.org/dc/elements/1.1/",
}

# Configuración de feeds Atom → categoría principal
FEEDS_ATOM = {
    "parques":            {"ruta": "parques.geo",            "tiene_techo": False, "icono": ("green", "tree")},
    "monumentos":         {"ruta": "monumentos.geo",         "tiene_techo": False, "icono": ("darkred", "landmark")},
    "museos":             {"ruta": "museos.geo",             "tiene_techo": True,  "icono": ("cadetblue", "university")},
    "bibliotecas":        {"ruta": "bibliotecas.geo",        "tiene_techo": True,  "icono": ("purple", "book")},
    "centros_culturales": {"ruta": "centros_culturales.geo", "tiene_techo": True,  "icono": ("darkblue", "theater-masks")},
    "centros_mayores":    {"ruta": "centros_mayores.geo",    "tiene_techo": True,  "icono": ("orange", "users")},
}

# Feeds de emergencias (opcionales: si no existen, no rompe)
FEEDS_EMERGENCIAS = {
    "farmacias":       {"ruta": "farmacias.geo",       "icono": ("lightgreen", "prescription-bottle")},
    "centros_salud":   {"ruta": "centros_salud.geo",   "icono": ("lightred", "hospital")},
    "comisarias":      {"ruta": "comisarias.geo",      "icono": ("gray", "shield-alt")},
}

RUTA_FUENTES_JSON = "fuentes.json"
RUTA_ARBOLADO_CSV = "arbolado.csv"
RUTA_CLIMA_API    = "clima.api"


# ---------------- FEED ATOM GENÉRICO ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_feed_atom(ruta):
    columnas = ["nombre", "lat", "lon", "descripcion"]
    try:
        tree = ET.parse(ruta)
    except Exception:
        return pd.DataFrame(columns=columnas)

    filas = []
    for entry in tree.getroot().findall("atom:entry", NS):
        nombre = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip()
        contenido = (entry.findtext("atom:content", default="", namespaces=NS) or "").strip()
        texto = contenido.replace("&lt;", "<").replace("&gt;", ">").replace("<p>", " ").replace("</p>", " ")

        lat = lon = None
        t_lat = entry.findtext("geo:lat", default=None, namespaces=NS)
        t_lon = entry.findtext("geo:long", default=None, namespaces=NS)
        if t_lat and t_lon:
            try:
                lat, lon = float(t_lat), float(t_lon)
            except ValueError:
                pass
        if lat is None:
            punto = entry.findtext("georss:point", default=None, namespaces=NS)
            if punto:
                partes = punto.strip().split()
                if len(partes) == 2:
                    try:
                        lat, lon = float(partes[0]), float(partes[1])
                    except ValueError:
                        pass
        if lat is None:
            continue

        filas.append({"nombre": nombre or "Lugar", "lat": lat, "lon": lon,
                      "descripcion": texto[:500]})

    if not filas:
        return pd.DataFrame(columns=columnas)
    return pd.DataFrame(filas)


# ---------------- FUENTES ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_fuentes():
    vacias = pd.DataFrame(columns=["nombre", "lat", "lon", "descripcion"])
    try:
        with open(RUTA_FUENTES_JSON, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return vacias

    if isinstance(datos, dict):
        registros = datos.get("result", {}).get("records") or datos.get("records") or [datos]
    elif isinstance(datos, list):
        registros = datos
    else:
        return vacias

    df = pd.DataFrame(registros)
    if df.empty:
        return vacias
    df.columns = [c.upper() for c in df.columns]
    if "LATITUD" not in df.columns or "LONGITUD" not in df.columns:
        return vacias

    df["LATITUD"] = pd.to_numeric(df["LATITUD"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df["LONGITUD"] = pd.to_numeric(df["LONGITUD"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df = df.dropna(subset=["LATITUD", "LONGITUD"])
    if "ESTADO" in df.columns:
        df = df[~df["ESTADO"].astype(str).str.contains("FUERA|CERRAD", case=False, na=False)]

    nombre_via = df.get("NOM_VIA", pd.Series([""] * len(df))).astype(str)
    out = pd.DataFrame({
        "nombre": "Fuente · " + nombre_via,
        "lat": df["LATITUD"], "lon": df["LONGITUD"], "descripcion": "",
    })
    return out.reset_index(drop=True)


# ---------------- ARBOLADO ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_arbolado(ruta=RUTA_ARBOLADO_CSV):
    vacio = pd.DataFrame(columns=["LATITUD", "LONGITUD"])
    try:
        df = pd.read_csv(ruta, sep=None, engine="python", on_bad_lines="skip", encoding="utf-8")
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(ruta, sep=None, engine="python", on_bad_lines="skip", encoding="latin-1")
        except Exception:
            return vacio
    except Exception:
        return vacio

    if df.empty:
        return vacio
    df.columns = [str(c).strip().upper() for c in df.columns]

    if "LATITUD" in df.columns and "LONGITUD" in df.columns:
        df["LATITUD"] = pd.to_numeric(df["LATITUD"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
        df["LONGITUD"] = pd.to_numeric(df["LONGITUD"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    elif any(c in df.columns for c in ("X", "COORD_X")) and any(c in df.columns for c in ("Y", "COORD_Y")):
        if not PYPROJ_OK:
            return vacio
        cx = "X" if "X" in df.columns else "COORD_X"
        cy = "Y" if "Y" in df.columns else "COORD_Y"
        e = pd.to_numeric(df[cx], errors="coerce")
        n = pd.to_numeric(df[cy], errors="coerce")
        if (e.abs().max() <= 180) and (n.abs().max() <= 90):
            df["LONGITUD"], df["LATITUD"] = e, n
        else:
            t = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
            lon, lat = t.transform(e.values, n.values)
            df["LATITUD"], df["LONGITUD"] = lat, lon
    else:
        return vacio

    df = df.dropna(subset=["LATITUD", "LONGITUD"])
    df = df[(df["LATITUD"].between(40.3, 40.6)) & (df["LONGITUD"].between(-3.85, -3.55))]
    return df.reset_index(drop=True)


# ---------------- CLIMA ----------------
@st.cache_data(ttl=600, show_spinner=False)
def cargar_clima():
    datos = None
    try:
        with open(RUTA_CLIMA_API, "r", encoding="utf-8", errors="replace") as f:
            datos = json.load(f)
    except Exception:
        pass

    if isinstance(datos, dict) and "current" in datos:
        c = datos["current"]
        return {"temp": float(c.get("temperature_2m", 22.0)),
                "lluvia": float(c.get("precipitation", 0.0)),
                "uv": float(c.get("uv_index", 0.0)),
                "fuente": "archivo"}

    try:
        url = ("https://api.open-meteo.com/v1/forecast"
               "?latitude=40.4168&longitude=-3.7038"
               "&current=temperature_2m,precipitation,uv_index"
               "&timezone=Europe%2FMadrid")
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        c = r.json()["current"]
        return {"temp": float(c.get("temperature_2m", 22.0)),
                "lluvia": float(c.get("precipitation", 0.0)),
                "uv": float(c.get("uv_index", 0.0)),
                "fuente": "open-meteo"}
    except Exception:
        return {"temp": 22.0, "lluvia": 0.0, "uv": 0.0, "fuente": "fallback"}


# ---------------- REGISTRO UNIFICADO ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def construir_registro_pois(categorias_activas):
    filas = []
    for cat, cfg in FEEDS_ATOM.items():
        if cat not in categorias_activas:
            continue
        df = cargar_feed_atom(cfg["ruta"])
        for _, r in df.iterrows():
            ap, ci = parsear_horario_texto(r["descripcion"])
            if cat == "bibliotecas" and ap is None:
                ap, ci = HORARIO_BIBLIOTECAS["lv"]
            margen = 30 if cat == "bibliotecas" else (75 if cat == "museos" else 0)
            filas.append({
                "categoria": cat, "nombre": r["nombre"],
                "lat": r["lat"], "lon": r["lon"], "descripcion": r["descripcion"],
                "tiene_techo": cfg["tiene_techo"], "icono": cfg["icono"],
                "apertura": ap, "cierre": ci, "margen_min": margen,
                "horario_desconocido": (ap is None and ci is None),
            })

    if "fuentes" in categorias_activas:
        for _, r in cargar_fuentes().iterrows():
            filas.append({
                "categoria": "fuentes", "nombre": r["nombre"],
                "lat": r["lat"], "lon": r["lon"], "descripcion": "",
                "tiene_techo": False, "icono": ("blue", "tint"),
                "apertura": None, "cierre": None, "margen_min": 0,
                "horario_desconocido": True,
            })

    if not filas:
        return pd.DataFrame(columns=["categoria","nombre","lat","lon","descripcion",
                                      "tiene_techo","icono","apertura","cierre",
                                      "margen_min","horario_desconocido"])
    return pd.DataFrame(filas)


@st.cache_data(ttl=3600, show_spinner=False)
def construir_registro_emergencias():
    filas = []
    for cat, cfg in FEEDS_EMERGENCIAS.items():
        df = cargar_feed_atom(cfg["ruta"])
        for _, r in df.iterrows():
            filas.append({
                "categoria": cat, "nombre": r["nombre"],
                "lat": r["lat"], "lon": r["lon"], "descripcion": r["descripcion"],
                "icono": cfg["icono"],
            })
    if not filas:
        return pd.DataFrame(columns=["categoria","nombre","lat","lon","descripcion","icono"])
    return pd.DataFrame(filas)
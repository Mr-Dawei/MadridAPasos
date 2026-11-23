# -*- coding: utf-8 -*-
"""Carga y unificación de datos: POIs, fuentes, arbolado y clima (con caché de Streamlit)."""
import html
import json
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests
import streamlit as st

from config import (ARCHIVO_ARBOLADO_CSV, ARCHIVO_MALLA_ARBOLADO, BBOX_MADRID, CATEGORIAS, EXCLUIR_REFUGIO_PATRON,
                    HORARIOS_DEFECTO, MARGEN_CIERRE_MIN, RUTA_DATOS, RUTA_PROYECTO)
from geo_utils import latlon_a_utm, parsear_horario_texto, utm_a_latlon
from spatial import IndiceArbolado, construir_desde_csv

NS = {"atom": "http://www.w3.org/2005/Atom", "georss": "http://www.georss.org/georss",
      "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#"}

COLUMNAS_POI = ["categoria", "nombre", "lat", "lon", "x", "y", "descripcion", "url", "tiene_techo",
                "ap_min", "ci_min", "ap_fs", "ci_fs", "cerrado_mask", "margen_min", "horario_fuente"]


# ---------------- UTILIDADES ----------------
def resolver_ruta(nombre):
    """Busca un fichero ignorando mayúsculas (en Linux/Docker 'Museos.geo' ≠ 'museos.geo')."""
    for base in (RUTA_DATOS, RUTA_PROYECTO):
        if base.is_dir():
            for p in base.iterdir():
                if p.name.lower() == nombre.lower():
                    return p
    return None


def _limpiar_html(txt):
    txt = re.sub(r"<[^>]+>", " ", html.unescape(txt or ""))
    return re.sub(r"\s+", " ", txt).strip()


# ---------------- FEED ATOM / GEORSS ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_feed_atom(ruta):
    columnas = ["nombre", "lat", "lon", "descripcion", "url"]
    try:
        raiz = ET.parse(ruta).getroot()
    except Exception:
        return pd.DataFrame(columns=columnas)
    filas = []
    for e in raiz.findall("atom:entry", NS):
        lat, lon = e.findtext("geo:lat", None, NS), e.findtext("geo:long", None, NS)
        if lat is None:
            partes = (e.findtext("georss:point", "", NS) or "").split()
            if len(partes) != 2:
                continue
            lat, lon = partes
        try:
            lat, lon = float(lat), float(lon)
        except ValueError:
            continue
        enlace = next((l.get("href") for l in e.findall("atom:link", NS) if l.get("rel") == "alternate"), "") or ""
        filas.append({"nombre": (e.findtext("atom:title", "", NS) or "Lugar").strip(),
                      "lat": lat, "lon": lon,
                      "descripcion": _limpiar_html(e.findtext("atom:content", "", NS))[:600],
                      "url": enlace.replace("http://www.madrid.es", "https://www.madrid.es")})
    return pd.DataFrame(filas, columns=columnas)


# ---------------- FUENTES DE BEBER ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def cargar_fuentes():
    vacio = pd.DataFrame(columns=["nombre", "lat", "lon", "descripcion", "url"])
    ruta = resolver_ruta(CATEGORIAS["fuentes"]["fichero"])
    if ruta is None:
        return vacio
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return vacio
    if isinstance(datos, dict):
        datos = datos.get("result", {}).get("records") or datos.get("records") or [datos]
    df = pd.DataFrame(datos)
    if df.empty:
        return vacio
    df.columns = [str(c).upper() for c in df.columns]
    if "ESTADO" in df.columns:
        df = df[~df["ESTADO"].astype(str).str.contains("FUERA|CERRAD", case=False, na=False)]

    def num(col):
        if col not in df.columns:
            return pd.Series(np.nan, index=df.index)
        return pd.to_numeric(df[col].astype(str).str.replace(",", ".", regex=False), errors="coerce")

    lat, lon = num("LATITUD"), num("LONGITUD")
    falta = lat.isna() | lon.isna()
    x, y = num("COORD_GIS_X"), num("COORD_GIS_Y")
    usable = falta & x.notna() & y.notna()          # muchas filas solo traen UTM (ETRS89)
    if usable.any():
        la, lo = utm_a_latlon(x[usable].to_numpy(), y[usable].to_numpy())
        lat, lon = lat.copy(), lon.copy()
        lat[usable], lon[usable] = la, lo
    lon_min, lat_min, lon_max, lat_max = BBOX_MADRID
    ok = lat.between(lat_min, lat_max) & lon.between(lon_min, lon_max)

    def txt(col):
        return df[col].fillna("").astype(str).where(~df[col].astype(str).isin(["None", "nan"]), "") if col in df.columns \
            else pd.Series("", index=df.index)

    via = (txt("NOM_VIA") + " " + txt("NUM_VIA")).str.replace(r"\s+", " ", regex=True).str.strip()   # NOM_VIA ya incluye "Calle/Avenida…"
    out = pd.DataFrame({"nombre": "Fuente · " + via.where(via != "", "sin dirección"),
                        "lat": lat, "lon": lon, "descripcion": "", "url": ""})
    return out[ok].reset_index(drop=True)


# ---------------- REGISTRO UNIFICADO DE POIs ----------------
def _horarios(cat, descripciones):
    """Devuelve ap_lv, ci_lv, ap_fs, ci_fs, cerrado_mask, fuente (listas) según texto oficial o estimación."""
    n = len(descripciones)
    if cat not in HORARIOS_DEFECTO:                       # parques, monumentos, fuentes… acceso libre
        nan = [np.nan] * n
        return nan, nan, nan, nan, [0] * n, ["no_aplica"] * n
    h = HORARIOS_DEFECTO[cat]
    mascara = sum(1 << d for d in h["cerrado"])
    ap, ci, apf, cif, cm, fu = [], [], [], [], [], []
    for d in descripciones:
        a, c = parsear_horario_texto(d)
        if a is not None:                                  # horario explícito en la ficha oficial
            ap.append(a); ci.append(c); apf.append(a); cif.append(c); cm.append(0); fu.append("oficial_texto")
        else:
            ap.append(h["lv"][0]); ci.append(h["lv"][1])
            apf.append(h["fs"][0]); cif.append(h["fs"][1]); cm.append(mascara); fu.append("estimado")
    return ap, ci, apf, cif, cm, fu


def _registro_vacio():
    """DataFrame vacío con los tipos correctos (evita sorpresas al filtrar un registro sin datos)."""
    tipos = {c: "float64" for c in ("lat", "lon", "x", "y", "ap_min", "ci_min", "ap_fs", "ci_fs", "margen_min")}
    tipos.update({"tiene_techo": "bool", "cerrado_mask": "int64"})
    return pd.DataFrame({c: pd.Series(dtype=tipos.get(c, "object")) for c in COLUMNAS_POI})


@st.cache_data(ttl=3600, show_spinner=False)
def construir_registro_pois():
    """Todos los POIs en un único DataFrame (con coordenadas UTM y horarios). Se filtra por categoría fuera."""
    partes = []
    for cat, cfg in CATEGORIAS.items():
        if cat == "fuentes":
            df = cargar_fuentes()
        else:
            ruta = resolver_ruta(cfg["fichero"])
            df = cargar_feed_atom(str(ruta)) if ruta else pd.DataFrame(columns=["nombre", "lat", "lon", "descripcion", "url"])
        if df.empty:
            continue
        df = df.reset_index(drop=True).copy()
        df["categoria"] = cat
        df["tiene_techo"] = bool(cfg["techo"]) & ~df["nombre"].str.contains(EXCLUIR_REFUGIO_PATRON, regex=True)
        ap, ci, apf, cif, cm, fu = _horarios(cat, df["descripcion"].tolist())
        df["ap_min"], df["ci_min"], df["ap_fs"], df["ci_fs"] = ap, ci, apf, cif
        df["cerrado_mask"], df["horario_fuente"] = cm, fu
        df["margen_min"] = float(MARGEN_CIERRE_MIN.get(cat, 0))
        df["x"], df["y"] = latlon_a_utm(df["lat"].to_numpy(), df["lon"].to_numpy())
        partes.append(df[COLUMNAS_POI])
    if not partes:
        return _registro_vacio()
    reg = pd.concat(partes, ignore_index=True)
    reg["cerrado_mask"] = reg["cerrado_mask"].astype("int64")
    return reg


# ---------------- ARBOLADO ----------------
@st.cache_resource(show_spinner="Cargando arbolado…")
def cargar_indice_arbolado():
    """Índice de densidad de arbolado. Usa el .npz compacto; si no existe lo construye desde el CSV (una vez)."""
    npz = resolver_ruta(ARCHIVO_MALLA_ARBOLADO)
    if npz is not None:
        return IndiceArbolado.cargar(npz)
    csv = resolver_ruta(ARCHIVO_ARBOLADO_CSV)
    if csv is None:
        return None
    indice = construir_desde_csv(csv)
    try:
        indice.guardar(RUTA_DATOS / ARCHIVO_MALLA_ARBOLADO)
    except OSError:
        pass                                               # sistema de ficheros de solo lectura
    return indice


# ---------------- CLIMA ----------------
@st.cache_data(ttl=600, show_spinner=False)
def cargar_clima(lat=40.42, lon=-3.70):
    """Clima actual (Open-Meteo). Si falla NO se inventan datos: ok=False y la app lo indica."""
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=8, params={
            "latitude": lat, "longitude": lon, "current": "temperature_2m,precipitation,uv_index",
            "timezone": "Europe/Madrid"})
        r.raise_for_status()
        c = r.json()["current"]
        return {"ok": True, "temp": float(c["temperature_2m"]), "lluvia": float(c.get("precipitation") or 0.0),
                "uv": float(c.get("uv_index") or 0.0), "fuente": "Open-Meteo"}
    except Exception:
        return {"ok": False, "temp": None, "lluvia": None, "uv": None, "fuente": "no disponible"}


def estado_datos(registro, indice):
    """Diagnóstico para el panel de ajustes (útil para detectar ficheros que no se han cargado)."""
    filas = {cat: int((registro["categoria"] == cat).sum()) if not registro.empty else 0 for cat in CATEGORIAS}
    return {"pois_por_categoria": filas,
            "arbolado": "cargado (%.0f árboles equivalentes)" % indice.peso_total if indice is not None else "no encontrado"}

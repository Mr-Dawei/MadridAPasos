# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
Motor de puntuación multicriterio.

7 criterios:
  AHP (5, ajustables por el usuario):
    sombra, refugio, hidratacion, cultural, distancia
  Fijos (2, del perfil):
    desnivel, accesibilidad

Reglas duras:
  - Lluvia > 1 mm/h o refugio manual → la ruta DEBE tener techo
  - Movilidad reducida → descarta rutas con desnivel > 30 m

Agregación: producto ponderado con normalización [1, 100].
"""
import math
import numpy as np

from geo_utils import haversine_vec


CRITERIOS_AHP = ["sombra", "refugio", "hidratacion", "cultural", "distancia"]
CRITERIOS_FIJOS = ["desnivel", "accesibilidad"]
TODOS_LOS_CRITERIOS = CRITERIOS_AHP + CRITERIOS_FIJOS

PESOS_PERFIL = {
    "tranquilo": {
        "sombra": 9, "refugio": 7, "hidratacion": 8,
        "cultural": 4, "distancia": 5,
        "desnivel": 8, "accesibilidad": 7,
    },
    "activo": {
        "sombra": 5, "refugio": 4, "hidratacion": 6,
        "cultural": 9, "distancia": 7,
        "desnivel": 3, "accesibilidad": 5,
    },
    "movilidad_reducida": {
        "sombra": 7, "refugio": 9, "hidratacion": 8,
        "cultural": 5, "distancia": 4,
        "desnivel": 10, "accesibilidad": 10,
    },
}

RANGOS = {
    "sombra":        (0, 60),
    "refugio":       (0, 10),
    "hidratacion":   (0, 15),
    "cultural":      (0, 10),
    "distancia":     (0, 800),
    "desnivel":      (0, 40),
    "accesibilidad": (0, 1),
}

MAX_DESNIVEL_MR = 30
MAX_PENDIENTE_MR = 8


def _normalizar(valor, criterio):
    vmin, vmax = RANGOS[criterio]
    if vmax == vmin:
        return 50.0
    x = (valor - vmin) / (vmax - vmin)
    x = max(0.0, min(1.0, x))
    if criterio in ("distancia", "desnivel"):
        x = 1.0 - x
    return 1.0 + x * 99.0


def _dist(lat1, lon1, lat2, lon2):
    r = 6371000
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _muestrear_geometria(geometria, cada_m=50):
    coords = geometria.get("coordinates", []) if geometria else []
    if not coords:
        return []
    puntos = []
    acum = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        if acum >= cada_m or i == 0:
            puntos.append((lat1, lon1))
            acum = 0.0
        acum += _dist(lat1, lon1, lat2, lon2)
    return puntos


def _contar_en_buffer(puntos_ruta, df, radio_m=200):
    if df is None or df.empty or not puntos_ruta:
        return 0
    df_lats = df["lat"].values
    df_lons = df["lon"].values
    count = 0
    for lat, lon in puntos_ruta:
        d = haversine_vec(lat, lon, df_lats, df_lons)
        count += int((d <= radio_m).sum())
    return count


def evaluar_ruta(geometria, km, minutos, desnivel_m, pois_df, arbolado_df,
                 pesos, perfil, lluvia, refugio_manual):
    puntos = _muestrear_geometria(geometria)
    if not puntos:
        return {"score": 0, "criterios": {}, "pasa_filtros": False,
                "motivo_filtro": "Geometría vacía", "explicacion": ""}

    arb_ren = arbolado_df.rename(columns={"LATITUD": "lat", "LONGITUD": "lon"}) if arbolado_df is not None else None
    n_arboles = _contar_en_buffer(puntos, arb_ren, radio_m=200)

    poi_techo = pois_df[(pois_df["tiene_techo"]) & (pois_df["abierto_ahora"])] if not pois_df.empty else pois_df
    n_refugio = _contar_en_buffer(puntos, poi_techo, radio_m=200)

    poi_fuentes = pois_df[pois_df["categoria"] == "fuentes"] if not pois_df.empty else pois_df
    n_fuentes = _contar_en_buffer(puntos, poi_fuentes, radio_m=200)

    poi_cult = pois_df[pois_df["categoria"].isin(["monumentos", "museos"])] if not pois_df.empty else pois_df
    n_cultural = _contar_en_buffer(puntos, poi_cult, radio_m=200)

    # Reglas duras
    motivo_filtro = None
    if (lluvia > 1.0 or refugio_manual) and n_refugio == 0:
        motivo_filtro = ("Lluvia > 1 mm/h" if lluvia > 1.0 else "Refugio solicitado") \
                        + " y la ruta no pasa por refugio con techo abierto."

    if perfil == "movilidad_reducida" and desnivel_m > MAX_DESNIVEL_MR:
        motivo_filtro = f"Desnivel {desnivel_m:.0f} m > {MAX_DESNIVEL_MR} m (movilidad reducida)."

    if motivo_filtro:
        return {"score": 0, "criterios": {}, "pasa_filtros": False,
                "motivo_filtro": motivo_filtro, "explicacion": motivo_filtro}

    bruto = {
        "sombra": n_arboles, "refugio": n_refugio, "hidratacion": n_fuentes,
        "cultural": n_cultural, "distancia": max(0, km * 1000),
        "desnivel": desnivel_m,
        "accesibilidad": 1 if desnivel_m <= MAX_DESNIVEL_MR else 0,
    }

    criterios = {}
    log_producto = 0.0
    for c in TODOS_LOS_CRITERIOS:
        norm = _normalizar(bruto[c], c)
        peso = pesos.get(c, 5)
        contrib = peso * math.log(norm)
        log_producto += contrib
        criterios[c] = {"valor_bruto": round(bruto[c], 2),
                        "normalizado": round(norm, 2),
                        "peso": peso,
                        "contribucion": round(contrib, 2)}
    score = math.exp(log_producto)

    partes = []
    if n_refugio > 0:
        partes.append(f"{n_refugio} refugios con techo")
    if n_arboles > 0:
        partes.append(f"{n_arboles} árboles")
    if n_fuentes > 0:
        partes.append(f"{n_fuentes} fuentes")
    if n_cultural > 0:
        partes.append(f"{n_cultural} POIs culturales")
    if desnivel_m > 0:
        partes.append(f"desnivel {desnivel_m:.0f} m")
    explicacion = "Gana porque " + ", ".join(partes) if partes else "Ruta sin POIs destacados."

    return {"score": round(score, 2), "criterios": criterios,
            "pasa_filtros": True, "motivo_filtro": None,
            "explicacion": explicacion}


def pesos_por_perfil(perfil, ajustes_usuario=None):
    pesos = dict(PESOS_PERFIL[perfil])
    if ajustes_usuario:
        for k, v in ajustes_usuario.items():
            if k in pesos:
                pesos[k] = v
    return pesos
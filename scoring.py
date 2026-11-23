# -*- coding: utf-8 -*-
"""Motor de puntuación multicriterio (sin dependencias de Streamlit).

7 criterios, cada uno normalizado a [0, 1] ANTES de agregar:
  AHP (5, ajustables por el usuario): sombra, refugio, hidratacion, cultural, distancia
  Fijos (2, del perfil):              desnivel, accesibilidad
Agregación: media geométrica ponderada con pesos normalizados → puntuación 1-100 (un criterio muy
malo penaliza de verdad, pero ya no explota: antes los pesos sin normalizar daban puntuaciones ~1e50).

Reglas duras (la ruta NO pasa los filtros si no las cumple):
  · lluvia, o refugio pedido por el usuario  ⇒ al menos una PARADA con techo y abierta
  · movilidad reducida                       ⇒ ascenso total ≤ 30 m (si hay datos de altimetría)

Correcciones respecto a la versión anterior: cada POI se cuenta UNA vez (antes se sumaba por cada punto
de muestreo, inflando los conteos), la sombra se mide como densidad local de arbolado ponderada por altura
(antes: conteo con rango 0-60, saturado siempre) y la distancia se compara con el objetivo del usuario.
"""
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from config import CATEGORIAS
from geo_utils import latlon_a_utm
from spatial import IndiceArbolado

CRITERIOS_AHP = ["sombra", "refugio", "hidratacion", "cultural", "distancia"]
CRITERIOS_FIJOS = ["desnivel", "accesibilidad"]
TODOS_LOS_CRITERIOS = CRITERIOS_AHP + CRITERIOS_FIJOS

ETIQUETAS = {"sombra": "Sombra", "refugio": "Refugio con techo", "hidratacion": "Fuentes de agua",
             "cultural": "Lugares de interés", "distancia": "Ajuste a tu tiempo",
             "desnivel": "Desnivel suave", "accesibilidad": "Pendientes suaves"}

PESOS_PERFIL = {   # escala 0-10
    "tranquilo":          {"sombra": 9, "refugio": 7, "hidratacion": 8, "cultural": 4, "distancia": 5, "desnivel": 8,  "accesibilidad": 7},
    "activo":             {"sombra": 5, "refugio": 4, "hidratacion": 6, "cultural": 9, "distancia": 7, "desnivel": 3,  "accesibilidad": 5},
    "movilidad_reducida": {"sombra": 7, "refugio": 9, "hidratacion": 8, "cultural": 5, "distancia": 4, "desnivel": 10, "accesibilidad": 10},
}

PARAMS = {
    "radio_sombra": 25.0,        # m: ventana de arbolado alrededor de cada punto de la ruta
    "dens_ref": 12.0,            # árboles medianos equivalentes en la ventana que dan sombra "completa" (calibrado: Castellana ≈ 16, Retiro ≈ 43)
    "umbral_sombra": 6.0,        # a partir de aquí el tramo cuenta como "con sombra"
    "radio_fuente": 60.0, "radio_interes": 80.0, "radio_techo": 150.0,
    "fuentes_ref_km": 1.5,       # fuentes por km que dan hidratación completa
    "interes_ref_km": 2.5,       # "puntos de interés ponderados" por km que dan interés completo
    "desnivel_lim_m_km": {"tranquilo": 30.0, "activo": 45.0, "movilidad_reducida": 15.0},
    "pendiente_frac_max": 0.30,  # fracción del recorrido con pendiente > 6 % que anula la accesibilidad
    "mr_max_ascenso_m": 30.0,
}


# ---------------- PESOS ----------------
def pesos_por_perfil(perfil, ajustes_usuario=None):
    pesos = dict(PESOS_PERFIL[perfil])
    for k, v in (ajustes_usuario or {}).items():
        if k in pesos:
            pesos[k] = v
    return pesos


def ajustar_pesos_clima(pesos, flags):
    """Calor/UV/frío: el refugio (y la sombra o las fuentes) pesan más en el scoring. Lluvia: refugio ×2 (+ regla dura)."""
    p = dict(pesos)
    if flags.get("calor") or flags.get("uv"):
        for c in ("sombra", "hidratacion", "refugio"):
            p[c] = p.get(c, 5) * 1.5
    if flags.get("frio"):
        p["refugio"] = p.get("refugio", 5) * 1.5
        p["sombra"] = p.get("sombra", 5) * 0.6
    if flags.get("lluvia"):
        p["refugio"] = p.get("refugio", 5) * 2.0
        p["sombra"] = p.get("sombra", 5) * 0.5
    return p


# ---------------- CONTEXTO (arrays preparados una vez por planificación) ----------------
@dataclass
class Contexto:
    indice: Optional[IndiceArbolado]
    fuentes_xy: np.ndarray        # fuentes operativas
    interes_xy: np.ndarray        # POIs de las categorías que quiere ver el usuario
    interes_w: np.ndarray
    techo_xy: np.ndarray          # refugios con techo abiertos ahora


def _xy(df):
    return df[["x", "y"]].to_numpy(dtype=float) if len(df) else np.zeros((0, 2))


def construir_contexto(pois_df, indice, categorias_interes):
    """pois_df debe traer 'abierto_ahora' (ver geo_utils.calcular_abierto_ahora)."""
    interes = pois_df[pois_df["categoria"].isin(categorias_interes) & (pois_df["categoria"] != "fuentes")]
    peso = interes["categoria"].map({k: v["interes"] for k, v in CATEGORIAS.items()}).to_numpy(dtype=float)
    return Contexto(indice, _xy(pois_df[pois_df["categoria"] == "fuentes"]), _xy(interes), peso,
                    _xy(pois_df[pois_df["tiene_techo"] & pois_df["abierto_ahora"]]))


# ---------------- GEOMETRÍA ----------------
def muestrear_ruta(coords, paso_m=20.0):
    """Puntos equiespaciados (UTM) a lo largo de la ruta + distancia acumulada y longitud total (m)."""
    a = np.asarray([[c[0], c[1]] for c in coords], dtype=float)
    x, y = latlon_a_utm(a[:, 1], a[:, 0])
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    largo = float(cum[-1])
    if largo < 1.0:
        return x[:1], y[:1], np.array([0.0]), largo
    s = np.append(np.arange(0.0, largo, paso_m), largo)
    return np.interp(s, cum, x), np.interp(s, cum, y), s, largo


def mascara_cerca(poi_xy, path_xy, radio):
    """Qué POIs están a ≤ radio de algún punto de la ruta: cada POI cuenta UNA vez."""
    out = np.zeros(len(poi_xy), dtype=bool)
    if len(poi_xy) == 0 or len(path_xy) == 0:
        return out
    lo, hi = path_xy.min(axis=0) - radio, path_xy.max(axis=0) + radio
    cand = np.flatnonzero((poi_xy[:, 0] >= lo[0]) & (poi_xy[:, 0] <= hi[0]) & (poi_xy[:, 1] >= lo[1]) & (poi_xy[:, 1] <= hi[1]))
    for i in range(0, len(cand), 400):
        idx = cand[i:i + 400]
        d2 = ((poi_xy[idx, None, :] - path_xy[None, :, :]) ** 2).sum(axis=-1).min(axis=1)
        out[idx] = d2 <= radio ** 2
    return out


# ---------------- EVALUACIÓN ----------------
def evaluar_ruta(coords, ctx, paradas, pesos, perfil, objetivo_km=None, ascenso_m=None, frac_pendiente=None,
                 refugio_obligatorio=False, km=None):
    """Puntúa una ruta. `paradas`: dicts con 'nombre', 'categoria' y 'refugio_ok' (techo y abierta).
    `km` permite pasar una estimación cuando `coords` es una línea recta (prefiltrado de candidatas)."""
    P = PARAMS
    xs, ys, _, largo = muestrear_ruta(coords)
    km = largo / 1000 if km is None else km
    kmr = max(km, 0.5)                                       # evita divisiones raras en rutas muy cortas
    path_xy = np.column_stack([xs, ys])

    if ctx.indice is not None:
        dens = ctx.indice.densidad_xy(xs, ys, P["radio_sombra"])
        sombra = float(np.clip(dens / P["dens_ref"], 0, 1).mean())
        pct_sombra = float((dens >= P["umbral_sombra"]).mean())
    else:
        sombra, pct_sombra = 0.5, None                       # sin datos de arbolado: valor neutro

    n_fuentes = int(mascara_cerca(ctx.fuentes_xy, path_xy, P["radio_fuente"]).sum())
    hidratacion = min(1.0, (n_fuentes / kmr) / P["fuentes_ref_km"])

    m_int = mascara_cerca(ctx.interes_xy, path_xy, P["radio_interes"])
    suma = float(ctx.interes_w[m_int].sum()) + sum(CATEGORIAS.get(p["categoria"], {}).get("interes", 0.3) for p in paradas)
    n_interes = int(m_int.sum())
    cultural = min(1.0, suma / (P["interes_ref_km"] * kmr))

    n_techo_parada = sum(1 for p in paradas if p.get("refugio_ok"))
    n_techo_cerca = int(mascara_cerca(ctx.techo_xy, path_xy, P["radio_techo"]).sum())
    refugio = min(1.0, 0.6 * (1.0 if n_techo_parada else 0.0) + 0.4 * min(1.0, n_techo_cerca / 2))

    distancia = max(0.0, 1.0 - abs(km - objetivo_km) / objetivo_km) if objetivo_km else 1.0
    desnivel = 0.6 if ascenso_m is None else max(0.0, 1.0 - (ascenso_m / kmr) / P["desnivel_lim_m_km"][perfil])
    accesibilidad = 0.6 if frac_pendiente is None else max(0.0, 1.0 - frac_pendiente / P["pendiente_frac_max"])

    valores = {"sombra": sombra, "refugio": refugio, "hidratacion": hidratacion, "cultural": cultural,
               "distancia": distancia, "desnivel": desnivel, "accesibilidad": accesibilidad}

    total_pesos = sum(max(0.0, float(pesos.get(c, 0))) for c in TODOS_LOS_CRITERIOS) or 1.0
    criterios, log_score = {}, 0.0
    for c in TODOS_LOS_CRITERIOS:
        w = max(0.0, float(pesos.get(c, 0))) / total_pesos
        norm = 1.0 + 99.0 * valores[c]
        log_score += w * math.log(norm)
        criterios[c] = {"valor": round(valores[c], 3), "normalizado": round(norm, 1), "peso": round(w, 3),
                        "contribucion": round(w * math.log(norm), 3)}

    motivo = None
    if refugio_obligatorio and n_techo_parada == 0:
        motivo = "Hace falta un refugio con techo abierto y la ruta no pasa por ninguno."
    if perfil == "movilidad_reducida" and ascenso_m is not None and ascenso_m > P["mr_max_ascenso_m"]:
        motivo = f"Desnivel de {ascenso_m:.0f} m (máximo {P['mr_max_ascenso_m']:.0f} m para movilidad reducida)."

    metricas = {"km": km, "pct_sombra": pct_sombra, "n_fuentes": n_fuentes, "n_interes": n_interes,
                "n_techo_parada": n_techo_parada, "n_techo_cerca": n_techo_cerca,
                "ascenso_m": ascenso_m, "frac_pendiente": frac_pendiente}
    return {"score": round(math.exp(log_score), 1), "pasa_filtros": motivo is None, "motivo_filtro": motivo,
            "criterios": criterios, "metricas": metricas, "explicacion": _explicar(metricas, paradas)}


def _explicar(m, paradas):
    partes = []
    if m["pct_sombra"] is not None:
        partes.append(f"{m['pct_sombra'] * 100:.0f} % del recorrido con sombra")
    if m["n_fuentes"]:
        partes.append(f"{m['n_fuentes']} fuente{'s' if m['n_fuentes'] != 1 else ''} de agua")
    techo = [p["nombre"] for p in paradas if p.get("refugio_ok")]
    if techo:
        partes.append(f"refugio con techo en {techo[0]}")
    if m["ascenso_m"] is not None:
        partes.append(f"{m['ascenso_m']:.0f} m de desnivel")
    return " · ".join(partes) or "Ruta equilibrada"

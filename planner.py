# -*- coding: utf-8 -*-
"""Planificador de paseos: elige 1-3 paradas de interés, traza la ruta real y se queda con la mejor.

Las llamadas a servicios de rutas son lo más lento, así que se prefiltra con geometría barata (numpy):
  1. Candidatos: POIs abiertos y compatibles (anillo alrededor del origen si es circular, elipse si es A→B).
  2. Preselección por sombra local + interés, sin repetir zonas (≥ 250 m entre paradas candidatas).
  3. Combinaciones de paradas → puntuadas con la línea recta (rápido) → se quedan las K mejores.
  4. Solo esas K se trazan con el servicio de rutas (en paralelo) y se re-puntúan con la ruta real.
  5. Lluvia o refugio pedido ⇒ solo combinaciones con al menos UNA parada con techo y abierta.
"""
import math
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations

import numpy as np

from config import (CATEGORIAS, CATEGORIAS_DEFECTO, CENTRO_LAT, CENTRO_LON, CENTRO_RADIO_M, FACTOR_CALLE,
                    MIN_POR_PARADA, PERFILES, REFUGIO_CATEGORIAS)
from geo_utils import haversine_vec, latlon_a_utm, utm_a_latlon
from routing import calcular_ruta
from scoring import PARAMS, ajustar_pesos_clima, construir_contexto, evaluar_ruta, pesos_por_perfil

MAX_POOL = 12
SEPARACION_M = 250.0


def n_paradas_por_duracion(minutos):
    return 1 if minutos <= 30 else 2 if minutos <= 60 else 3


def _dict_parada(fila):
    return {"nombre": fila["nombre"], "categoria": fila["categoria"], "lat": float(fila["lat"]), "lon": float(fila["lon"]),
            "x": float(fila["x"]), "y": float(fila["y"]), "url": fila.get("url", ""), "tiene_techo": bool(fila["tiene_techo"]),
            "abierto_ahora": bool(fila["abierto_ahora"]), "cierra_min": None if np.isnan(fila["cierra_min"]) else float(fila["cierra_min"]),
            "horario_fuente": fila["horario_fuente"], "refugio_ok": bool(fila["refugio_ok"])}


def _seleccionar_pool(df, indice, must_roof):
    """Top-MAX_POOL por sombra local + interés, con separación mínima entre candidatas."""
    xy = df[["x", "y"]].to_numpy(dtype=float)
    interes = df["categoria"].map({k: v["interes"] for k, v in CATEGORIAS.items()}).to_numpy(dtype=float)
    sombra = (np.clip(indice.densidad_xy(xy[:, 0], xy[:, 1], PARAMS["radio_sombra"]) / PARAMS["dens_ref"], 0, 1)
              if indice is not None else np.full(len(df), 0.5))
    techo = df["refugio_ok"].to_numpy(dtype=bool)
    pre = 0.45 * interes + 0.40 * sombra + (0.20 if must_roof else 0.05) * techo
    elegidos = []
    for i in np.argsort(-pre):
        if len(elegidos) >= MAX_POOL:
            break
        if all(math.hypot(*(xy[i] - xy[j])) >= SEPARACION_M for j in elegidos):
            elegidos.append(int(i))
    if must_roof and not techo[elegidos].any():                 # garantiza que haya al menos un refugio entre las candidatas
        mejor = next((int(i) for i in np.argsort(-pre) if techo[i]), None)
        if mejor is not None:
            elegidos[-1] = mejor
    return df.iloc[elegidos].reset_index(drop=True)


def _ordenar(origen_xy, destino_xy, stops_xy):
    """Circular: por ángulo alrededor del origen (evita cruces). A→B: por avance hacia el destino."""
    if destino_xy is None:
        return np.argsort([math.atan2(y - origen_xy[1], x - origen_xy[0]) for x, y in stops_xy])
    v = destino_xy - origen_xy
    n2 = max(float(v @ v), 1.0)
    return np.argsort([float((np.array(s) - origen_xy) @ v) / n2 for s in stops_xy])


def _punto_via(origen_xy, parada_xy, indice):
    """Con una sola parada, el regreso iría por la misma calle: se añade un punto lateral (el lado con más árboles)."""
    v = np.asarray(parada_xy) - origen_xy
    d = float(np.hypot(*v))
    if d < 1:
        return None
    perp = np.array([-v[1], v[0]]) / d
    cands = [origen_xy + 0.5 * v + s * 0.35 * d * perp for s in (1.0, -1.0)]
    k = int(np.argmax([indice.densidad_xy(c[0], c[1], 40.0)[0] for c in cands])) if indice is not None else 0
    return cands[k]


def _a_coords(puntos_xy):
    xs, ys = zip(*puntos_xy)
    la, lo = utm_a_latlon(np.array(xs), np.array(ys))
    return [[float(b), float(a)] for a, b in zip(la, lo)]


def _opcion(etiqueta, paradas, ruta, ctx, pesos, perfil, objetivo_km, must, ritmo):
    ev = evaluar_ruta(ruta.coords, ctx, paradas, pesos, perfil, objetivo_km, ruta.ascenso_m, ruta.frac_pendiente, must)
    minutos = ruta.km * 1000 / ritmo + len(paradas) * MIN_POR_PARADA
    return {"etiqueta": etiqueta, "paradas": paradas, "ruta": ruta, "evaluacion": ev, "km": ruta.km, "minutos": int(round(minutos))}


def planificar(origen, destino, duracion_min, perfil, pois_df, indice, pesos, flags, refugio_manual=False,
               categorias=None, evitar_centro=False, router=calcular_ruta, k_reales=4):
    """origen/destino: (lat, lon); destino=None → paseo circular. pois_df debe traer 'abierto_ahora'/'cierra_min'.
    Devuelve {"opciones": [...mejor primero], "base": ruta directa (A→B) o None, "avisos": [...], "meta": {...}}."""
    avisos, circular = [], destino is None
    ritmo, movilidad = PERFILES[perfil]["ritmo_m_min"], perfil == "movilidad_reducida"
    must = bool(flags.get("lluvia")) or bool(refugio_manual)
    pesos = ajustar_pesos_clima(pesos, flags)
    n = n_paradas_por_duracion(duracion_min)
    o_xy = np.array(latlon_a_utm(*origen), dtype=float)
    d_xy = None if circular else np.array(latlon_a_utm(*destino), dtype=float)

    # ---- objetivo de distancia y ruta directa (A→B) ----
    objetivo_m = max(10, duracion_min - n * MIN_POR_PARADA) * ritmo
    base = None
    ctx_todo = construir_contexto(pois_df, indice, categorias or CATEGORIAS_DEFECTO)
    if not circular:
        directa = router([origen, destino], movilidad)
        avisos += directa.avisos
        directa_m = directa.km * 1000
        if objetivo_m < directa_m * 1.1:
            avisos.append("El tiempo elegido no da ni para ir directo: añado una sola parada sin apenas desvío.")
            objetivo_m = directa_m * 1.15
        n = max(1, min(n, 1 + int((objetivo_m - directa_m) // 700)))
        base = _opcion("Ruta directa", [], directa, ctx_todo, pesos, perfil, directa.km, False, ritmo)
        base["waypoints"] = [origen, destino]
    objetivo_km, ls = objetivo_m / 1000, objetivo_m / FACTOR_CALLE

    # ---- candidatos ----
    cats = set(categorias or CATEGORIAS_DEFECTO)
    if must:
        cats |= set(REFUGIO_CATEGORIAS)                           # con lluvia siempre hay que poder elegir un refugio
    if flags.get("calor") or flags.get("uv"):
        cats.add("fuentes")                                        # con calor, beber agua es una parada de interés
    df = pois_df[pois_df["categoria"].isin(cats) & pois_df["abierto_ahora"]].copy()
    if evitar_centro and len(df):
        df = df[haversine_vec(CENTRO_LAT, CENTRO_LON, df["lat"].to_numpy(), df["lon"].to_numpy()) > CENTRO_RADIO_M]
    df["refugio_ok"] = df["tiene_techo"] & df["abierto_ahora"]
    d1 = np.hypot(df["x"].to_numpy() - o_xy[0], df["y"].to_numpy() - o_xy[1])
    d2 = None if circular else np.hypot(df["x"].to_numpy() - d_xy[0], df["y"].to_numpy() - d_xy[1])
    recta = 0.0 if circular else float(np.hypot(*(d_xy - o_xy)))

    def zona(escala):
        l = ls * escala
        return df[(d1 > 0.10 * l) & (d1 < 0.55 * l)] if circular else df[(d1 + d2) <= max(l, recta * 1.15)]

    def sin_resultado(mensaje):
        avisos.append(mensaje)
        return {"opciones": [], "base": base, "avisos": avisos, "meta": {"n_paradas": 0, "refugio_obligatorio": must,
                "circular": circular, "objetivo_km": objetivo_km}}

    cand, escala = zona(1.0), 1.0
    if must and not cand["refugio_ok"].any():              # con lluvia lo prioritario es resguardarse: se amplía la zona
        for escala in (1.3, 1.6):
            cand = zona(escala)
            if cand["refugio_ok"].any():
                break
    if must and not cand["refugio_ok"].any():
        if not df["refugio_ok"].any():
            return sin_resultado("Ahora mismo no hay ningún museo, biblioteca ni centro cultural abierto en Madrid (los horarios son "
                                 "orientativos). Prueba más tarde o quita la opción de techo.")
        return sin_resultado(f"El sitio con techo abierto más cercano está a unos {d1[df['refugio_ok'].to_numpy()].min():.0f} m, "
                             "demasiado lejos para este tiempo: prueba con más duración.")
    if escala > 1.0:                                       # el paseo se alarga para llegar a un refugio abierto
        objetivo_m, ls = objetivo_m * escala, ls * escala
        objetivo_km = objetivo_m / 1000
        avisos.append(f"El refugio abierto más cercano está algo lejos: el paseo se alarga hasta unos "
                      f"{int(round(objetivo_m / ritmo + n * MIN_POR_PARADA))} min.")
    if cand.empty:
        return sin_resultado("No encuentro sitios de interés abiertos con esas condiciones; prueba con más tiempo o más categorías.")
    pool = _seleccionar_pool(cand, indice, must)
    k = min(n, len(pool))

    # ---- combinaciones → prefiltrado con línea recta (banda de tiempo estricta; si no hay, se relaja) ----
    ctx = ctx_todo

    def evaluar_combinaciones(minimo, maximo):
        salida = []
        for comb in combinations(range(len(pool)), k):
            filas = [pool.iloc[i] for i in comb]
            if must and not any(f["refugio_ok"] for f in filas):
                continue
            orden = _ordenar(o_xy, d_xy, [(f["x"], f["y"]) for f in filas])
            filas = [filas[i] for i in orden]
            pts = [o_xy] + [np.array([f["x"], f["y"]]) for f in filas]
            if circular and k == 1:
                via = _punto_via(o_xy, pts[1], indice)
                if via is not None:
                    pts.append(via)
            pts.append(o_xy if circular else d_xy)
            largo = sum(float(np.hypot(*(b - a))) for a, b in zip(pts, pts[1:]))
            if largo > ls * maximo or (circular and largo < ls * minimo):
                continue
            paradas_min = [{"nombre": f["nombre"], "categoria": f["categoria"], "refugio_ok": bool(f["refugio_ok"])} for f in filas]
            ev = evaluar_ruta(_a_coords(pts), ctx, paradas_min, pesos, perfil, objetivo_km, refugio_obligatorio=must,
                              km=largo * FACTOR_CALLE / 1000)
            salida.append((ev["score"], filas, pts))
        return salida

    candidatas = evaluar_combinaciones(0.75, 1.10) or evaluar_combinaciones(0.55, 1.30)
    if not candidatas:
        avisos.append("Ninguna combinación de paradas encaja con el tiempo pedido: prueba con otra duración.")
        return {"opciones": [], "base": base, "avisos": avisos, "meta": {"n_paradas": k, "refugio_obligatorio": must,
                "circular": circular, "objetivo_km": objetivo_km}}
    candidatas.sort(key=lambda c: -c[0])
    top, maximo_comun = [], max(0, k - 2)          # alternativas con paradas distintas (k=2: ninguna en común; k=3: como mucho 1)
    for c in candidatas:
        nombres = {f["nombre"] for f in c[1]}
        if all(len(nombres & {f["nombre"] for f in t[1]}) <= maximo_comun for t in top):
            top.append(c)
        if len(top) == k_reales:
            break
    usadas = {id(t) for t in top}                   # (comparar por identidad: las tuplas contienen Series de pandas)
    top += [c for c in candidatas if id(c) not in usadas][:k_reales - len(top)]

    # ---- ruta real de las K mejores (en paralelo) y puntuación definitiva ----
    waypoints = []
    for _, filas, pts in top:
        w = [origen] + [(f["lat"], f["lon"]) for f in filas]
        if circular and k == 1 and len(pts) == 4:
            la, lo = utm_a_latlon(*pts[2])
            w.append((float(la), float(lo)))
        w.append(destino or origen)
        waypoints.append(w)
    with ThreadPoolExecutor(max_workers=min(4, len(waypoints))) as ex:
        rutas = list(ex.map(lambda w: router(w, movilidad), waypoints))
    opciones = []
    for (_, filas, _), ruta, w in zip(top, rutas, waypoints):
        avisos += [a for a in ruta.avisos if a not in avisos]
        op = _opcion("", [_dict_parada(f) for f in filas], ruta, ctx, pesos, perfil, objetivo_km, must, ritmo)
        op["waypoints"] = w                                        # permite repetir el paseo exactamente igual
        opciones.append(op)
    # primero las que pasan los filtros, luego las que respetan el tiempo pedido (±30 %), luego mejor puntuación
    opciones.sort(key=lambda o: (not o["evaluacion"]["pasa_filtros"], abs(o["km"] - objetivo_km) / objetivo_km > 0.30,
                                 -o["evaluacion"]["score"]))
    for i, o in enumerate(opciones):
        o["etiqueta"] = "Recomendada" if i == 0 else f"Alternativa {i + 1}"
    return {"opciones": opciones, "base": base, "avisos": avisos, "meta": {"n_paradas": k, "refugio_obligatorio": must,
            "circular": circular, "objetivo_km": objetivo_km, "pesos": pesos}}


def reconstruir_paseo(item, pois_df, indice, flags, router=calcular_ruta):
    """Vuelve a trazar un paseo guardado (favorito/historial) con el clima y los horarios de AHORA."""
    perfil = item["perfil"]
    ritmo = PERFILES[perfil]["ritmo_m_min"]
    df = pois_df.copy()
    df["refugio_ok"] = df["tiene_techo"] & df["abierto_ahora"]
    paradas = []
    for p in item["paradas"]:
        fila = df[(df["nombre"] == p["nombre"]) & (df["categoria"] == p["categoria"])]
        if len(fila):
            paradas.append(_dict_parada(fila.iloc[0]))
        else:                                                       # ya no está en los datos: se conserva con lo guardado
            paradas.append({"nombre": p["nombre"], "categoria": p["categoria"], "lat": p["lat"], "lon": p["lon"], "x": 0.0, "y": 0.0,
                            "url": "", "tiene_techo": False, "abierto_ahora": True, "cierra_min": None,
                            "horario_fuente": "no_aplica", "refugio_ok": False})
    destino = item.get("destino")
    waypoints = [tuple(w) for w in item.get("waypoints") or
                 [item["origen"]] + [(p["lat"], p["lon"]) for p in paradas] + [destino or item["origen"]]]
    ruta = router(waypoints, perfil == "movilidad_reducida")
    pesos = ajustar_pesos_clima(pesos_por_perfil(perfil), flags)
    ctx = construir_contexto(pois_df, indice, CATEGORIAS_DEFECTO)
    op = _opcion("Repetido", paradas, ruta, ctx, pesos, perfil, item.get("km"), False, ritmo)
    op["waypoints"] = waypoints
    return {"opciones": [op], "base": None, "avisos": list(ruta.avisos),
            "meta": {"n_paradas": len(paradas), "refugio_obligatorio": False, "circular": destino is None, "objetivo_km": item.get("km")}}

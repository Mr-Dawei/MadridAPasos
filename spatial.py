# -*- coding: utf-8 -*-
"""Índice espacial del arbolado: malla de densidad ponderada + imagen integral.

Cada árbol aporta un peso según su altura (≈ copa). La densidad dentro de un cuadrado de radio r
alrededor de cualquier punto se obtiene con 4 lecturas (O(1)), en vez de calcular la distancia a los
~800.000 árboles por cada punto de la ruta. Solo numpy; se guarda en un .npz de pocos MB.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from geo_utils import latlon_a_utm, utm_a_latlon

CELDA_M = 10.0          # tamaño de celda (m)
CUANT = 20.0            # cuantización del peso (uint16)
UTM_MADRID = (420000.0, 470000.0, 4450000.0, 4500000.0)     # xmin, xmax, ymin, ymax
ALTURA_MIN, ALTURA_MAX, ALTURA_REF = 0.5, 12.0, 6.0         # un árbol de 6 m pesa 1


class IndiceArbolado:
    def __init__(self, x0, y0, celda, nx, ny, idx, val):
        self.x0, self.y0, self.celda = float(x0), float(y0), float(celda)
        self.nx, self.ny = int(nx), int(ny)
        self.idx = np.asarray(idx, dtype=np.int64)
        self.val = np.asarray(val, dtype=np.uint16)
        q = np.zeros(self.nx * self.ny, dtype=np.uint16)
        q[self.idx] = self.val
        self._q = q.reshape(self.ny, self.nx)
        ii = np.zeros((self.ny + 1, self.nx + 1), dtype=np.int32)
        np.cumsum(np.cumsum(self._q, axis=0, dtype=np.int32), axis=1, out=ii[1:, 1:])
        self._ii = ii

    # ---------- construcción / persistencia ----------
    @classmethod
    def desde_puntos(cls, x, y, peso, celda=CELDA_M):
        x, y, peso = np.asarray(x, float), np.asarray(y, float), np.asarray(peso, float)
        x0 = np.floor(x.min() / celda) * celda - celda
        y0 = np.floor(y.min() / celda) * celda - celda
        nx, ny = int((x.max() - x0) // celda) + 2, int((y.max() - y0) // celda) + 2
        ix = ((x - x0) // celda).astype(np.int64)
        iy = ((y - y0) // celda).astype(np.int64)
        val = np.bincount(iy * nx + ix, weights=peso, minlength=nx * ny)
        q = np.minimum(np.rint(val * CUANT), 65535).astype(np.uint16)
        idx = np.flatnonzero(q)
        return cls(x0, y0, celda, nx, ny, idx, q[idx])

    def guardar(self, ruta):
        np.savez_compressed(ruta, x0=self.x0, y0=self.y0, celda=self.celda, nx=self.nx, ny=self.ny,
                            idx=self.idx.astype(np.int32), val=self.val)

    @classmethod
    def cargar(cls, ruta):
        d = np.load(ruta)
        return cls(d["x0"], d["y0"], d["celda"], d["nx"], d["ny"], d["idx"], d["val"])

    # ---------- consultas ----------
    @property
    def peso_total(self):
        return float(self.val.sum()) / CUANT

    def densidad_xy(self, x, y, radio_m=25.0):
        """Peso de arbolado (≈ nº de árboles medianos) en el cuadrado de lado 2·radio centrado en (x, y)."""
        x, y = np.atleast_1d(np.asarray(x, float)), np.atleast_1d(np.asarray(y, float))
        r = max(1, int(round(radio_m / self.celda)))
        cx = np.floor((x - self.x0) / self.celda).astype(np.int64)
        cy = np.floor((y - self.y0) / self.celda).astype(np.int64)
        x1, x2 = np.clip(cx - r, 0, self.nx), np.clip(cx + r + 1, 0, self.nx)
        y1, y2 = np.clip(cy - r, 0, self.ny), np.clip(cy + r + 1, 0, self.ny)
        ii = self._ii
        return (ii[y2, x2] - ii[y1, x2] - ii[y2, x1] + ii[y1, x1]).astype(np.float64) / CUANT

    def densidad(self, lat, lon, radio_m=25.0):
        x, y = latlon_a_utm(lat, lon)
        return self.densidad_xy(x, y, radio_m)

    def celdas_en_radio(self, lat, lon, radio_m=1500.0, agregar=3):
        """(lat, lon, peso) de celdas con arbolado alrededor de un punto: para pintar un mapa de calor ligero."""
        cx, cy = latlon_a_utm(lat, lon)
        r = int(radio_m // self.celda)
        icx, icy = int((cx - self.x0) // self.celda), int((cy - self.y0) // self.celda)
        ix0, ix1 = max(0, icx - r), min(self.nx, icx + r + 1)
        iy0, iy1 = max(0, icy - r), min(self.ny, icy + r + 1)
        bloque = self._q[iy0:iy1, ix0:ix1].astype(np.float32)
        h, w = (bloque.shape[0] // agregar) * agregar, (bloque.shape[1] // agregar) * agregar
        if h == 0 or w == 0:
            return np.array([]), np.array([]), np.array([])
        b = bloque[:h, :w].reshape(h // agregar, agregar, w // agregar, agregar).sum(axis=(1, 3))
        ys, xs = np.nonzero(b)
        xx = self.x0 + (ix0 + xs * agregar + agregar / 2) * self.celda
        yy = self.y0 + (iy0 + ys * agregar + agregar / 2) * self.celda
        la, lo = utm_a_latlon(xx, yy)
        return la, lo, b[ys, xs] / CUANT


def construir_desde_csv(ruta_csv):
    """Lee el CSV de arbolado del Ayuntamiento (X, Y en UTM 30N; ALTURA_TOTAL en m) y construye el índice."""
    ruta_csv = Path(ruta_csv)
    with open(ruta_csv, encoding="utf-8-sig", errors="replace") as f:
        cabecera = f.readline()
    sep = ";" if cabecera.count(";") >= cabecera.count(",") else ","
    cols = {c.strip().upper(): c for c in cabecera.strip().split(sep)}
    cx = cols.get("X") or cols.get("COORD_X") or cols.get("LONGITUD")
    cy = cols.get("Y") or cols.get("COORD_Y") or cols.get("LATITUD")
    ch = cols.get("ALTURA_TOTAL") or cols.get("ALTURA")
    if not (cx and cy):
        raise ValueError(f"No encuentro columnas de coordenadas en {ruta_csv.name}: {list(cols)[:12]}")
    usar = [c for c in (cx, cy, ch) if c]
    df = pd.read_csv(ruta_csv, sep=sep, encoding="utf-8-sig", dtype=str, usecols=usar, on_bad_lines="skip")

    def num(s):
        return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce").to_numpy(dtype=float)

    x, y = num(df[cx]), num(df[cy])
    if np.nanmax(np.abs(x)) <= 180:                       # vienen como lon/lat → a UTM
        x, y = latlon_a_utm(y, x)
    alt = num(df[ch]) if ch else np.full(len(df), ALTURA_REF)
    xmin, xmax, ymin, ymax = UTM_MADRID
    ok = np.isfinite(x) & np.isfinite(y) & (x > xmin) & (x < xmax) & (y > ymin) & (y < ymax)
    alt = np.where(np.isfinite(alt), alt, 3.0)            # sin altura → árbol joven
    peso = np.clip(alt, ALTURA_MIN, ALTURA_MAX)[ok] / ALTURA_REF
    return IndiceArbolado.desde_puntos(x[ok], y[ok], peso)

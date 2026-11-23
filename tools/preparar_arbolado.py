# -*- coding: utf-8 -*-
"""Convierte el CSV de arbolado del Ayuntamiento (≈ 75 MB, 800.000 árboles) en un índice compacto.

    python tools/preparar_arbolado.py [ruta/al/arbolado.csv]        →  data/arbolado_malla.npz (≈ 1 MB)

La app carga el .npz en ~0,1 s (el CSV tardaba más de 10 s y gastaba cientos de MB de memoria). Se sube el .npz al
repositorio y el CSV puede quedarse fuera (ver .gitignore). Vuelve a ejecutarlo si actualizas el CSV.
"""
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from config import ARCHIVO_MALLA_ARBOLADO, RUTA_DATOS      # noqa: E402
from spatial import construir_desde_csv                      # noqa: E402


def main():
    csv = Path(sys.argv[1]) if len(sys.argv) > 1 else RUTA_DATOS / "arbolado.csv"
    if not csv.is_file():
        sys.exit(f"No encuentro {csv}. Uso: python tools/preparar_arbolado.py ruta/al/arbolado.csv")
    t = time.time()
    indice = construir_desde_csv(csv)
    salida = RUTA_DATOS / ARCHIVO_MALLA_ARBOLADO
    salida.parent.mkdir(exist_ok=True)
    indice.guardar(salida)
    print(f"OK: {salida} ({salida.stat().st_size / 1e6:.2f} MB, {len(indice.idx):,} celdas, "
          f"{indice.peso_total:,.0f} árboles equivalentes) en {time.time() - t:.1f} s")


if __name__ == "__main__":
    main()

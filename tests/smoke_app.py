# -*- coding: utf-8 -*-
"""Prueba de humo: ejecuta app.py entera con un Streamlit simulado (sin red) y los datos reales de data/.
Comprueba los fallos que tumbaban la versión anterior: set_page_config duplicado, expanders anidados, escritura en
claves de widgets ya creados, regla de lluvia, modo paseo, repetir favoritos, emergencias sin red y contraseña."""
import os
import re
import runpy
import sys
from unittest import mock

import pandas as pd
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [RAIZ, os.path.join(RAIZ, "tests")]
os.chdir(RAIZ)
import fake_streamlit as fs  # noqa: E402

clicks = {"k": lambda key: False}
st = fs.instalar(lambda key: clicks["k"](key))
S = st.session_state
MARTES_11 = pd.Timestamp("2026-11-24 11:00").to_pydatetime()


def correr(titulo, esperado="ok"):
    st.salidas.clear(); st.html_comp.clear(); st.nueva_ejecucion()
    try:
        runpy.run_path("app.py", run_name="__main__"); estado = "ok"
    except fs.Rerun:
        estado = "rerun"
    except fs.Stop:
        estado = "stop"
    fs.SS.bloqueadas.clear()                      # entre ejecuciones el navegador sí puede cambiar los widgets
    md = " ".join(str(s[1]) for s in st.salidas if s[0] == "markdown")
    assert st.cfg_llamadas == 1, f"{titulo}: set_page_config llamado {st.cfg_llamadas} veces"
    assert estado == esperado, f"{titulo}: esperaba {esperado} y fue {estado}"
    print(f"  ✓ {titulo}")
    return md


with mock.patch.object(requests, "get", side_effect=OSError("sin red")), mock.patch.object(requests, "post", side_effect=OSError("sin red")), \
        mock.patch("geo_utils.ahora_madrid", return_value=MARTES_11):
    correr("carga inicial")
    clicks["k"] = lambda key: key == "crear"
    correr("crear paseo circular", "rerun")
    assert S["resultado"]["res"]["opciones"], "no se generó ninguna opción"
    clicks["k"] = lambda key: False
    md = correr("mostrar resultado")
    assert "Recomendada" in md and 'class="stop"' in md
    S["navegando"] = True
    correr("modo paseo en vivo")
    assert any("Empezar con GPS" in h for h, _ in st.html_comp), "no se pintó el modo paseo"
    S["navegando"] = False
    S["sim_clima"] = "Lluvia"; clicks["k"] = lambda key: key == "crear"
    correr("lluvia: crear paseo", "rerun")
    clicks["k"] = lambda key: False
    md = correr("lluvia: mostrar")
    ops = S["resultado"]["res"]["opciones"]
    assert ops and all(any(p["refugio_ok"] for p in o["paradas"]) for o in ops), "con lluvia todas las opciones deben tener techo"
    assert "Llueve" in md
    S["sim_clima"] = "Clima real"; S["modo"] = "De A a B"
    clicks["k"] = lambda key: key == "crear"
    correr("A→B: crear", "rerun")
    clicks["k"] = lambda key: False
    correr("A→B: mostrar")
    import storage
    R = S["resultado"]; op = R["res"]["opciones"][0]
    item = storage.crear_item(op, R["origen"], R["destino"], R["perfil"], R["duracion"], R["nombre_origen"], R["nombre_destino"])
    S["favoritos"], S["historial"] = [item], [item]
    clicks["k"] = lambda key: key.startswith("rep_favoritos")
    correr("repetir un favorito", "rerun")
    clicks["k"] = lambda key: key == "buscar_emerg"
    correr("emergencias sin red")
    os.environ["APP_PASSWORD"] = "secreto"
    for m in ("config", "app"):
        sys.modules.pop(m, None)
    S.clear(); clicks["k"] = lambda key: False
    correr("con contraseña configurada: la pide", "stop")
    S["autenticado"] = True
    correr("tras autenticarse")
print("SMOKE OK")

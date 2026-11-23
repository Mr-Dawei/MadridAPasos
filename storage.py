# -*- coding: utf-8 -*-
"""Favoritos e historial en el navegador del usuario (localStorage): sin servidor ni cuentas.

· Los datos se quedan en el dispositivo (privacidad por diseño; nada viaja a ningún servidor).
· La sesión de Streamlit es la fuente de verdad: se hidrata UNA vez desde localStorage y cada cambio
  reescribe la lista completa (antes se añadía en cada rerun y el historial se duplicaba).
· Si streamlit-js-eval no está instalado, funciona solo durante la sesión y la app avisa.
"""
import hashlib
import json
from datetime import datetime

import streamlit as st

try:
    from streamlit_js_eval import streamlit_js_eval
    JS_EVAL_OK = True
except ImportError:                                  # pragma: no cover
    JS_EVAL_OK = False

CLAVES = {"favoritos": "mapasos_favoritos", "historial": "mapasos_historial"}
MAX_ITEMS = {"favoritos": 50, "historial": 40}


def _js(expresion, key, salida=True):
    """Ejecuta JS en el navegador. Tolera versiones de streamlit-js-eval con distinta firma."""
    try:
        return streamlit_js_eval(js_expressions=expresion, want_output=salida, key=key)
    except TypeError:
        return streamlit_js_eval(js_expressions=expresion, key=key)


def firma(origen, destino, paradas):
    """Id estable de un paseo (mismo origen, destino y paradas → mismo id)."""
    base = json.dumps([[round(origen[0], 4), round(origen[1], 4)],
                       None if destino is None else [round(destino[0], 4), round(destino[1], 4)],
                       [p["nombre"] for p in paradas]], ensure_ascii=False)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def crear_item(opcion, origen, destino, perfil, duracion_min, nombre_origen, nombre_destino):
    paradas = [{k: p[k] for k in ("nombre", "categoria", "lat", "lon")} for p in opcion["paradas"]]
    return {"id": firma(origen, destino, paradas), "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "titulo": " → ".join(p["nombre"] for p in paradas) or f"{nombre_origen} → {nombre_destino}",
            "origen": list(origen), "destino": None if destino is None else list(destino),
            "nombre_origen": nombre_origen, "nombre_destino": nombre_destino,
            "perfil": perfil, "duracion_min": duracion_min, "km": round(opcion["km"], 2),
            "minutos": opcion["minutos"], "paradas": paradas,
            "waypoints": [list(w) for w in opcion.get("waypoints", [])]}


def _escribir(tipo, lista):
    """Escribe la lista completa en localStorage (una clave de widget nueva por escritura)."""
    if not JS_EVAL_OK:
        return
    n = st.session_state.get("_ls_n", 0) + 1
    st.session_state["_ls_n"] = n
    valor = json.dumps(json.dumps(lista, ensure_ascii=False))          # literal JS de una cadena JSON
    _js(f"localStorage.setItem('{CLAVES[tipo]}', {valor})", f"ls_w_{tipo}_{n}", salida=False)


def hidratar():
    """Llamar al inicio de cada ejecución: carga favoritos e historial desde localStorage la primera vez."""
    ss = st.session_state
    if ss.get("_ls_hidratado") or not JS_EVAL_OK:
        ss.setdefault("favoritos", [])
        ss.setdefault("historial", [])
        return
    crudo = _js("JSON.stringify({f: localStorage.getItem('%s') || '[]', h: localStorage.getItem('%s') || '[]'})"
                % (CLAVES["favoritos"], CLAVES["historial"]), "ls_lectura")
    if crudo is None:                                 # el navegador aún no ha respondido
        ss.setdefault("favoritos", [])
        ss.setdefault("historial", [])
        return
    try:
        d = json.loads(crudo)
        ss["favoritos"], ss["historial"] = json.loads(d["f"]), json.loads(d["h"])
    except (ValueError, KeyError, TypeError):
        ss["favoritos"], ss["historial"] = [], []
    ss["_ls_hidratado"] = True


def es_favorito(item_id):
    return any(x["id"] == item_id for x in st.session_state.get("favoritos", []))


def alternar_favorito(item):
    fav = [x for x in st.session_state.get("favoritos", []) if x["id"] != item["id"]]
    if len(fav) == len(st.session_state.get("favoritos", [])):         # no estaba → se añade
        fav.insert(0, item)
    st.session_state["favoritos"] = fav[:MAX_ITEMS["favoritos"]]
    _escribir("favoritos", st.session_state["favoritos"])


def registrar_historial(item):
    h = [x for x in st.session_state.get("historial", []) if x["id"] != item["id"]]
    h.insert(0, item)
    st.session_state["historial"] = h[:MAX_ITEMS["historial"]]
    _escribir("historial", st.session_state["historial"])


def quitar(tipo, item_id):
    st.session_state[tipo] = [x for x in st.session_state.get(tipo, []) if x["id"] != item_id]
    _escribir(tipo, st.session_state[tipo])


def borrar_todo():
    for tipo in ("favoritos", "historial"):
        st.session_state[tipo] = []
        _escribir(tipo, [])

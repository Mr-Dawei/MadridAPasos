# -*- coding: utf-8 -*-
"""Favoritos e historial en localStorage del navegador (sin servidor)."""
import json
import streamlit as st
import streamlit.components.v1 as components

try:
    from streamlit_js_eval import streamlit_js_eval
    JS_EVAL_OK = True
except ImportError:
    JS_EVAL_OK = False


def _guardar_lista(key, item, max_items=100):
    js = f"""
    <script>
      const k = '{key}';
      const arr = JSON.parse(window.parent.localStorage.getItem(k) || '[]');
      arr.unshift({json.dumps(item)});
      window.parent.localStorage.setItem(k, JSON.stringify(arr.slice(0, {max_items})));
    </script>
    """
    components.html(js, height=0)


def guardar_favorito(nombre, origen, destino, perfil):
    _guardar_lista("pasea_favoritos",
                   {"nombre": nombre, "origen": list(origen),
                    "destino": list(destino), "perfil": perfil})


def guardar_historial(origen, destino, km, minutos, perfil):
    _guardar_lista("pasea_historial",
                   {"origen": list(origen), "destino": list(destino),
                    "km": km, "minutos": minutos, "perfil": perfil},
                   max_items=50)


def _leer(key):
    if not JS_EVAL_OK:
        return []
    try:
        raw = streamlit_js_eval(js_expressions=f"localStorage.getItem('{key}')",
                                key=f"ls_{key}")
        return json.loads(raw) if raw else []
    except Exception:
        return []


def leer_favoritos():
    return _leer("pasea_favoritos")


def leer_historial():
    return _leer("pasea_historial")


def borrar_todo():
    components.html("""
    <script>
      window.parent.localStorage.removeItem('pasea_favoritos');
      window.parent.localStorage.removeItem('pasea_historial');
    </script>
    """, height=0)
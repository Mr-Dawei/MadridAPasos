# -*- coding: utf-8 -*-
"""Prepara el entorno de los tests: ruta del proyecto y un Streamlit mínimo si no está instalado."""
import pathlib
import sys
import types

RAIZ = pathlib.Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:
    import streamlit  # noqa: F401
except ImportError:
    def _deco(*a, **k):
        return a[0] if a and callable(a[0]) else (lambda f: f)
    _st = types.ModuleType("streamlit")
    _st.cache_data, _st.cache_resource, _st.secrets = _deco, _deco, {}
    sys.modules["streamlit"] = _st

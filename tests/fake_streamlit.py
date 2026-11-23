# -*- coding: utf-8 -*-
"""Streamlit simulado para probar app.py sin Streamlit ni navegador (prueba de humo, no de aspecto)."""
import sys
import types
from unittest import mock


class Rerun(Exception):
    pass


class Stop(Exception):
    pass


class SS(dict):
    """Como Streamlit real: no se puede escribir en la clave de un widget ya instanciado en esta ejecución."""
    bloqueadas = set()

    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __setitem__(self, k, v):
        if k in SS.bloqueadas:
            raise Exception(f"st.session_state.{k} cannot be modified after the widget with key {k} is instantiated.")
        super().__setitem__(k, v)


class _Ctx:
    """Contenedor (columna, pestaña, expander…): se usa con 'with' y reenvía los widgets al módulo."""
    def __init__(self, st, expander=False):
        self._st, self._exp = st, expander

    def __enter__(self):
        if self._exp:
            if self._st.prof_expander:
                raise Exception("Expanders may not be nested inside other expanders.")
            self._st.prof_expander += 1
        return self

    def __exit__(self, *a):
        if self._exp:
            self._st.prof_expander -= 1
        return False

    def __getattr__(self, n):
        return getattr(self._st, n)


def instalar(clicks=lambda key: False):
    """Registra módulos falsos en sys.modules y devuelve el 'streamlit' falso (con .salidas para inspeccionar)."""
    st = types.ModuleType("streamlit")
    st.session_state, st.secrets, st.salidas, st.html_comp, st.cfg_llamadas = SS(), {}, [], [], 0
    st.prof_expander = 0
    st.clicks = clicks

    def deco(*a, **k):
        return a[0] if a and callable(a[0]) else (lambda f: f)
    st.cache_data, st.cache_resource = deco, deco

    def set_page_config(**k):
        st.cfg_llamadas += 1
        if st.cfg_llamadas > 1:
            raise Exception("set_page_config() can only be called once per app page")
    st.set_page_config = set_page_config
    st.nueva_ejecucion = lambda: (SS.bloqueadas.clear(), setattr(st, 'prof_expander', 0), setattr(st, 'cfg_llamadas', 0))

    def emitir(tipo):
        return lambda *a, **k: st.salidas.append((tipo, a[0] if a else ""))
    for n in ("markdown", "caption", "write", "info", "warning", "error", "success", "subheader", "title", "header", "dataframe"):
        setattr(st, n, emitir(n))

    def guardar(key, valor):
        if key is not None:
            if key in SS.bloqueadas:
                raise Exception(f"DuplicateWidgetID: {key}")
            if key not in st.session_state:
                dict.__setitem__(st.session_state, key, valor)
            SS.bloqueadas.add(key)
            return st.session_state[key]
        return valor
    st.radio = lambda label, options, index=0, key=None, **k: guardar(key, list(options)[index])
    st.selectbox = lambda label, options, index=0, key=None, **k: guardar(key, list(options)[index])
    st.slider = lambda label, mn=0, mx=100, value=None, key=None, **k: guardar(key, mn if value is None else value)
    st.checkbox = lambda label, value=False, key=None, **k: guardar(key, value)
    st.toggle = st.checkbox
    st.multiselect = lambda label, options, default=None, key=None, **k: guardar(key, list(default or []))
    st.text_input = lambda label, key=None, **k: guardar(key, "")
    st.button = lambda label, key=None, **k: bool(st.clicks(key or label))
    st.download_button = lambda *a, **k: False
    st.link_button = lambda *a, **k: False
    st.columns = lambda spec, **k: [_Ctx(st) for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs = lambda nombres: [_Ctx(st) for _ in nombres]
    st.expander = lambda *a, **k: _Ctx(st, expander=True)
    st.spinner = lambda *a, **k: _Ctx(st)
    st.container = lambda *a, **k: _Ctx(st)

    def rerun():
        raise Rerun()

    def stop():
        raise Stop()
    st.rerun, st.stop = rerun, stop

    v1 = types.ModuleType("streamlit.components.v1")
    v1.html = lambda h, height=None, **k: st.html_comp.append((h, height))
    comp = types.ModuleType("streamlit.components")
    comp.v1, st.components = v1, comp
    sys.modules.update({"streamlit": st, "streamlit.components": comp, "streamlit.components.v1": v1})

    sf = types.ModuleType("streamlit_folium")
    sf.st_folium = lambda m, **k: st.salidas.append(("mapa", k))
    sj = types.ModuleType("streamlit_js_eval")
    sj.streamlit_js_eval = lambda **k: None
    sj.get_geolocation = lambda *a, **k: None
    folium = mock.MagicMock()
    sys.modules.update({"streamlit_folium": sf, "streamlit_js_eval": sj, "folium": folium, "folium.plugins": folium.plugins})

    class FakeFPDF:
        def __init__(s, *a, **k): s.y = 20
        def get_y(s): return s.y
        def set_y(s, v): s.y = v
        def __getattr__(s, n): return lambda *a, **k: None
        def output(s, *a): return bytearray(b"%PDF-fake")
    sys.modules["fpdf"] = types.SimpleNamespace(FPDF=FakeFPDF)
    return st

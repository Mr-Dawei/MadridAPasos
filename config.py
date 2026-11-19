# -*- coding: utf-8 -*-
import os

try:
    import streamlit as st
    _SECRETS_OK = True
except ImportError:
    _SECRETS_OK = False


def _leer_clave(nombre, valor_local=""):
    if _SECRETS_OK:
        try:
            if nombre in st.secrets:
                return st.secrets[nombre]
        except (FileNotFoundError, KeyError):
            pass
    return os.getenv(nombre, valor_local)


ORS_API_KEY        = _leer_clave("ORS_API_KEY",        "")
OPEN_ELEVATION_KEY = _leer_clave("OPEN_ELEVATION_KEY", "")

APP_NAME = "MadridAPasos"
APP_TAGLINE = "Rutas que respiran contigo"
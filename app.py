# -*- coding: utf-8 -*-
"""Pasea Madrid · app principal."""
import json
from datetime import datetime

import folium
from folium.plugins import FastMarkerCluster
import pandas as pd
import requests
import streamlit as st
st.set_page_config(page_title="Pasea Madrid", layout="wide")
from streamlit_folium import st_folium

from config import APP_NAME, APP_TAGLINE
from data_loader import (
    construir_registro_pois, construir_registro_emergencias,
    cargar_clima, cargar_arbolado, FEEDS_ATOM,
)
from geo_utils import (
    haversine, haversine_vec, obtener_estacion, necesita_refugio,
    UMBRALES_CLIMA, UMBRAL_LLUVIA, calcular_abierto_ahora,
)
from routing import calcular_ruta, calcular_ruta_circular, calcular_desnivel
from scoring import evaluar_ruta, pesos_por_perfil, CRITERIOS_AHP
from storage import guardar_favorito, guardar_historial, leer_favoritos, leer_historial, borrar_todo
from ui_components import (
    boton_geolocalizacion, botones_compartir, boton_tts, barra_progreso_gps,
)

PASSWORD = "datathon2026"  

if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

if not st.session_state["autenticado"]:
    st.title("🚶 Pasea Madrid")
    st.caption("Acceso restringido al jurado del datathon")
    pwd = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if pwd == PASSWORD:
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    st.stop()


st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="🚶")

# ---------------- CSS global (Apple Maps style) ----------------
st.markdown("""
<style>
html, body, [class*="css"] {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
h1 { font-size: 1.6rem !important; font-weight: 700; letter-spacing: -0.02em; }
h2 { font-size: 1.25rem !important; font-weight: 600; }
.stButton button {
  border-radius: 999px; padding: 0.6rem 1.4rem; font-weight: 600;
  background: #0A84FF; color: white; border: none;
  box-shadow: 0 2px 6px rgba(10,132,255,0.25);
}
.stButton button:hover { background: #0070e0; }
.stMetric {
  background: #F5F5F7; border-radius: 14px; padding: 0.8rem 1rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
@media (max-width: 768px) {
  section[data-testid="stSidebar"] { display: none !important; }
  .block-container { padding: 1rem 0.8rem !important; }
  h1 { font-size: 1.3rem !important; }
}
</style>
""", unsafe_allow_html=True)


# ---------------- PUNTOS PREDEFINIDOS ----------------
LUGARES_MADRID = {
    "Puerta del Sol": (40.4169, -3.7035),
    "Parque del Retiro (Puerta de Alcalá)": (40.4199, -3.6887),
    "Estación de Atocha": (40.4065, -3.6896),
    "Templo de Debod": (40.4240, -3.7178),
    "Plaza Mayor": (40.4155, -3.7074),
    "Matadero Madrid (Madrid Río)": (40.3917, -3.6974),
    "Nuevos Ministerios": (40.4463, -3.6921),
}
CENTRO_LAT, CENTRO_LON, CENTRO_RADIO_M = 40.4169, -3.7035, 1200


# ---------------- ESTADO ----------------
if "origen" not in st.session_state:
    st.session_state["origen"] = LUGARES_MADRID["Puerta del Sol"]
    st.session_state["origen_nombre"] = "Puerta del Sol"
if "destino" not in st.session_state:
    st.session_state["destino"] = LUGARES_MADRID["Parque del Retiro (Puerta de Alcalá)"]
    st.session_state["destino_nombre"] = "Parque del Retiro (Puerta de Alcalá)"

# Geolocalización desde URL
try:
    params = st.query_params
except AttributeError:
    params = st.experimental_get_query_params()
lat_url = params.get("user_lat")
lon_url = params.get("user_lon")
if lat_url and lon_url:
    try:
        st.session_state["origen"] = (float(lat_url), float(lon_url))
        st.session_state["origen_nombre"] = "Mi ubicación"
        try:
            st.query_params.clear()
        except Exception:
            pass
    except (ValueError, TypeError):
        pass


# ---------------- SIDEBAR ----------------
with st.sidebar:
    st.markdown(f"### {APP_NAME}")
    st.caption(APP_TAGLINE)
    st.divider()

    st.markdown("**1 · Trayecto**")
    perfil = st.radio(
        "Perfil de paseo",
        ["tranquilo", "activo", "movilidad_reducida"],
        format_func=lambda x: {"tranquilo": "🌿 Paseo tranquilo",
                               "activo": "🎨 Paseo activo",
                               "movilidad_reducida": "♿ Movilidad reducida"}[x],
        horizontal=False,
    )

    tipo_paseo = st.radio("Tipo", ["A → B", "Circular"], horizontal=True)
    if tipo_paseo == "Circular":
        duracion_circular = st.slider("Duración (min)", 15, 90, 45, step=5)
        destino_nombre = "(circular)"
        destino = None
    else:
        origen_nombre = st.selectbox("Origen", list(LUGARES_MADRID.keys()), index=0)
        destino_nombre = st.selectbox("Destino", list(LUGARES_MADRID.keys()), index=1)
        st.session_state["origen"] = LUGARES_MADRID[origen_nombre]
        st.session_state["origen_nombre"] = origen_nombre
        st.session_state["destino"] = LUGARES_MADRID[destino_nombre]
        st.session_state["destino_nombre"] = destino_nombre

    boton_geolocalizacion()

    st.divider()
    st.markdown("**2 · Clima**")
    usar_clima_real = st.toggle("Usar clima real", value=True)
    clima = cargar_clima()
    estacion_auto = obtener_estacion()
    estacion = st.selectbox(
        "Estación", ["primavera", "verano", "otono", "invierno"],
        index=["primavera", "verano", "otono", "invierno"].index(estacion_auto),
    )
    if usar_clima_real:
        temp, lluvia, uv = clima["temp"], clima["lluvia"], clima["uv"]
        st.info(f"**{temp:.1f} °C** · {lluvia:.1f} mm · UV {uv:.1f}")
    else:
        temp = st.slider("Temperatura (°C)", 0, 42, 30)
        lluvia = st.slider("Lluvia (mm/h)", 0.0, 15.0, 0.0, step=0.5)
        uv = st.slider("UV", 0.0, 11.0, 3.0, step=0.5)

    hay_refugio, motivo_refugio = necesita_refugio(temp, lluvia, uv, estacion)
    refugio_manual = st.checkbox("Buscar refugio obligatorio", value=hay_refugio)
    if hay_refugio or refugio_manual:
        st.warning(f"Refugio activo: {motivo_refugio or 'manual'}")

    st.divider()
    st.markdown("**3 · Capas**")
    categorias_activas = []
    for cat in ["fuentes", "parques", "monumentos", "museos",
                "bibliotecas", "centros_culturales", "centros_mayores"]:
        if st.checkbox(cat.replace("_", " ").capitalize(), value=True, key=f"cat_{cat}"):
            categorias_activas.append(cat)
    evitar_centro = st.checkbox("Evitar el centro", value=False)
    mostrar_arbolado = st.checkbox("Mostrar arbolado", value=False)

    st.divider()
    st.markdown("**4 · Pesos (0-10)**")
    ajustes_usuario = {}
    with st.expander("Ajustar criterios"):
        for c in CRITERIOS_AHP:
            ajustes_usuario[c] = st.slider(c.capitalize(), 0, 10,
                                            pesos_por_perfil(perfil).get(c, 5),
                                            key=f"peso_{c}")


# ---------------- CARGA DE DATOS ----------------
pois_df = construir_registro_pois(tuple(categorias_activas))
pois_df = calcular_abierto_ahora(pois_df, datetime.now())

origen = st.session_state["origen"]
if tipo_paseo == "A → B":
    destino = st.session_state["destino"]
    if origen == destino:
        st.warning("Origen y destino deben ser distintos.")
        st.stop()

if evitar_centro and not pois_df.empty:
    d = pois_df.apply(lambda r: haversine(CENTRO_LAT, CENTRO_LON, r["lat"], r["lon"]), axis=1)
    pois_df = pois_df.loc[d > CENTRO_RADIO_M].reset_index(drop=True)

punto_medio = ((origen[0] + (destino[0] if destino else origen[0] + 0.005)) / 2,
               (origen[1] + (destino[1] if destino else origen[1] + 0.005)) / 2)

# ---------------- RUTA ----------------
with st.spinner("Calculando ruta peatonal…"):
    if tipo_paseo == "Circular":
        geometria, km, minutos = calcular_ruta_circular(origen, duracion_circular)
    else:
        geometria, km, minutos = calcular_ruta(origen, None, destino)
    desnivel_m = calcular_desnivel(geometria)

# Evaluación
pesos = pesos_por_perfil(perfil, ajustes_usuario)
resultado = evaluar_ruta(geometria, km, minutos, desnivel_m, pois_df,
                          cargar_arbolado() if mostrar_arbolado else pd.DataFrame(columns=["LATITUD","LONGITUD"]),
                          pesos, perfil, lluvia, refugio_manual)


# ---------------- HEADER ----------------
st.title(APP_NAME)
st.caption(f"{APP_TAGLINE} · {estacion.capitalize()} · "
           f"Refugio {'sí' if (hay_refugio or refugio_manual) else 'no'} · "
           f"Perfil: {perfil.replace('_', ' ')}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Distancia", f"{km:.2f} km")
c2.metric("Tiempo", f"{minutos} min")
c3.metric("Desnivel", f"{desnivel_m:.0f} m")
c4.metric("Score", f"{resultado['score']:.0f}" if resultado["pasa_filtros"] else "—")

if not resultado["pasa_filtros"]:
    st.error(f"⚠️ {resultado['motivo_filtro']}")
else:
    st.success(f"✅ {resultado['explicacion']}")

# ---------------- TABS ----------------
tab_mapa, tab_ruta, tab_fav, tab_emerg, tab_ajustes = st.tabs(
    ["🗺 Mapa", "🧭 Ruta", "⭐ Favoritos", "🚨 Emergencias", "⚙️ Ajustes"])

# --- MAPA ---
with tab_mapa:
    radio_mapa_m = st.slider("Radio de POIs (m)", 500, 5000, 1500, step=500)
    if not pois_df.empty:
        d = haversine_vec(punto_medio[0], punto_medio[1],
                          pois_df["lat"].values, pois_df["lon"].values)
        pois_mapa = pois_df.loc[d <= radio_mapa_m].reset_index(drop=True)
    else:
        pois_mapa = pois_df

    mapa = folium.Map(location=punto_medio, zoom_start=14, tiles="OpenStreetMap")

    for cat in categorias_activas:
        sub = pois_mapa[pois_mapa["categoria"] == cat]
        if sub.empty:
            continue
        color, icono = FEEDS_ATOM.get(cat, {}).get("icono", ("gray", "circle"))
        if len(sub) > 100:
            FastMarkerCluster(sub[["lat", "lon"]].values.tolist(),
                              name=f"{cat} ({len(sub)})").add_to(mapa)
        else:
            g = folium.FeatureGroup(name=f"{cat} ({len(sub)})")
            for _, r in sub.iterrows():
                popup = f"<b>{r['nombre']}</b>"
                if r["descripcion"]:
                    popup += f"<br><small>{r['descripcion'][:200]}</small>"
                if not r["abierto_ahora"] and not r["horario_desconocido"]:
                    popup += "<br><span style='color:#b91c1c'>Cerrado ahora</span>"
                folium.Marker([r["lat"], r["lon"]],
                              icon=folium.Icon(color=color, icon=icono, prefix="fa"),
                              popup=folium.Popup(popup, max_width=280),
                              tooltip=r["nombre"]).add_to(g)
            g.add_to(mapa)

    if mostrar_arbolado:
        arb = cargar_arbolado()
        if not arb.empty:
            d = haversine_vec(punto_medio[0], punto_medio[1],
                              arb["LATITUD"].values, arb["LONGITUD"].values)
            arb_c = arb.loc[d <= radio_mapa_m]
            if not arb_c.empty:
                FastMarkerCluster(arb_c[["LATITUD", "LONGITUD"]].values.tolist(),
                                  name=f"Arbolado ({len(arb_c)})").add_to(mapa)

    if evitar_centro:
        folium.Circle([CENTRO_LAT, CENTRO_LON], radius=CENTRO_RADIO_M,
                      color="#dc2626", fill=True, fill_opacity=0.08).add_to(mapa)

    folium.GeoJson(geometria, name="Ruta",
                   style_function=lambda _: {"color": "#0284c7", "weight": 6, "opacity": 0.9}).add_to(mapa)
    folium.Marker(origen, popup=f"Origen", icon=folium.Icon(color="green", icon="play")).add_to(mapa)
    if destino:
        folium.Marker(destino, popup=f"Destino", icon=folium.Icon(color="red", icon="flag")).add_to(mapa)
    folium.LayerControl(collapsed=False).add_to(mapa)

    try:
        cs = geometria["coordinates"]
        lats = [c[1] for c in cs]; lons = [c[0] for c in cs]
        mapa.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    except Exception:
        pass

    st_folium(mapa, height=560, use_container_width=True, returned_objects=[])


# --- RUTA ---
with tab_ruta:
    st.subheader("Tu ruta")
    st.write(resultado["explicacion"] if resultado["pasa_filtros"] else resultado["motivo_filtro"])

    st.markdown("**Compartir / abrir en…**")
    if destino:
        botones_compartir(origen, destino, km, minutos,
                          st.session_state["origen_nombre"], st.session_state["destino_nombre"])
    texto_tts = (f"Tu ruta desde {st.session_state['origen_nombre']} "
                 f"hasta {st.session_state['destino_nombre']} tiene {km:.1f} kilómetros "
                 f"y se recorre en {minutos} minutos.")
    boton_tts(texto_tts)

    st.markdown("**Progreso en tiempo real**")
    if destino:
        barra_progreso_gps(origen, destino)

    if st.button("⭐ Guardar en favoritos", use_container_width=True):
        guardar_favorito(f"Ruta {datetime.now().strftime('%d/%m %H:%M')}",
                         origen, destino or origen, perfil)
        st.toast("Guardado en favoritos")

    # Desglose de scoring
    if resultado["pasa_filtros"] and resultado["criterios"]:
        with st.expander("Ver desglose de puntuación"):
            df_crit = pd.DataFrame(resultado["criterios"]).T.reset_index()
            df_crit.columns = ["Criterio", "Valor bruto", "Normalizado (1-100)", "Peso", "Contribución"]
            st.dataframe(df_crit, use_container_width=True, hide_index=True)


# --- FAVORITOS ---
with tab_fav:
    st.subheader("Favoritos")
    favs = leer_favoritos()
    if not favs:
        st.info("Aún no tienes favoritos guardados. Se guardan en tu navegador.")
    else:
        for f in favs:
            st.write(f"⭐ **{f['nombre']}** · {f['perfil']}")

    st.divider()
    st.subheader("Historial reciente")
    hist = leer_historial()
    if hist:
        st.dataframe(pd.DataFrame(hist[:20]), use_container_width=True)
    else:
        st.caption("Sin historial todavía.")

    if st.button("🗑 Borrar todo"):
        borrar_todo()
        st.toast("Borrado")


# --- EMERGENCIAS ---
with tab_emerg:
    st.subheader("Emergencias cerca de ti")
    st.caption("Farmacias, centros de salud y comisarías.")
    df_emerg = construir_registro_emergencias()
    if df_emerg.empty:
        st.info("Añade los feeds `farmacias.geo`, `centros_salud.geo`, `comisarias.geo` "
                "en la carpeta de la app para verlos aquí.")
    else:
        mapa_e = folium.Map(location=origen, zoom_start=15, tiles="OpenStreetMap")
        for _, r in df_emerg.iterrows():
            color, icono = r["icono"]
            folium.Marker([r["lat"], r["lon"]],
                          icon=folium.Icon(color=color, icon=icono, prefix="fa"),
                          popup=f"<b>{r['nombre']}</b>").add_to(mapa_e)
        folium.Marker(origen, icon=folium.Icon(color="blue", icon="user")).add_to(mapa_e)
        st_folium(mapa_e, height=460, use_container_width=True, returned_objects=[])


# --- AJUSTES ---
with tab_ajustes:
    st.subheader("Ajustes avanzados")
    st.markdown(f"""
    **Umbrales climáticos actuales ({estacion}):**
    - Calor: `{UMBRALES_CLIMA[estacion]['temp_calor']}`
    - Frío: `{UMBRALES_CLIMA[estacion]['temp_frio']}`
    - UV: `{UMBRALES_CLIMA[estacion]['uv']}`
    - Lluvia: `> {UMBRAL_LLUVIA} mm/h`
    """)
    st.write("**Categorías activas:**", ", ".join(categorias_activas) or "(ninguna)")
    st.write("**Pesos actuales:**", pesos)
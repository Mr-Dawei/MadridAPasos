# -*- coding: utf-8 -*-
"""MadridAPasos · paseos por Madrid con sombra, fuentes y sitios de interés, adaptados al clima."""
import hmac
import html

import pandas as pd
import streamlit as st

from config import (APP_NAME, APP_PASSWORD, APP_TAGLINE, BBOX_MADRID, CATEGORIAS, CATEGORIAS_DEFECTO, CENTRO_LAT, CENTRO_LON,
                    LUGARES_MADRID, PERFILES, UMBRALES)

st.set_page_config(page_title=APP_NAME, page_icon="🌳", layout="wide", initial_sidebar_state="collapsed")   # ÚNICA llamada

import streamlit.components.v1 as components

import storage
from data_loader import cargar_clima, cargar_indice_arbolado, construir_registro_pois, estado_datos
from emergencias import TIPOS as TIPOS_EMERG, buscar_servicios, calidad_aire
from geo_utils import ahora_madrid, calcular_abierto_ahora, evaluar_clima, haversine
from pdf_export import generar_pdf
from planner import planificar, reconstruir_paseo
from routing import geocodificar
from scoring import CRITERIOS_AHP, ETIQUETAS, PESOS_PERFIL, pesos_por_perfil
from ui_components import (alertas_clima_html, cabecera_html, construir_mapa, criterios_html, estilos, html_boton_voz, html_navegacion,
                           paradas_html, pasos_html, tarjeta_resumen_html, texto_clima, texto_para_voz, urls_compartir, vacio_html)

try:
    from streamlit_js_eval import get_geolocation
    GPS_OK = True
except ImportError:                                                      # pragma: no cover
    GPS_OK = False

S = st.session_state
OPCION_GPS, OPCION_BUSCAR = "📍 Mi ubicación (GPS)", "🔎 Buscar una dirección…"


# =====================================================================
#  ACCESO (opcional): la contraseña va en secrets/entorno, nunca en el código
# =====================================================================
def pantalla_acceso():
    if not APP_PASSWORD or S.get("autenticado"):
        return
    st.markdown(estilos(), unsafe_allow_html=True)
    st.markdown(cabecera_html(""), unsafe_allow_html=True)
    st.markdown('<div class="card">🔒 Acceso restringido. Introduce la contraseña que te han facilitado.</div>', unsafe_allow_html=True)
    clave = st.text_input("Contraseña", type="password", key="clave_acceso")
    if st.button("Entrar", type="primary", key="entrar"):
        if hmac.compare_digest(clave.encode("utf-8"), APP_PASSWORD.encode("utf-8")):
            S["autenticado"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()


# =====================================================================
#  SELECCIÓN DE LUGARES (lista, GPS o búsqueda de direcciones)
# =====================================================================
def dentro_de_madrid(p):
    lon0, lat0, lon1, lat1 = BBOX_MADRID
    return lat0 <= p[0] <= lat1 and lon0 <= p[1] <= lon1


def obtener_gps():
    """Ubicación del navegador SIN recargar la página (así no se pierde la sesión). None mientras no haya permiso."""
    if S.get("gps"):
        return S["gps"]
    if not GPS_OK:
        st.caption("Para usar el GPS instala streamlit-js-eval (pip install -r requirements.txt).")
        return None
    if not S.get("pedir_gps"):
        if st.button("Permitir ubicación", key="btn_gps"):
            S["pedir_gps"] = True
            st.rerun()
        return None
    loc = get_geolocation()
    coords = (loc or {}).get("coords") or {}
    if coords.get("latitude") is not None:
        S["gps"], S["pedir_gps"] = (float(coords["latitude"]), float(coords["longitude"])), False
        st.rerun()
    st.caption("Esperando el permiso de ubicación del navegador…")
    return None


def selector_lugar(etiqueta, clave, defecto, permitir_gps=True):
    opciones = ([OPCION_GPS] if permitir_gps else []) + list(LUGARES_MADRID) + [OPCION_BUSCAR]
    sel = st.selectbox(etiqueta, opciones, index=opciones.index(defecto), key=f"sel_{clave}")
    if sel in LUGARES_MADRID:
        return LUGARES_MADRID[sel], sel
    if sel == OPCION_GPS:
        pos = obtener_gps()
        if pos and not dentro_de_madrid(pos):
            st.warning("Parece que no estás en Madrid: elige un punto de la ciudad en la lista.")
            return None, None
        return (pos, "Mi ubicación") if pos else (None, None)
    q = st.text_input("Dirección o lugar", key=f"q_{clave}", placeholder="Calle Mayor 5, Plaza de España…")
    if st.button("Buscar", key=f"buscar_{clave}"):
        S[f"res_{clave}"], S[f"buscado_{clave}"] = geocodificar(q), True
    res = S.get(f"res_{clave}") or []
    if res:
        i = st.selectbox("Resultados", range(len(res)), format_func=lambda k: res[k]["nombre"], key=f"resel_{clave}")
        return (res[i]["lat"], res[i]["lon"]), res[i]["nombre"]
    if S.get(f"buscado_{clave}"):
        st.caption("No encuentro esa dirección en Madrid. Prueba con otra.")
    return None, None


# =====================================================================
#  CLIMA (real o simulado para la demo)
# =====================================================================
def clima_efectivo(real):
    sim = S.get("sim_clima", "Clima real")
    if sim == "Lluvia":
        return {"ok": True, "temp": 14.0, "lluvia": 4.0, "uv": 1.0}, True
    if sim == "Calor (34 °C)":
        return {"ok": True, "temp": 34.0, "lluvia": 0.0, "uv": 8.0}, True
    if sim == "Frío (3 °C)":
        return {"ok": True, "temp": 3.0, "lluvia": 0.0, "uv": 1.0}, True
    if sim == "Personalizado":
        return {"ok": True, "temp": float(S.get("sim_temp", 22)), "lluvia": float(S.get("sim_lluvia", 0.0)), "uv": float(S.get("sim_uv", 3.0))}, True
    return real, False


# =====================================================================
#  PLANIFICADOR (columna izquierda)
# =====================================================================
def panel_planificador(pois, indice, flags):
    with st.expander("🧭 Tu paseo", expanded=not S.get("resultado")):
        modo = st.radio("Tipo de paseo", ["Circular", "De A a B"], horizontal=True, key="modo",
                        help="Circular: sales y vuelves al mismo sitio. De A a B: vas de un punto a otro pasando por lugares de interés.")
        origen, nombre_origen = selector_lugar("¿Desde dónde sales?", "origen", "Puerta del Sol", permitir_gps=True)
        destino = nombre_destino = None
        if modo == "De A a B":
            destino, nombre_destino = selector_lugar("¿A dónde vas?", "destino", "Parque del Retiro (Puerta de Alcalá)", permitir_gps=False)
        duracion = st.slider("Tiempo para pasear" if modo == "Circular" else "Tiempo disponible", 15, 120, 45, step=5,
                             format="%d min", key="duracion", help="Incluye unos 5 minutos por parada. Con más tiempo, más paradas (de 1 a 3).")
        perfil = st.radio("Perfil", list(PERFILES), horizontal=True, key="perfil",
                          format_func=lambda k: f'{PERFILES[k]["icono"]} {PERFILES[k]["etiqueta"]}')
        refugio_manual = st.checkbox("☂️ Quiero pasar por un sitio con techo", key="refugio_manual",
                                     help="Si lo marcas, el paseo pasará sí o sí por un museo, biblioteca o centro cultural abierto.")
        categorias, evitar_centro = list(CATEGORIAS_DEFECTO), False        # (Streamlit no permite expanders anidados)
        if st.checkbox("Elegir qué quiero ver", key="personalizar"):
            categorias = st.multiselect("Tipos de lugares", list(CATEGORIAS), default=list(CATEGORIAS_DEFECTO), key="categorias",
                                        format_func=lambda k: f'{CATEGORIAS[k]["icono"]} {CATEGORIAS[k]["etiqueta"]}')
            evitar_centro = st.checkbox("Evitar el centro (Puerta del Sol)", key="evitar_centro")
        st.checkbox("🔎 Texto grande", key="texto_grande")
        crear = st.button("Crear paseo", type="primary", key="crear")

    if origen:
        S["ultimo_origen"] = origen
    if not crear:
        return
    if origen is None:
        st.warning("Elige primero de dónde sales.")
        return
    if modo == "De A a B":
        if destino is None:
            st.warning("Elige un destino.")
            return
        if haversine(*origen, *destino) < 150:
            st.warning("Origen y destino son el mismo sitio: prueba con un paseo circular.")
            return
    ajustes = {c: S[f"peso_{perfil}_{c}"] for c in CRITERIOS_AHP if f"peso_{perfil}_{c}" in S}
    with st.spinner("Buscando el mejor paseo…"):
        res = planificar(origen, destino, duracion, perfil, pois, indice, pesos_por_perfil(perfil, ajustes), flags,
                         refugio_manual, categorias or None, evitar_centro)
    S["resultado"] = {"res": res, "origen": origen, "destino": destino, "perfil": perfil, "duracion": duracion,
                      "nombre_origen": nombre_origen, "nombre_destino": nombre_destino or "(circular)"}
    S["_reset_opcion"], S["navegando"] = True, False
    st.rerun()


# =====================================================================
#  RESULTADO (columna derecha)
# =====================================================================
def mostrar_mapa(mapa, alto=520):
    try:
        from streamlit_folium import st_folium
    except ImportError:
        st.error("Falta streamlit-folium: ejecuta pip install -r requirements.txt")
        return
    try:
        st_folium(mapa, height=alto, use_container_width=True, returned_objects=[], key="mapa_principal")
    except TypeError:                                                    # versiones sin use_container_width
        st_folium(mapa, height=alto, returned_objects=[], key="mapa_principal")


def columna_resultado(pois, indice):
    if S.pop("_reset_opcion", False):            # no se puede escribir en la clave de un widget ya creado en esta ejecución
        S["opcion_idx"] = 0
    R = S.get("resultado")
    if not R:
        st.markdown(vacio_html("Elige cómo quieres pasear y pulsa «Crear paseo». Te propondremos de 1 a 3 paradas con sombra, "
                               "fuentes y sitios de interés."), unsafe_allow_html=True)
        centro = S.get("ultimo_origen") or (CENTRO_LAT, CENTRO_LON)
        mostrar_mapa(construir_mapa(centro, origen=S.get("ultimo_origen"), indice=indice, mostrar_sombra=True))
        return
    res = R["res"]
    for aviso in res["avisos"]:
        st.warning(aviso)
    opciones = res["opciones"] or ([res["base"]] if res["base"] else [])
    if not opciones:
        st.markdown(vacio_html("No hemos podido crear un paseo con esas condiciones. Prueba con más tiempo, otras categorías "
                               "o desmarca el techo."), unsafe_allow_html=True)
        return
    if not res["opciones"]:
        st.info("No encontré paradas que encajen: te muestro la ruta directa.")
    idx = 0
    if len(opciones) > 1:
        idx = st.radio("Opciones de paseo", list(range(len(opciones))), horizontal=True, key="opcion_idx",
                       format_func=lambda i: f'{opciones[i]["etiqueta"]} · {opciones[i]["minutos"]} min')
    opcion = opciones[min(idx, len(opciones) - 1)]
    origen, destino, perfil = R["origen"], R["destino"], R["perfil"]
    ritmo = PERFILES[perfil]["ritmo_m_min"]

    st.markdown(tarjeta_resumen_html(opcion, res["base"] if res["opciones"] else None), unsafe_allow_html=True)
    item = storage.crear_item(opcion, origen, destino, perfil, R["duracion"], R["nombre_origen"], R["nombre_destino"])
    c1, c2 = st.columns(2)
    if c1.button("▶ Empezar paseo", type="primary", key=f"empezar_{item['id']}"):
        storage.registrar_historial(item)
        S["navegando"] = True
        st.rerun()
    favorito = storage.es_favorito(item["id"])
    if c2.button("★ En favoritos" if favorito else "☆ Guardar en favoritos", key=f"fav_{item['id']}"):
        storage.alternar_favorito(item)
        st.rerun()
    with st.popover("📤 Compartir, PDF y voz", use_container_width=True):
        urls = urls_compartir(opcion, origen, destino)

        st.markdown("**Abrir en el móvil**")
        st.link_button("🗺 Google Maps", urls["google"], use_container_width=True)
        st.link_button("🍎 Apple Maps", urls["apple"], use_container_width=True)
        st.link_button("💬 Compartir por WhatsApp", urls["whatsapp"], use_container_width=True)

        st.divider()
        st.markdown("**Descargar**")
        try:
            clima_txt = S.get("clima_txt", "")
            pdf = generar_pdf(opcion, origen, destino, perfil, R["nombre_origen"], R["nombre_destino"], clima_txt)
            st.download_button(
                "📄 PDF para imprimir", pdf,
                file_name="mi_paseo.pdf", mime="application/pdf",
                key=f"pdf_{item['id']}", use_container_width=True,
            )
        except ImportError:
            st.caption("Instala fpdf2 para exportar a PDF.")
        except Exception as e:
            st.caption(f"No se pudo generar el PDF ({type(e).__name__}).")

        st.divider()
        st.markdown("**Escuchar**")
        components.html(html_boton_voz(texto_para_voz(opcion)), height=64)

    if S.get("navegando"):
        components.html(html_navegacion(opcion, ritmo), height=650)
        if st.button("⏹ Terminar paseo", key="terminar"):
            S["navegando"] = False
            st.rerun()
        st.caption("Si no puedes salir a caminar ahora, pulsa «Simular paseo» para ver cómo avanza tu progreso.")
        return

    t_mapa, t_ind, t_det = st.tabs(["🗺 Mapa", "🧭 Indicaciones", "📊 Detalle"])
    with t_mapa:
        capas = st.multiselect("Capas del mapa", ["Sombra (arbolado)", "Fuentes", "Lugares de interés"], default=["Sombra (arbolado)"], key="capas")
        pts = opcion["ruta"].pts()
        lats, lons = [p[0] for p in pts], [p[1] for p in pts]
        centro = (sum(lats) / len(lats), sum(lons) / len(lons))
        zona = pois[pois["lat"].between(min(lats) - 0.004, max(lats) + 0.004) & pois["lon"].between(min(lons) - 0.005, max(lons) + 0.005)]
        cats = (["fuentes"] if "Fuentes" in capas else []) + (list(CATEGORIAS_DEFECTO) if "Lugares de interés" in capas else [])
        mostrar_mapa(construir_mapa(centro, opcion, origen, destino, zona[zona["categoria"].isin(cats)] if cats else None,
                                    indice, "Sombra (arbolado)" in capas, 1500))
        st.markdown(paradas_html(opcion["paradas"]), unsafe_allow_html=True)
    with t_ind:
        st.markdown(pasos_html(opcion["ruta"].pasos), unsafe_allow_html=True)
    with t_det:
        ev = opcion["evaluacion"]
        st.markdown(criterios_html(ev), unsafe_allow_html=True)
        if res["opciones"]:
            filas = [{"Opción": o["etiqueta"], "Min": o["minutos"], "Km": round(o["km"], 2), "Puntuación": o["evaluacion"]["score"],
                      "Sombra %": None if o["evaluacion"]["metricas"]["pct_sombra"] is None else round(o["evaluacion"]["metricas"]["pct_sombra"] * 100),
                      "Fuentes": o["evaluacion"]["metricas"]["n_fuentes"]} for o in res["opciones"]]
            if res["base"]:
                b = res["base"]
                filas.append({"Opción": "Ruta directa", "Min": b["minutos"], "Km": round(b["km"], 2), "Puntuación": b["evaluacion"]["score"],
                              "Sombra %": None if b["evaluacion"]["metricas"]["pct_sombra"] is None else round(b["evaluacion"]["metricas"]["pct_sombra"] * 100),
                              "Fuentes": b["evaluacion"]["metricas"]["n_fuentes"]})
            st.dataframe(pd.DataFrame(filas), hide_index=True)
        st.caption("Ruta: " + {"ors": "OpenRouteService", "fossgis": "servidor público FOSSGIS (OpenStreetMap)",
                               "linea": "línea recta aproximada"}[opcion["ruta"].fuente])


# =====================================================================
#  PESTAÑAS INFERIORES
# =====================================================================
def pestana_guardados(pois, indice, flags):
    vista = st.radio("Ver", ["Favoritos", "Historial"], horizontal=True, key="vista_guardados")
    tipo = "favoritos" if vista == "Favoritos" else "historial"
    lista = S.get(tipo, [])
    if not lista:
        st.markdown(vacio_html("Aquí aparecerán tus paseos favoritos." if tipo == "favoritos" else "Aquí aparecerán los paseos que empieces."),
                    unsafe_allow_html=True)
        st.caption("Se guardan solo en este dispositivo (no en ningún servidor).")
        return
    for it in lista:
        st.markdown(f'<div class="card"><b>{html.escape(it["titulo"])}</b><br><span class="muted">{it["km"]} km · {it["minutos"]} min · '
                    f'{PERFILES[it["perfil"]]["etiqueta"]} · {html.escape(it["ts"])}</span></div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        if a.button("Repetir", key=f"rep_{tipo}_{it['id']}"):
            with st.spinner("Preparando el paseo con el clima y los horarios de ahora…"):
                res = reconstruir_paseo(it, pois, indice, flags)
            d = it["destino"]
            S["resultado"] = {"res": res, "origen": tuple(it["origen"]), "destino": tuple(d) if d else None, "perfil": it["perfil"],
                              "duracion": it["duracion_min"], "nombre_origen": it["nombre_origen"], "nombre_destino": it["nombre_destino"]}
            S["_reset_opcion"], S["navegando"] = True, False
            st.rerun()
        if b.button("Quitar", key=f"del_{tipo}_{it['id']}"):
            storage.quitar(tipo, it["id"])
            st.rerun()


def pestana_emergencias():
    st.markdown('<a class="sos" href="tel:112">📞 Llamar al 112</a>', unsafe_allow_html=True)
    lat, lon = S.get("ultimo_origen") or (CENTRO_LAT, CENTRO_LON)
    st.caption("Busca desde tu punto de salida. Datos de OpenStreetMap y Open-Meteo.")
    if st.button("Buscar servicios cerca", key="buscar_emerg"):
        with st.spinner("Consultando servicios cercanos…"):
            S["emerg"] = {"servicios": buscar_servicios(lat, lon), "aire": calidad_aire(lat, lon)}
    E = S.get("emerg")
    if not E:
        st.markdown(vacio_html("Pulsa el botón para ver farmacias, centros de salud, desfibriladores, aseos y bancos cerca de ti."),
                    unsafe_allow_html=True)
        return
    aire = E["aire"]
    if aire["aqi"] is not None:
        polen = " · ".join(f"{k}: {v:.0f} granos/m³" for k, v in aire["polen"].items())
        st.markdown(f'<div class="card"><b>🌬 Calidad del aire: {aire["nivel"]}</b> <span class="muted">(índice europeo {aire["aqi"]})</span>'
                    f'{f"<br>🌼 Polen — {polen}" if polen else ""}</div>', unsafe_allow_html=True)
    if E["servicios"] is None:
        st.warning("No pudimos consultar los servicios cercanos (sin conexión con OpenStreetMap). Si es urgente, llama al 112.")
        return
    for clave, (etiqueta, icono, radio, _) in TIPOS_EMERG.items():
        items = E["servicios"].get(clave, [])
        filas = "".join(
            f'<div class="stop"><div class="info"><b>{html.escape(x["nombre"])}</b><span class="cat">a {x["distancia_m"]} m · '
            f'<a href="https://www.google.com/maps/dir/?api=1&travelmode=walking&destination={x["lat"]},{x["lon"]}" target="_blank" rel="noopener">Cómo llegar ↗</a></span></div></div>'
            for x in items) or f'<div class="muted">Nada registrado a menos de {radio} m.</div>'
        st.markdown(f'<div class="card"><b>{icono} {etiqueta}</b>{filas}</div>', unsafe_allow_html=True)


def pestana_ajustes(registro, indice):
    perfil = S.get("perfil", "tranquilo")
    st.subheader("Simulación del clima (demo)")
    st.selectbox("Clima", ["Clima real", "Lluvia", "Calor (34 °C)", "Frío (3 °C)", "Personalizado"], key="sim_clima",
                 help="Para probar la app en una demo. Vuelve a pulsar «Crear paseo» después de cambiarlo.")
    if S.get("sim_clima") == "Personalizado":
        a, b, c = st.columns(3)
        a.slider("Temperatura (°C)", -5, 45, 22, key="sim_temp")
        b.slider("Lluvia (mm/h)", 0.0, 10.0, 0.0, step=0.5, key="sim_lluvia")
        c.slider("Índice UV", 0, 12, 3, key="sim_uv")
    st.caption(f'Umbrales: calor ≥ {UMBRALES["calor"]:.0f} °C · frío < {UMBRALES["frio"]:.0f} °C · UV ≥ {UMBRALES["uv"]} · '
               f'lluvia > {UMBRALES["lluvia"]} mm/h. Lluvia o refugio pedido ⇒ techo obligatorio; calor/frío/UV ⇒ el refugio pesa más.')
    st.subheader(f'Pesos de los criterios · perfil {PERFILES[perfil]["etiqueta"]}')
    cols = st.columns(len(CRITERIOS_AHP))
    for col, c in zip(cols, CRITERIOS_AHP):
        col.slider(ETIQUETAS[c], 0, 10, int(PESOS_PERFIL[perfil][c]), key=f"peso_{perfil}_{c}")
    st.caption("Los criterios fijos (desnivel y pendientes) los marca el perfil. Se aplican al crear el siguiente paseo.")
    with st.expander("Cómo funciona"):
        st.markdown(
            "**Puntuación (1-100)** = media geométrica ponderada de 7 criterios: sombra (densidad de arbolado ponderada por altura a ≤ 25 m de la ruta), "
            "refugio con techo, fuentes, lugares de interés, ajuste al tiempo pedido, desnivel y pendientes.\n\n"
            "**Paradas**: de 1 a 3 según la duración. Se prefiltran combinaciones con geometría rápida y solo las mejores se trazan con el servicio de rutas.\n\n"
            "**Limitaciones**: los horarios de museos, bibliotecas y centros culturales son *orientativos* (los feeds oficiales no los traen estructurados) "
            "y los festivos pueden cambiarlos; el monte de la Casa de Campo solo tiene arbolado inventariado en zonas ajardinadas.")
    with st.expander("Datos cargados"):
        d = estado_datos(registro, indice)
        st.write(d["pois_por_categoria"])
        st.write("Arbolado:", d["arbolado"])
    st.subheader("Privacidad")
    st.caption("Favoritos e historial se guardan solo en tu navegador (localStorage); no hay cuentas ni servidor.")
    if st.button("Borrar mis favoritos e historial", key="borrar_todo"):
        storage.borrar_todo()
        st.success("Datos borrados.")


# =====================================================================
#  EJECUCIÓN
# =====================================================================
pantalla_acceso()
st.markdown(estilos(bool(S.get("texto_grande"))), unsafe_allow_html=True)
storage.hidratar()

registro = construir_registro_pois()
pois = calcular_abierto_ahora(registro, ahora_madrid())
indice = cargar_indice_arbolado()
clima, simulado = clima_efectivo(cargar_clima())
flags = evaluar_clima(clima.get("temp"), clima.get("lluvia"), clima.get("uv"))
S["clima_txt"] = texto_clima(clima, simulado)

st.markdown(cabecera_html(S["clima_txt"]), unsafe_allow_html=True)
st.markdown(alertas_clima_html(flags, clima.get("ok", False), bool(S.get("refugio_manual"))), unsafe_allow_html=True)
if registro.empty:
    st.error("No se han cargado los puntos de interés: revisa que la carpeta data/ contenga los ficheros .geo y fuentes.json.")
    st.stop()
if indice is None:
    st.warning("No encuentro los datos de arbolado (data/arbolado_malla.npz o data/arbolado.csv): la sombra se valora con un valor neutro.")

col_plan, col_res = st.columns([1, 1.7], gap="large")
with col_plan:
    panel_planificador(pois, indice, flags)
with col_res:
    columna_resultado(pois, indice)

t_guardados, t_emergencias, t_ajustes = st.tabs(["⭐ Guardados", "🚨 Emergencias", "⚙️ Ajustes"])
with t_guardados:
    pestana_guardados(pois, indice, flags)
with t_emergencias:
    pestana_emergencias()
with t_ajustes:
    pestana_ajustes(registro, indice)
st.caption("Datos: Ayuntamiento de Madrid (datos.madrid.es) · OpenStreetMap · OpenRouteService · Open-Meteo. "
           "Horarios orientativos; ante una emergencia llama al 112.")

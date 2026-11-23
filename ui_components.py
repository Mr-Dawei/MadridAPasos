# -*- coding: utf-8 -*-
"""Componentes de interfaz: estilos, tarjetas, mapa, modo paseo en vivo, compartir y voz."""
import html
import json
import urllib.parse

import numpy as np

from config import APP_NAME, APP_TAGLINE, CATEGORIAS, UMBRALES
from geo_utils import texto_estado
from scoring import ETIQUETAS

AZUL, VERDE = "#0A84FF", "#1E9E6A"
TILES = "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
TILES_ATTR = "© OpenStreetMap · © CARTO"
LEAFLET_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"
LEAFLET_JS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"


def _e(x):
    return html.escape(str(x), quote=True)


def _num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def _json_seguro(obj):
    """JSON para incrustar dentro de <script>: < > & se escapan como \\uXXXX (válido en JSON y JS), así ni </script> ni <!--
    ni <script dentro de un nombre pueden alterar el HTML."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# =====================================================================
#  CSS
# =====================================================================
CSS = f"""
<style>
:root {{
  --azul:{AZUL}; --verde:{VERDE}; --verde-bg:#E7F6EF; --ambar:#B45309; --ambar-bg:#FFF4E5; --rojo:#D92D20;
  --tinta:#1C1C1E; --tinta2:#6B6F76; --linea:#E6E8EB; --fondo:#F4F5F7; --radio:20px;
  --sombra:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.07);
}}
html, body, [class*="st-"], .stApp {{
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
}}
.stApp {{ background:var(--fondo); color:var(--tinta); }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{ display:none !important; }}
header[data-testid="stHeader"] {{ background:transparent; height:0; }}
.block-container {{ max-width:1180px; padding-top:1.1rem; padding-bottom:4rem; }}
h1,h2,h3 {{ letter-spacing:-.02em; }}

/* Botones: grandes, redondeados, ancho completo (también en móvil) */
.stButton>button, .stDownloadButton>button, [data-testid^="stBaseLinkButton"], [data-testid="stLinkButton"] a {{
  border-radius:14px !important; min-height:3rem; font-weight:600; width:100%; border:1px solid var(--linea);
  box-shadow:0 1px 2px rgba(16,24,40,.04);
}}
.stButton>button[kind="primary"] {{ background:var(--azul); border-color:var(--azul); color:#fff; }}
.stButton>button[kind="primary"]:hover {{ background:#0066CC; border-color:#0066CC; }}
button[data-baseweb="tab"] {{ font-weight:600; font-size:1rem; }}
[data-testid="stExpander"] {{ background:#fff; border-radius:var(--radio); border:1px solid var(--linea); box-shadow:var(--sombra); }}
[data-testid="stExpander"] summary {{ font-weight:700; font-size:1.05rem; }}

/* Cabecera */
.top {{ display:flex; justify-content:space-between; align-items:center; gap:.75rem; margin:.2rem 0 .9rem; flex-wrap:wrap; }}
.brand {{ font-size:1.7rem; font-weight:800; letter-spacing:-.03em; }}
.brand span {{ color:var(--verde); }}
.tag {{ color:var(--tinta2); font-size:.95rem; margin-top:-.15rem; }}
.wx {{ background:#fff; border:1px solid var(--linea); border-radius:999px; padding:.45rem .95rem; font-weight:600; box-shadow:var(--sombra); }}

/* Tarjetas */
.card {{ background:#fff; border-radius:var(--radio); padding:1.1rem 1.2rem; box-shadow:var(--sombra); margin-bottom:.9rem; }}
.hero .etq {{ color:var(--azul); font-weight:700; font-size:.85rem; text-transform:uppercase; letter-spacing:.06em; }}
.hero .big {{ font-size:2.6rem; font-weight:800; letter-spacing:-.04em; line-height:1.1; margin:.15rem 0 .5rem; }}
.hero .big small {{ font-size:1.2rem; font-weight:600; color:var(--tinta2); }}
.hero .big span {{ font-size:1.3rem; font-weight:600; color:var(--tinta2); }}
.hero .why {{ margin-top:.6rem; color:#3A3F47; }}
.hero .vs {{ margin-top:.5rem; background:var(--verde-bg); color:#0B6B47; border-radius:12px; padding:.5rem .75rem; font-weight:600; }}
.chips {{ display:flex; flex-wrap:wrap; gap:.4rem; }}
.chip {{ background:#EEF1F4; color:#2B3036; border-radius:999px; padding:.3rem .75rem; font-weight:600; font-size:.9rem; }}
.chip.ok {{ background:var(--verde-bg); color:#0B6B47; }}
.chip.info {{ background:#E6F1FF; color:#0A5BC4; }}
.chip.warn {{ background:var(--ambar-bg); color:var(--ambar); }}
.stop {{ display:flex; gap:.8rem; align-items:flex-start; padding:.7rem 0; border-bottom:1px solid var(--linea); }}
.stop:last-child {{ border-bottom:0; }}
.stop .num {{ flex:0 0 2rem; height:2rem; border-radius:50%; background:var(--azul); color:#fff; font-weight:700;
              display:flex; align-items:center; justify-content:center; }}
.stop .info {{ display:flex; flex-direction:column; gap:.1rem; }}
.stop .cat, .muted {{ color:var(--tinta2); font-size:.9rem; }}
.stop .est {{ font-size:.9rem; font-weight:600; }} .est.ok {{ color:#0B6B47; }} .est.no {{ color:var(--rojo); }}
.stop a {{ color:var(--azul); font-size:.9rem; text-decoration:none; }}
.alerta {{ border-radius:16px; padding:.7rem 1rem; margin-bottom:.6rem; font-weight:600; }}
.alerta.lluvia {{ background:#E6F1FF; color:#0A5BC4; }} .alerta.calor {{ background:var(--ambar-bg); color:var(--ambar); }}
.alerta.frio {{ background:#EDEBFE; color:#4C3FB5; }} .alerta.aviso {{ background:#FEF3F2; color:#B42318; }}
.bar {{ display:flex; align-items:center; gap:.6rem; margin:.35rem 0; }}
.bar span {{ flex:0 0 9.5rem; font-size:.92rem; }}
.bar div {{ flex:1; background:#E9ECEF; border-radius:99px; height:.6rem; overflow:hidden; }}
.bar i {{ display:block; height:100%; background:var(--verde); border-radius:99px; }}
.bar b {{ flex:0 0 2.2rem; text-align:right; font-size:.9rem; }}
.vacio {{ text-align:center; padding:2.2rem 1rem; color:var(--tinta2); }}
.vacio .ico {{ font-size:3rem; }}
.sos {{ display:block; text-align:center; background:var(--rojo); color:#fff !important; font-weight:800; font-size:1.3rem;
        border-radius:16px; padding:.95rem; text-decoration:none; box-shadow:var(--sombra); margin-bottom:.8rem; }}
iframe {{ border-radius:var(--radio); }}

@media (max-width: 640px) {{
  .block-container {{ padding:.8rem .7rem 4rem; }}
  .brand {{ font-size:1.45rem; }} .hero .big {{ font-size:2.2rem; }} .bar span {{ flex-basis:7.5rem; }}
}}
</style>
"""


def estilos(texto_grande=False):
    extra = "<style>html{font-size:118% !important}.stButton>button{font-size:1.1rem}</style>" if texto_grande else ""
    return CSS + extra


# =====================================================================
#  HTML de tarjetas
# =====================================================================
def cabecera_html(clima_txt):
    wx = f'<div class="wx">{_e(clima_txt)}</div>' if clima_txt else ""
    return (f'<div class="top"><div><div class="brand">🌳 {_e(APP_NAME)}</div>'
            f'<div class="tag">{_e(APP_TAGLINE)}</div></div>{wx}</div>')


def texto_clima(clima, simulado=False):
    if not clima or clima.get("temp") is None:
        return "Clima no disponible"
    extra = f" · UV {clima['uv']:.0f}" if clima.get("uv") else ""
    lluvia = " · 🌧 lluvia" if clima.get("lluvia") and clima["lluvia"] > UMBRALES["lluvia"] else ""
    return f"{'🧪 ' if simulado else ''}{clima['temp']:.0f} °C{extra}{lluvia}"


def alertas_clima_html(flags, clima_ok, refugio_manual=False):
    out = []
    if flags.get("lluvia"):
        out.append('<div class="alerta lluvia">🌧 Llueve: tu paseo pasará sí o sí por un sitio con techo abierto.</div>')
    if flags.get("calor") or flags.get("uv"):
        out.append('<div class="alerta calor">☀️ Calor o sol fuerte: damos más peso a la sombra, las fuentes y los sitios con techo. '
                   'Bebe agua y evita las horas centrales.</div>')
    if flags.get("frio"):
        out.append('<div class="alerta frio">🥶 Hace frío: damos más peso a los sitios con techo.</div>')
    if refugio_manual and not flags.get("lluvia"):
        out.append('<div class="alerta lluvia">☂️ Has pedido techo: el paseo pasará por un sitio cubierto abierto.</div>')
    if not clima_ok:
        out.append('<div class="alerta aviso">No hemos podido leer el clima: calculamos con condiciones normales.</div>')
    return "".join(out)


def tarjeta_resumen_html(opcion, base=None):
    ev, m = opcion["evaluacion"], opcion["evaluacion"]["metricas"]
    chips = []
    if m["pct_sombra"] is not None:
        chips.append(f'<span class="chip ok">🌳 {m["pct_sombra"] * 100:.0f} % con sombra</span>')
    n = len(opcion["paradas"])
    chips.append(f'<span class="chip info">📍 {n} parada{"s" if n != 1 else ""}</span>')
    if m["n_fuentes"]:
        chips.append(f'<span class="chip info">⛲ {m["n_fuentes"]} fuente{"s" if m["n_fuentes"] != 1 else ""}</span>')
    if m["n_techo_parada"]:
        chips.append('<span class="chip ok">☂️ Con refugio</span>')
    if m["ascenso_m"] is not None:
        chips.append(f'<span class="chip">⛰ {m["ascenso_m"]:.0f} m de desnivel</span>')
    if opcion["ruta"].fuente == "linea":
        chips.append('<span class="chip warn">Ruta aproximada (sin conexión)</span>')
    vs = ""
    if base is not None and base["evaluacion"]["metricas"]["pct_sombra"] is not None and m["pct_sombra"] is not None:
        dp = (m["pct_sombra"] - base["evaluacion"]["metricas"]["pct_sombra"]) * 100
        dmin = opcion["minutos"] - base["minutos"]
        if dp >= 1:
            vs = f'<div class="vs">+{dp:.0f} puntos de sombra respecto a la ruta directa ({"+" if dmin >= 0 else ""}{dmin} min)</div>'
    ok = "" if ev["pasa_filtros"] else f'<div class="alerta aviso">⚠️ {_e(ev["motivo_filtro"])}</div>'
    return (f'<div class="card hero"><div class="etq">{_e(opcion["etiqueta"])} · puntuación {ev["score"]:.0f}/100</div>'
            f'<div class="big">{opcion["minutos"]} <small>min</small> <span>· {_num(opcion["km"])} km</span></div>'
            f'<div class="chips">{"".join(chips)}</div><div class="why">{_e(ev["explicacion"])}</div>{vs}{ok}</div>')


def paradas_html(paradas):
    if not paradas:
        return '<div class="card muted">Esta ruta no incluye paradas.</div>'
    filas = []
    for i, p in enumerate(paradas, 1):
        cfg = CATEGORIAS.get(p["categoria"], {})
        estado = texto_estado(p["abierto_ahora"], p["cierra_min"] if p["cierra_min"] is not None else 0, p["horario_fuente"])
        clase = "ok" if p["abierto_ahora"] else "no"
        enlace = f' · <a href="{_e(p["url"])}" target="_blank" rel="noopener">Horario oficial ↗</a>' if p.get("url") else ""
        techo = " · ☂️ Refugio" if p.get("refugio_ok") else ""
        filas.append(f'<div class="stop"><div class="num">{i}</div><div class="info"><b>{_e(p["nombre"])}</b>'
                     f'<span class="cat">{cfg.get("icono", "")} {_e(cfg.get("etiqueta", p["categoria"]))}{techo}</span>'
                     f'<span class="est {clase}">{_e(estado)}{enlace}</span></div></div>')
    nota = '<div class="muted" style="margin-top:.4rem">Los horarios son orientativos; los festivos pueden cambiarlos.</div>'
    return f'<div class="card">{"".join(filas)}{nota}</div>'


def criterios_html(evaluacion):
    filas = []
    for c, d in evaluacion["criterios"].items():
        filas.append(f'<div class="bar"><span>{_e(ETIQUETAS[c])} <span class="muted">({d["peso"] * 100:.0f} %)</span></span>'
                     f'<div><i style="width:{d["valor"] * 100:.0f}%"></i></div><b>{d["valor"] * 100:.0f}</b></div>')
    return f'<div class="card">{"".join(filas)}</div>'


def _dist_txt(m):
    return f"{_num(m / 1000, 2)} km" if m >= 1000 else f"{m:.0f} m"


def pasos_html(pasos):
    if not pasos:
        return '<div class="card muted">Sin indicaciones paso a paso.</div>'
    filas = [f'<div class="stop"><div class="num">{i}</div><div class="info"><b>{_e(p["texto"])}</b>'
             f'<span class="cat">{_dist_txt(p["distancia_m"])}</span></div></div>' for i, p in enumerate(pasos, 1)]
    return f'<div class="card">{"".join(filas)}</div>'


def vacio_html(texto):
    return f'<div class="card vacio"><div class="ico">🌿</div><div>{_e(texto)}</div></div>'


# =====================================================================
#  MAPA (folium)
# =====================================================================
def _pin(n, color=AZUL):
    return (f'<div style="width:34px;height:34px;border-radius:50%;background:{color};color:#fff;font-weight:700;'
            f'display:flex;align-items:center;justify-content:center;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.35)">{n}</div>')


def construir_mapa(centro, opcion=None, origen=None, destino=None, pois=None, indice=None, mostrar_sombra=False, radio_m=1500):
    import folium
    from folium.plugins import Fullscreen, HeatMap

    m = folium.Map(location=list(centro), zoom_start=15, tiles=None, control_scale=True, prefer_canvas=True)
    folium.TileLayer(tiles=TILES, attr=TILES_ATTR, name="Mapa", subdomains="abcd", max_zoom=19).add_to(m)
    Fullscreen().add_to(m)
    capas = False

    if mostrar_sombra and indice is not None:
        la, lo, w = indice.celdas_en_radio(centro[0], centro[1], radio_m)
        if len(w):
            w = np.clip(w / 12.0, 0, 1)
            HeatMap([[float(a), float(b), float(c)] for a, b, c in zip(la, lo, w)], name="Sombra (arbolado)", radius=14, blur=20,
                    min_opacity=0.25, gradient={0.3: "#D9F0D3", 0.6: "#74C476", 1.0: "#006D2C"}).add_to(m)
            capas = True
    if pois is not None and len(pois):
        for cat, grupo in pois.groupby("categoria"):
            cfg = CATEGORIAS[cat]
            fg = folium.FeatureGroup(name=f'{cfg["icono"]} {cfg["etiqueta"]}', show=True)
            for _, r in grupo.head(500).iterrows():
                folium.CircleMarker([r["lat"], r["lon"]], radius=5, color="#fff", weight=1.5, fill=True, fill_color=cfg["color"],
                                    fill_opacity=0.95, tooltip=r["nombre"]).add_to(fg)
            fg.add_to(m)
            capas = True

    if opcion is not None:
        pts = [(c[1], c[0]) for c in opcion["ruta"].coords]
        folium.PolyLine(pts, color="#FFFFFF", weight=11, opacity=1).add_to(m)
        folium.PolyLine(pts, color=AZUL, weight=6, opacity=0.95, tooltip=f'{opcion["minutos"]} min · {_num(opcion["km"])} km').add_to(m)
        for i, p in enumerate(opcion["paradas"], 1):
            cfg = CATEGORIAS.get(p["categoria"], {})
            pop = f'<b>{_e(p["nombre"])}</b><br>{_e(cfg.get("etiqueta", ""))}'
            folium.Marker([p["lat"], p["lon"]], tooltip=p["nombre"], popup=folium.Popup(pop, max_width=240),
                          icon=folium.DivIcon(html=_pin(i), icon_size=(34, 34), icon_anchor=(17, 17))).add_to(m)
        lats, lons = [q[0] for q in pts], [q[1] for q in pts]
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(30, 30))
    if origen is not None:
        folium.Marker(list(origen), tooltip="Salida",
                      icon=folium.DivIcon(html='<div style="width:20px;height:20px;border-radius:50%;background:#0A84FF;border:4px solid #fff;'
                                               'box-shadow:0 0 0 6px rgba(10,132,255,.25)"></div>', icon_size=(20, 20), icon_anchor=(10, 10))).add_to(m)
    if destino is not None:
        folium.Marker(list(destino), tooltip="Destino", icon=folium.DivIcon(html=_pin("B", "#1C1C1E"), icon_size=(34, 34), icon_anchor=(17, 17))).add_to(m)
    if capas:
        folium.LayerControl(collapsed=True).add_to(m)
    return m


# =====================================================================
#  MODO PASEO EN VIVO (Leaflet + GPS dentro del mismo iframe)
# =====================================================================
def _simplificar(pts, min_m=3.0):
    """Quita vértices a menos de min_m del anterior (la ruta pesa mucho menos y se ve igual)."""
    if len(pts) < 3:
        return pts
    out, ult = [pts[0]], pts[0]
    for p in pts[1:-1]:
        if abs(p[0] - ult[0]) * 111000 + abs(p[1] - ult[1]) * 85000 >= min_m:
            out.append(p); ult = p
    out.append(pts[-1])
    return out


NAV_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="__LEAFLET_CSS__"><script src="__LEAFLET_JS__"></script>
<style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;color:#1C1C1E}
#m{height:__ALTO_MAPA__px;border-radius:18px 18px 0 0}
#panel{background:#fff;border-radius:0 0 18px 18px;padding:12px 14px 14px;box-shadow:0 8px 24px rgba(16,24,40,.10)}
#paso{font-size:1.15rem;font-weight:700;line-height:1.25;min-height:2.6rem}
.barra{height:12px;background:#E9ECEF;border-radius:99px;overflow:hidden;margin:10px 0 6px}
#pb{height:100%;width:0;background:#1E9E6A;border-radius:99px;transition:width .4s}
.fila{display:flex;justify-content:space-between;color:#6B6F76;font-size:.92rem;gap:8px;flex-wrap:wrap}
#aviso{color:#B42318;font-weight:600;min-height:1.2rem;font-size:.92rem}
.btns{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
button{flex:1;min-width:120px;border:0;border-radius:14px;padding:13px 10px;font-size:1rem;font-weight:700;cursor:pointer;background:#EEF1F4;color:#1C1C1E}
button.pri{background:#0A84FF;color:#fff}
.pin{width:32px;height:32px;border-radius:50%;background:#0A84FF;color:#fff;font-weight:700;display:flex;align-items:center;justify-content:center;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.35)}
</style></head><body>
<div id="m"></div>
<div id="panel">
  <div id="paso">Pulsa «Empezar» para seguir tu ubicación</div>
  <div class="barra"><div id="pb"></div></div>
  <div class="fila"><span id="rec">0,00 km</span><b id="pct">0 %</b><span id="quedan"></span></div>
  <div id="aviso"></div>
  <div class="btns"><button class="pri" id="go">▶ Empezar con GPS</button><button id="sim">Simular paseo</button><button id="voz">🔊 Voz: no</button></div>
</div>
<script>
const R = __DATOS__;
const rad = Math.PI / 180, $ = id => document.getElementById(id);
function dist(a, b) { const x = (b[1] - a[1]) * rad * Math.cos((a[0] + b[0]) * rad / 2), y = (b[0] - a[0]) * rad; return 6371000 * Math.hypot(x, y); }
const pts = R.pts, cum = [0];
for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + dist(pts[i - 1], pts[i]));
const total = cum[cum.length - 1];
let prog = 0, seg = 0, primera = true, watchId = null, simId = null, voz = false, ultimo = -1, wl = null;

const map = L.map('m').setView(pts[0], 16);
L.tileLayer('__TILES__', {subdomains: 'abcd', maxZoom: 19, attribution: '__ATTR__'}).addTo(map);
const rest = L.polyline(pts, {color: '#0A84FF', weight: 7, opacity: .95}).addTo(map);
const done = L.polyline([], {color: '#9AA3AD', weight: 7, opacity: .95}).addTo(map);
R.paradas.forEach(p => L.marker([p.lat, p.lon], {icon: L.divIcon({className: '', html: '<div class="pin">' + p.n + '</div>', iconSize: [32, 32], iconAnchor: [16, 16]})}).bindPopup(p.nombre).addTo(map));
const yo = L.circleMarker(pts[0], {radius: 9, color: '#fff', weight: 3, fillColor: '#0A84FF', fillOpacity: 1}).addTo(map);
map.fitBounds(rest.getBounds(), {padding: [24, 24]});

function proyectar(p, desde, ventana) {          // punto del recorrido más cercano a p (proyección sobre segmentos)
  let best = {d: 1e12, s: desde, m: cum[desde]};
  const kx = Math.cos(p[0] * rad) * 111320, ky = 110540;
  for (let i = desde; i < pts.length - 1; i++) {
    if (cum[i] - cum[desde] > ventana) break;
    const ax = (pts[i][1] - p[1]) * kx, ay = (pts[i][0] - p[0]) * ky, bx = (pts[i + 1][1] - p[1]) * kx, by = (pts[i + 1][0] - p[0]) * ky;
    const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
    const t = l2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2)) : 0;
    const d = Math.hypot(ax + t * dx, ay + t * dy);
    if (d < best.d) best = {d: d, s: i, m: cum[i] + t * (cum[i + 1] - cum[i])};
  }
  return best;
}
function puntoEn(m) {
  let i = 0; while (i < pts.length - 2 && cum[i + 1] < m) i++;
  const t = (m - cum[i]) / Math.max(1e-6, cum[i + 1] - cum[i]);
  return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t, i];
}
const fmt = (x, d) => x.toFixed(d).replace('.', ',');
function hablar(t) {
  if (!('speechSynthesis' in window)) return;
  speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(t); u.lang = 'es-ES'; u.rate = .95; speechSynthesis.speak(u);
}
function pintar(fuera) {
  const q = puntoEn(prog), i = q[2];
  done.setLatLngs(pts.slice(0, i + 1).concat([[q[0], q[1]]]));
  rest.setLatLngs([[q[0], q[1]]].concat(pts.slice(i + 1)));
  const f = Math.min(1, prog / total);
  $('pb').style.width = (f * 100) + '%'; $('pct').textContent = Math.round(f * 100) + ' %';
  $('rec').textContent = fmt(prog / 1000, 2) + ' km de ' + fmt(total / 1000, 2) + ' km';
  $('quedan').textContent = 'quedan ' + Math.max(0, Math.round((total - prog) / R.ritmo)) + ' min';
  let k = 0; for (let j = 0; j < R.pasos.length; j++) if (R.pasos[j].ini <= prog) k = j;
  $('paso').textContent = R.pasos.length ? R.pasos[k].t : '';
  if (k !== ultimo) { ultimo = k; if (voz && R.pasos.length) hablar(R.pasos[k].t); }
  $('aviso').textContent = fuera > 70 ? 'Estás a ' + Math.round(fuera) + ' m de la ruta' : '';
  if (total - prog < 25) fin();
}
function onPos(lat, lon) {
  const p = [lat, lon]; yo.setLatLng(p);
  const r = primera ? proyectar(p, 0, 1e9) : proyectar(p, seg, 600);   // 1ª vez: toda la ruta; luego, ventana hacia delante
  if (r.d <= 70) { if (r.m >= prog) { prog = r.m; seg = r.s; } primera = false; }
  pintar(r.d);
}
function detener() {
  if (watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
  if (simId !== null) { clearInterval(simId); simId = null; }
  if (wl) { try { wl.release(); } catch (e) {} wl = null; }
}
function fin() {
  detener(); $('paso').textContent = '¡Paseo completado! Buen trabajo 🎉'; $('aviso').textContent = '';
  if (navigator.vibrate) navigator.vibrate(300); if (voz) hablar('Paseo completado. Buen trabajo.');
}
function reiniciar() { detener(); prog = 0; seg = 0; primera = true; ultimo = -1; done.setLatLngs([]); rest.setLatLngs(pts); }
$('go').onclick = async () => {
  reiniciar();
  if (!navigator.geolocation) { $('aviso').textContent = 'Tu navegador no ofrece GPS: usa «Simular paseo».'; return; }
  watchId = navigator.geolocation.watchPosition(x => onPos(x.coords.latitude, x.coords.longitude),
    e => { $('aviso').textContent = 'No puedo ver tu ubicación (' + e.message + '). Activa el permiso o usa «Simular».'; },
    {enableHighAccuracy: true, maximumAge: 2000, timeout: 20000});
  try { if ('wakeLock' in navigator) wl = await navigator.wakeLock.request('screen'); } catch (e) {}
  $('paso').textContent = 'Buscando tu ubicación…';
};
$('sim').onclick = () => {
  reiniciar(); let m = 0;
  simId = setInterval(() => { m = Math.min(total, m + 22); const q = puntoEn(m); onPos(q[0], q[1]); if (m >= total) detener(); }, 350);
};
$('voz').onclick = () => { voz = !voz; $('voz').textContent = '🔊 Voz: ' + (voz ? 'sí' : 'no'); if (voz) hablar('Voz activada'); };
</script></body></html>"""


def html_navegacion(opcion, ritmo_m_min, alto_mapa=430):
    """HTML autónomo (Leaflet + GPS): pinta de gris lo recorrido y avanza según tu ubicación. Determinista:
    si Streamlit vuelve a ejecutar el script con la misma ruta, el iframe no se reinicia."""
    pts = _simplificar([[round(c[1], 6), round(c[0], 6)] for c in opcion["ruta"].coords])
    datos = {"pts": pts, "ritmo": ritmo_m_min,
             "paradas": [{"n": i, "nombre": p["nombre"], "lat": p["lat"], "lon": p["lon"]} for i, p in enumerate(opcion["paradas"], 1)],
             "pasos": [{"t": p["texto"], "ini": round(p["inicio_m"], 1)} for p in opcion["ruta"].pasos]}
    return (NAV_HTML.replace("__DATOS__", _json_seguro(datos)).replace("__LEAFLET_CSS__", LEAFLET_CSS)
            .replace("__LEAFLET_JS__", LEAFLET_JS).replace("__TILES__", TILES).replace("__ATTR__", TILES_ATTR)
            .replace("__ALTO_MAPA__", str(alto_mapa)))


# =====================================================================
#  COMPARTIR Y VOZ
# =====================================================================
def urls_compartir(opcion, origen, destino):
    fin = destino or origen
    via = [(p["lat"], p["lon"]) for p in opcion["paradas"]]
    gmaps = ("https://www.google.com/maps/dir/?api=1&travelmode=walking"
             f"&origin={origen[0]},{origen[1]}&destination={fin[0]},{fin[1]}"
             + (f"&waypoints={urllib.parse.quote('|'.join(f'{a},{b}' for a, b in via))}" if via else ""))
    amaps = (f"https://maps.apple.com/?dirflg=w&saddr={origen[0]},{origen[1]}&daddr="
             + "+to:".join(f"{a},{b}" for a, b in via + [fin]))
    paradas = ", ".join(p["nombre"] for p in opcion["paradas"]) or "sin paradas"
    texto = f'Mi paseo con {APP_NAME}: {opcion["minutos"]} min · {_num(opcion["km"])} km, paso por {paradas}. {gmaps}'
    return {"google": gmaps, "apple": amaps, "whatsapp": "https://wa.me/?text=" + urllib.parse.quote(texto)}


def texto_para_voz(opcion):
    pasos = ". ".join(p["texto"] for p in opcion["ruta"].pasos[:12])
    paradas = ", ".join(p["nombre"] for p in opcion["paradas"]) or "ninguna"
    return (f'Paseo de {opcion["minutos"]} minutos y {_num(opcion["km"])} kilómetros. Paradas: {paradas}. '
            f'{opcion["evaluacion"]["explicacion"].replace("%", " por ciento")}. Indicaciones: {pasos}.')


def html_boton_voz(texto):
    """Botón de voz DENTRO del iframe: los navegadores exigen un gesto del usuario en el mismo marco."""
    return ('<button id="b" style="width:100%;min-height:48px;border:1px solid #E6E8EB;border-radius:14px;background:#fff;'
            'font:600 1rem -apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer">🔊 Leer en voz alta</button>'
            f'<script>const T={_json_seguro(texto)};const b=document.getElementById("b");'
            'b.onclick=()=>{if(!("speechSynthesis" in window)){b.textContent="Tu navegador no admite voz";return}'
            'speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(T);u.lang="es-ES";u.rate=.95;speechSynthesis.speak(u)};</script>')

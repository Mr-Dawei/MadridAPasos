# -*- coding: utf-8 -*-
"""PDF imprimible del paseo (fpdf2): resumen, mapa esquemático dibujado, paradas e indicaciones.

El mapa se dibuja con líneas (no descarga teselas): funciona sin conexión y no depende de terceros.
Las fuentes base de PDF solo admiten latin-1, así que se limpian emojis y signos fuera de ese juego.
"""
import math
import re
from datetime import datetime

from config import APP_NAME, APP_TAGLINE, CATEGORIAS, PERFILES
from geo_utils import texto_estado

AZUL, VERDE, TINTA, GRIS = (10, 132, 255), (30, 158, 106), (28, 28, 30), (107, 111, 118)


def _t(s):
    s = str(s).replace("→", "->").replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[^\x00-\xFF]", "", s).strip()


def _num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def _dibujar_mapa(pdf, opcion, origen, destino, x0, y0, w, h):
    pts = [(c[1], c[0]) for c in opcion["ruta"].coords]
    extra = [origen] + ([destino] if destino else []) + [(p["lat"], p["lon"]) for p in opcion["paradas"]]
    lats = [p[0] for p in pts + extra]
    lons = [p[1] for p in pts + extra]
    lat0, lat1, lon0, lon1 = min(lats), max(lats), min(lons), max(lons)
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    ancho, alto = max((lon1 - lon0) * kx, 1e-9), max(lat1 - lat0, 1e-9)
    esc = min((w - 10) / ancho, (h - 10) / alto)
    ox, oy = x0 + (w - ancho * esc) / 2, y0 + (h - alto * esc) / 2

    def xy(lat, lon):
        return ox + (lon - lon0) * kx * esc, oy + (lat1 - lat) * esc

    pdf.set_fill_color(244, 245, 247)
    pdf.set_draw_color(230, 232, 235)
    pdf.rect(x0, y0, w, h, style="DF")
    pdf.set_draw_color(*AZUL)
    pdf.set_line_width(0.9)
    for a, b in zip(pts, pts[1:]):
        (xa, ya), (xb, yb) = xy(*a), xy(*b)
        pdf.line(xa, ya, xb, yb)

    def marca(lat, lon, texto, color):
        x, y = xy(lat, lon)
        pdf.set_fill_color(*color)
        pdf.set_draw_color(255, 255, 255)
        pdf.set_line_width(0.5)
        pdf.ellipse(x - 3.2, y - 3.2, 6.4, 6.4, style="DF")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 7)
        pdf.text(x - 0.9 * len(texto), y + 1.0, texto)

    marca(origen[0], origen[1], "S", TINTA)
    if destino:
        marca(destino[0], destino[1], "B", TINTA)
    for i, p in enumerate(opcion["paradas"], 1):
        marca(p["lat"], p["lon"], str(i), AZUL)
    pdf.set_text_color(*GRIS)
    pdf.set_font("Helvetica", "", 7)
    pdf.text(x0 + 2, y0 + h - 2, "Mapa esquematico (Norte arriba). S = salida")


def generar_pdf(opcion, origen, destino, perfil, nombre_origen, nombre_destino, clima_txt=""):
    """Devuelve los bytes del PDF. Lanza ImportError si fpdf2 no está instalado."""
    from fpdf import FPDF

    ev, m = opcion["evaluacion"], opcion["evaluacion"]["metricas"]
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    pdf.set_text_color(*TINTA)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 10, _t(APP_NAME), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 6, _t(APP_TAGLINE), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_text_color(*TINTA)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _t(f'Tu paseo: {opcion["minutos"]} min - {_num(opcion["km"])} km'), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    destino_txt = "Paseo circular" if destino is None else f"Hasta {nombre_destino}"
    pdf.multi_cell(0, 5.5, _t(f'Perfil {PERFILES[perfil]["etiqueta"]}. Sale de {nombre_origen}. {destino_txt}. '
                            f'{datetime.now():%d/%m/%Y %H:%M}. {clima_txt}'), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*VERDE)
    pdf.set_font("Helvetica", "B", 10)
    sombra = f' - {m["pct_sombra"] * 100:.0f} % del recorrido con sombra' if m["pct_sombra"] is not None else ""
    pdf.multi_cell(0, 6, _t(f'Puntuacion {ev["score"]:.0f}/100{sombra}. {ev["explicacion"]}'), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    _dibujar_mapa(pdf, opcion, origen, destino, 15, pdf.get_y(), 180, 92)
    pdf.set_y(pdf.get_y() + 96)

    pdf.set_text_color(*TINTA)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Paradas", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for i, p in enumerate(opcion["paradas"], 1):
        cat = CATEGORIAS.get(p["categoria"], {}).get("etiqueta", p["categoria"])
        estado = texto_estado(p["abierto_ahora"], p["cierra_min"] or 0, p["horario_fuente"])
        pdf.multi_cell(0, 5.5, _t(f'{i}. {p["nombre"]} ({cat}). {estado}.'), new_x="LMARGIN", new_y="NEXT")
    if opcion["paradas"]:
        pdf.set_text_color(*GRIS)
        pdf.set_font("Helvetica", "I", 8)
        pdf.multi_cell(0, 4.5, "Horarios orientativos: confirmalos en madrid.es antes de ir (los festivos pueden cambiarlos).",
                       new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_text_color(*TINTA)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Indicaciones", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for i, s in enumerate(opcion["ruta"].pasos[:60], 1):
        d = f'{s["distancia_m"] / 1000:.2f} km'.replace(".", ",") if s["distancia_m"] >= 1000 else f'{s["distancia_m"]:.0f} m'
        pdf.multi_cell(0, 5.5, _t(f'{i}. {s["texto"]} ({d})'), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_text_color(185, 28, 28)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Emergencias: 112", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())

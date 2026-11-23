import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import _setup  # noqa: F401
import datos_sinteticos as ds
import emergencias as em
import planner as pl
import scoring as sc
import ui_components as ui


class TestEmergencias(unittest.TestCase):
    def test_parseo_y_orden_por_distancia(self):
        d = {"elements": [{"lat": 40.4172, "lon": -3.7040, "tags": {"amenity": "pharmacy", "name": "Farmacia Sol"}},
                          {"lat": 40.4300, "lon": -3.7000, "tags": {"amenity": "pharmacy", "name": "Farmacia Lejos"}},
                          {"center": {"lat": 40.42, "lon": -3.70}, "tags": {"amenity": "hospital", "name": "Hospital X"}},
                          {"lat": 40.4170, "lon": -3.7036, "tags": {"emergency": "defibrillator"}},
                          {"lat": 40.9, "lon": -3.7, "tags": {"amenity": "toilets"}}]}
        r = em.parsear_overpass(d, 40.4169, -3.7035)
        self.assertEqual([x["nombre"] for x in r["farmacia"]], ["Farmacia Sol", "Farmacia Lejos"])
        self.assertEqual(r["salud"][0]["nombre"], "Hospital X")
        self.assertEqual(r["dea"][0]["nombre"], "Desfibrilador (DEA)")
        self.assertEqual(r["aseos"], [])                                    # fuera del radio de búsqueda

    def test_niveles_de_calidad_del_aire(self):
        self.assertEqual((em.nivel_aqi(20), em.nivel_aqi(21), em.nivel_aqi(150)), ("Buena", "Razonable", "Extremadamente mala"))


class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = pl.planificar((ds.LAT0, ds.LON0), None, 25, "tranquilo", ds.registro(), ds.indice(), sc.pesos_por_perfil("tranquilo"),
                          ds.SIN_CLIMA, router=ds.router_falso)
        cls.op = r["opciones"][0]

    def test_se_escapa_el_html_de_los_nombres(self):
        op = dict(self.op, paradas=[dict(self.op["paradas"][0], nombre="<script>alert(1)</script>")])
        h = ui.paradas_html(op["paradas"])
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;script&gt;", h)

    def test_el_json_del_modo_paseo_no_puede_cerrar_el_script(self):
        op = dict(self.op, paradas=[dict(self.op["paradas"][0], nombre="</script><script>alert(1)")])
        h = ui.html_navegacion(op, 55)
        self.assertNotIn("<script>alert", h)
        self.assertEqual(h.count("</script>"), 2)                  # solo las etiquetas de Leaflet y del propio script
        self.assertIn("\\u003c/script\\u003e", h)

    def test_enlaces_para_compartir_incluyen_las_paradas(self):
        u = ui.urls_compartir(self.op, (ds.LAT0, ds.LON0), None)
        self.assertIn("waypoints=", u["google"])
        self.assertIn("+to:", u["apple"])
        self.assertTrue(u["whatsapp"].startswith("https://wa.me/?text="))

    def test_la_tarjeta_muestra_el_aviso_si_no_pasa_filtros(self):
        ev = dict(self.op["evaluacion"], pasa_filtros=False, motivo_filtro="Motivo de prueba")
        self.assertIn("Motivo de prueba", ui.tarjeta_resumen_html(dict(self.op, evaluacion=ev)))

    @unittest.skipUnless(shutil.which("node"), "node no está instalado")
    def test_progreso_del_modo_paseo_con_gps_simulado(self):
        h = ui.html_navegacion(self.op, 55)
        js = re.findall(r"<script>(.*?)</script>", h, re.S)[-1]
        prueba = """
const els={}; const st=()=>({style:{},textContent:'',onclick:null});
global.document={getElementById:id=>els[id]||(els[id]=st())}; global.navigator={}; global.window={};
const ch=()=>{const o={addTo:()=>o,bindPopup:()=>o,setLatLngs:()=>o,setLatLng:()=>o,getBounds:()=>({}),setView:()=>o,fitBounds:()=>o};return o};
global.L={map:ch,tileLayer:ch,polyline:ch,marker:ch,circleMarker:ch,divIcon:()=>({})};
let tick=null; global.setInterval=f=>{tick=f;return 1}; global.clearInterval=()=>{tick=null};
""" + js + """
els['sim'].onclick(); let n=0, ant=-1, monotono=true;
while(tick && n<2000){tick(); n++; const p=parseInt(els['pct'].textContent); if(p<ant) monotono=false; ant=p}
console.log(JSON.stringify({monotono, final:els['paso'].textContent.includes('completado')}));"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(prueba)
        salida = subprocess.run(["node", f.name], capture_output=True, text=True)
        self.assertEqual(json.loads(salida.stdout), {"monotono": True, "final": True}, salida.stderr)


if __name__ == "__main__":
    unittest.main()

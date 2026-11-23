import unittest

import _setup  # noqa: F401
import datos_sinteticos as ds
import planner as pl
import scoring as sc

ORIGEN = (ds.LAT0, ds.LON0)


def planificar(ahora=ds.MARTES_11, destino=None, dur=45, perfil="tranquilo", flags=ds.SIN_CLIMA, manual=False, cats=None):
    return pl.planificar(ORIGEN, destino, dur, perfil, ds.registro(ahora), ds.indice(), sc.pesos_por_perfil(perfil), flags, manual, cats,
                         router=ds.router_falso)


class TestPlanner(unittest.TestCase):
    def test_circular_respeta_el_tiempo_pedido(self):
        r = planificar(dur=45)
        self.assertTrue(r["opciones"])
        for o in r["opciones"]:
            self.assertLessEqual(abs(o["minutos"] - 45), 0.30 * 45, o["minutos"])

    def test_numero_de_paradas_segun_la_duracion(self):
        self.assertEqual(pl.n_paradas_por_duracion(25), 1)
        self.assertEqual(pl.n_paradas_por_duracion(45), 2)
        self.assertEqual(pl.n_paradas_por_duracion(90), 3)
        self.assertEqual(len(planificar(dur=25)["opciones"][0]["paradas"]), 1)
        self.assertEqual(len(planificar(dur=45)["opciones"][0]["paradas"]), 2)

    def test_lluvia_obliga_a_pasar_por_un_sitio_con_techo(self):
        r = planificar(flags={**ds.SIN_CLIMA, "lluvia": True}, cats=["parques", "monumentos"])
        self.assertTrue(r["opciones"])
        for o in r["opciones"]:                                   # 100 % de las opciones, aunque el usuario no pidiera museos
            self.assertTrue(any(p["refugio_ok"] for p in o["paradas"]))
            self.assertTrue(o["evaluacion"]["pasa_filtros"])

    def test_refugio_pedido_por_el_usuario_tambien_es_obligatorio(self):
        r = planificar(manual=True)
        self.assertTrue(all(any(p["refugio_ok"] for p in o["paradas"]) for o in r["opciones"]))

    def test_calor_no_obliga_pero_pondera(self):
        r = planificar(flags={**ds.SIN_CLIMA, "calor": True})
        self.assertTrue(r["opciones"])
        self.assertGreater(r["meta"]["pesos"]["refugio"], sc.pesos_por_perfil("tranquilo")["refugio"])

    def test_los_lunes_no_se_manda_a_museos_cerrados(self):
        r = planificar(ds.LUNES_11, flags={**ds.SIN_CLIMA, "lluvia": True})
        nombres = {p["nombre"] for o in r["opciones"] for p in o["paradas"]}
        self.assertFalse({n for n in nombres if n.startswith("Museo")})
        self.assertTrue(r["opciones"])                            # pero sí hay refugio: biblioteca o centro cultural

    def test_si_no_hay_nada_abierto_avisa_con_claridad(self):
        r = planificar(ds.MARTES_23, flags={**ds.SIN_CLIMA, "lluvia": True})
        self.assertEqual(r["opciones"], [])
        self.assertIn("no hay ningún", " ".join(r["avisos"]))

    def test_prefiere_la_zona_con_arboles(self):
        mejor = planificar(dur=45)["opciones"][0]                 # solo el este tiene árboles: el mejor paseo debe ir por allí
        self.assertGreater(mejor["evaluacion"]["metricas"]["pct_sombra"], 0.5)
        self.assertTrue(any(p["lon"] > ds.LON0 for p in mejor["paradas"]))

    def test_a_b_incluye_ruta_directa_y_paradas_dentro_del_tiempo(self):
        destino = (ds.LAT0 + 0.003, ds.LON0 + 0.012)
        r = planificar(destino=destino, dur=60)
        self.assertIsNotNone(r["base"])                           # para comparar "con paradas" frente a "directa"
        self.assertTrue(r["opciones"])
        mejor = r["opciones"][0]
        self.assertGreaterEqual(len(mejor["paradas"]), 1)         # en A→B siempre hay al menos un sitio de interés
        self.assertLessEqual(mejor["minutos"], 60 * 1.3)

    def test_las_alternativas_no_repiten_paradas(self):
        r = planificar(dur=45)
        conjuntos = [frozenset(p["nombre"] for p in o["paradas"]) for o in r["opciones"]]
        self.assertEqual(len(conjuntos), len(set(conjuntos)))

    def test_repetir_un_paseo_guardado(self):
        r = planificar(dur=25)
        o = r["opciones"][0]
        item = {"perfil": "tranquilo", "origen": list(ORIGEN), "destino": None, "km": o["km"], "paradas": o["paradas"],
                "waypoints": [list(w) for w in o["waypoints"]]}
        rr = pl.reconstruir_paseo(item, ds.registro(), ds.indice(), ds.SIN_CLIMA, router=ds.router_falso)
        self.assertEqual(len(rr["opciones"][0]["waypoints"]), len(o["waypoints"]))


if __name__ == "__main__":
    unittest.main()

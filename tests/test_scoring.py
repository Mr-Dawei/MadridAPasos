import unittest

import numpy as np

import _setup  # noqa: F401
import datos_sinteticos as ds
import scoring as sc

CATS = ["parques", "monumentos", "museos", "bibliotecas", "centros_culturales"]


def linea(a, b, n=40):
    return [[lo, la] for la, lo in zip(np.linspace(a[0], b[0], n), np.linspace(a[1], b[1], n))]


class TestScoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = sc.construir_contexto(ds.registro(), ds.indice(), CATS)
        cls.w = sc.pesos_por_perfil("tranquilo")
        # mismo trazado de 600 m, uno al este (bosque) y otro al oeste (sin árboles)
        cls.este = linea((ds.LAT0, ds.LON0 + 0.0095), (ds.LAT0 + 0.005, ds.LON0 + 0.0095))
        cls.oeste = linea((ds.LAT0, ds.LON0 - 0.0095), (ds.LAT0 + 0.005, ds.LON0 - 0.0095))

    def test_la_sombra_discrimina(self):
        a = sc.evaluar_ruta(self.este, self.ctx, [], self.w, "tranquilo")
        b = sc.evaluar_ruta(self.oeste, self.ctx, [], self.w, "tranquilo")
        self.assertGreater(a["criterios"]["sombra"]["valor"], 0.9)
        self.assertLess(b["criterios"]["sombra"]["valor"], 0.1)
        self.assertGreater(a["score"], b["score"])               # antes ambas saturaban la sombra al mismo valor

    def test_score_acotado_y_pesos_normalizados(self):
        r = sc.evaluar_ruta(self.este, self.ctx, [], self.w, "tranquilo")
        self.assertTrue(1.0 <= r["score"] <= 100.0)              # antes: ~1e50 por no normalizar los pesos
        self.assertAlmostEqual(sum(c["peso"] for c in r["criterios"].values()), 1.0, delta=0.01)

    def test_cada_fuente_cuenta_una_sola_vez(self):
        # una ruta larga que pasa junto a UNA fuente: antes se contaba una vez por cada punto de muestreo cercano
        larga = linea((ds.LAT0 - 0.0005, ds.LON0 + 0.0035), (ds.LAT0 + 0.0005, ds.LON0 + 0.0059), n=60)   # pasa junto a 'Fuente 1'
        r = sc.evaluar_ruta(larga, self.ctx, [], self.w, "tranquilo")
        self.assertEqual(r["metricas"]["n_fuentes"], 1)

    def test_regla_dura_de_refugio(self):
        sin = sc.evaluar_ruta(self.este, self.ctx, [], self.w, "tranquilo", refugio_obligatorio=True)
        con = sc.evaluar_ruta(self.este, self.ctx, [{"nombre": "M", "categoria": "museos", "refugio_ok": True}], self.w, "tranquilo",
                              refugio_obligatorio=True)
        self.assertFalse(sin["pasa_filtros"])
        self.assertTrue(con["pasa_filtros"])

    def test_movilidad_reducida_limita_el_desnivel(self):
        w = sc.pesos_por_perfil("movilidad_reducida")
        self.assertFalse(sc.evaluar_ruta(self.este, self.ctx, [], w, "movilidad_reducida", ascenso_m=45)["pasa_filtros"])
        self.assertTrue(sc.evaluar_ruta(self.este, self.ctx, [], w, "movilidad_reducida", ascenso_m=10)["pasa_filtros"])

    def test_sin_datos_de_altimetria_el_valor_es_neutro(self):
        r = sc.evaluar_ruta(self.este, self.ctx, [], self.w, "tranquilo")
        self.assertEqual(r["criterios"]["desnivel"]["valor"], 0.6)
        self.assertEqual(r["criterios"]["accesibilidad"]["valor"], 0.6)

    def test_el_clima_sube_el_peso_del_refugio(self):
        base = sc.ajustar_pesos_clima(self.w, {})
        for bandera in ("calor", "frio", "lluvia"):
            self.assertGreater(sc.ajustar_pesos_clima(self.w, {bandera: True})["refugio"], base["refugio"])
        self.assertGreater(sc.ajustar_pesos_clima(self.w, {"calor": True})["sombra"], base["sombra"])

    def test_sin_indice_de_arbolado_no_falla(self):
        ctx = sc.construir_contexto(ds.registro(), None, CATS)
        r = sc.evaluar_ruta(self.este, ctx, [], self.w, "tranquilo")
        self.assertIsNone(r["metricas"]["pct_sombra"])


if __name__ == "__main__":
    unittest.main()

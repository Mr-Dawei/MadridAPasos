import os
import tempfile
import unittest

import numpy as np

import _setup  # noqa: F401
from spatial import CUANT, IndiceArbolado


class TestSpatial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(3)
        cls.x, cls.y = 440000 + rng.uniform(0, 600, 5000), 4474000 + rng.uniform(0, 600, 5000)
        cls.w = rng.uniform(0.2, 2.0, 5000)
        cls.ix = IndiceArbolado.desde_puntos(cls.x, cls.y, cls.w)

    def test_coincide_con_fuerza_bruta(self):
        for px, py in [(440300, 4474300), (440100, 4474500), (440550, 4474050)]:
            cx, cy = np.floor((px - self.ix.x0) / 10), np.floor((py - self.ix.y0) / 10)
            xs, ys = np.floor((self.x - self.ix.x0) / 10), np.floor((self.y - self.ix.y0) / 10)
            bruto = self.w[(np.abs(xs - cx) <= 2) & (np.abs(ys - cy) <= 2)].sum()
            self.assertAlmostEqual(self.ix.densidad_xy(px, py, 25)[0], bruto, delta=25 * 0.5 / CUANT + 0.01)

    def test_fuera_de_la_malla_es_cero_y_no_falla(self):
        self.assertEqual(self.ix.densidad_xy([0.0, 9e6], [0.0, 9e6], 25).sum(), 0.0)

    def test_guardar_y_cargar(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "m.npz")
            self.ix.guardar(ruta)
            otro = IndiceArbolado.cargar(ruta)
        self.assertAlmostEqual(otro.peso_total, self.ix.peso_total, places=6)
        self.assertEqual(otro.densidad_xy(440300, 4474300, 25)[0], self.ix.densidad_xy(440300, 4474300, 25)[0])

    def test_celdas_para_mapa_de_calor(self):
        la, lo, w = self.ix.celdas_en_radio(40.4177, -3.7035, 500)
        self.assertEqual(len(la), len(lo))
        self.assertGreater(len(w), 0)
        self.assertTrue((w > 0).all())


if __name__ == "__main__":
    unittest.main()

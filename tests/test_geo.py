import unittest

import numpy as np
import pandas as pd

import _setup  # noqa: F401
import datos_sinteticos as ds
import geo_utils as g


class TestGeo(unittest.TestCase):
    def test_utm_ida_y_vuelta(self):
        lat, lon = np.array([40.4169, 40.45, 40.38]), np.array([-3.7035, -3.60, -3.80])
        la, lo = g.utm_a_latlon(*g.latlon_a_utm(lat, lon))
        self.assertLess(float(np.max(np.hypot((la - lat) * 111000, (lo - lon) * 85000))), 0.01)       # < 1 cm

    def test_umbral_de_calor_es_28_en_cualquier_mes(self):
        self.assertTrue(g.evaluar_clima(28.0, 0, 0)["calor"])
        self.assertFalse(g.evaluar_clima(27.9, 0, 0)["calor"])
        self.assertTrue(g.evaluar_clima(32.0, 0, 0)["calor"])              # el septiembre a 32 °C ya no pasa desapercibido

    def test_frio_lluvia_uv_y_datos_ausentes(self):
        self.assertTrue(g.evaluar_clima(7.9, 0, 0)["frio"])
        self.assertTrue(g.evaluar_clima(20, 1.5, 0)["lluvia"])
        self.assertFalse(g.evaluar_clima(20, 1.0, 0)["lluvia"])
        self.assertTrue(g.evaluar_clima(20, 0, 6.5)["uv"])
        self.assertFalse(any(v for k, v in g.evaluar_clima(None, None, None).items()))

    def test_horarios_por_dia_de_la_semana(self):
        r = ds.registro(ds.LUNES_11)
        self.assertFalse(r[r.categoria == "museos"].abierto_ahora.any())                # lunes: museos cerrados
        self.assertTrue(r[r.categoria == "bibliotecas"].abierto_ahora.all())
        martes_noche = ds.registro(pd.Timestamp("2026-11-24 20:30"))
        self.assertFalse(martes_noche[martes_noche.categoria == "museos"].abierto_ahora.any())   # 19:00 − 75 min de margen
        domingo_tarde = ds.registro(pd.Timestamp("2026-11-22 16:00"))
        self.assertFalse(domingo_tarde[domingo_tarde.categoria == "bibliotecas"].abierto_ahora.any())  # fin de semana: cierran 15:00
        self.assertTrue(domingo_tarde[domingo_tarde.categoria == "museos"].abierto_ahora.all())

    def test_lo_exterior_siempre_esta_accesible(self):
        r = ds.registro(pd.Timestamp("2026-11-24 03:00"))
        self.assertTrue(r[r.categoria.isin(["parques", "monumentos", "fuentes"])].abierto_ahora.all())

    def test_parseo_de_horario_explicito(self):
        self.assertEqual(g.parsear_horario_texto("Horario: de lunes a domingo, de 7:30 a 21:45 horas"), (450, 1305))
        self.assertEqual(g.parsear_horario_texto("Horarios, información y reservas"), (None, None))

    def test_hora_local_de_madrid_es_naive(self):
        self.assertIsNone(g.ahora_madrid().tzinfo)


if __name__ == "__main__":
    unittest.main()

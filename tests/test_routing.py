import unittest
from unittest import mock

import _setup  # noqa: F401
import routing as r

A, B = (40.4169, -3.7035), (40.4199, -3.6887)


def respuesta(datos, status=200):
    m = mock.Mock(status_code=status)
    m.json.return_value = datos
    m.raise_for_status = lambda: None
    return m


ORS = {"features": [{"geometry": {"coordinates": [[-3.7035, 40.4169, 650.0], [-3.7000, 40.4180, 660.0], [-3.6887, 40.4199, 672.0]]},
                     "properties": {"summary": {"distance": 1500.0}, "ascent": 27.0, "descent": 5.0,
                                    "segments": [{"steps": [{"instruction": "Camina hacia el este", "distance": 900.0},
                                                            {"instruction": "Llegas a tu destino", "distance": 600.0}]}]}}]}
OSRM = {"routes": [{"distance": 1500.0, "geometry": {"coordinates": [[-3.7035, 40.4169], [-3.6887, 40.4199]]},
                    "legs": [{"steps": [{"distance": 900, "name": "Calle Mayor", "maneuver": {"type": "depart"}},
                                        {"distance": 100, "name": "", "maneuver": {"type": "turn", "modifier": "left"}},
                                        {"distance": 500, "name": "", "maneuver": {"type": "arrive"}}]}]}]}


class TestRouting(unittest.TestCase):
    def setUp(self):
        r.limpiar_cache()

    def test_ors_con_clave_trae_pasos_y_desnivel(self):
        with mock.patch("routing.requests.post", return_value=respuesta(ORS)):
            ruta = r.calcular_ruta([A, B], clave_ors="clave-de-prueba")
        self.assertEqual((ruta.fuente, ruta.km, ruta.ascenso_m), ("ors", 1.5, 27.0))
        self.assertEqual([p["inicio_m"] for p in ruta.pasos], [0.0, 900.0])            # inicio acumulado de cada paso

    def test_sin_clave_usa_fossgis_con_instrucciones_en_espanol(self):
        with mock.patch("routing.requests.get", return_value=respuesta(OSRM)):
            ruta = r.calcular_ruta([A, B], clave_ors="")
        self.assertEqual(ruta.fuente, "fossgis")
        self.assertEqual(ruta.pasos[0]["texto"], "Empieza a caminar por Calle Mayor")
        self.assertEqual(ruta.pasos[1]["texto"], "Gira a la izquierda")
        self.assertEqual(ruta.pasos[-1]["texto"], "Has llegado a tu destino")

    def test_sin_red_cae_a_linea_recta_sin_duplicar_la_distancia(self):
        with mock.patch("routing.requests.get", side_effect=OSError), mock.patch("routing.requests.post", side_effect=OSError):
            ruta = r.calcular_ruta([A, B], clave_ors="x")
        self.assertEqual(ruta.fuente, "linea")
        self.assertAlmostEqual(ruta.km, 1.30 * 1.3, delta=0.05)    # antes (sin parada) salía el doble
        self.assertTrue(ruta.avisos)

    def test_los_avisos_nunca_contienen_la_clave(self):
        with mock.patch("routing.requests.post", side_effect=OSError("fallo SECRETA")), mock.patch("routing.requests.get", side_effect=OSError("x")):
            ruta = r.calcular_ruta([A, B], clave_ors="SECRETA")
        self.assertFalse(any("SECRETA" in a for a in ruta.avisos))

    def test_la_linea_recta_no_se_cachea_para_poder_reintentar(self):
        with mock.patch("routing.requests.get", side_effect=OSError), mock.patch("routing.requests.post", side_effect=OSError):
            r.calcular_ruta([A, B], clave_ors="")
        with mock.patch("routing.requests.get", return_value=respuesta(OSRM)):
            self.assertEqual(r.calcular_ruta([A, B], clave_ors="").fuente, "fossgis")

    def test_perfil_altimetrico(self):
        coords = [[-3.7035 + 0.0003 * i, 40.4169, 650.0 + 2 * i] for i in range(40)]        # subida constante
        asc, desc, frac = r.perfil_altimetrico(coords)
        self.assertGreater(asc, 40)
        self.assertEqual(round(desc), 0)
        self.assertEqual(r.perfil_altimetrico([[-3.7, 40.4], [-3.69, 40.41]]), (None, None, None))

    def test_geocodificar(self):
        photon = {"features": [{"properties": {"name": "Plaza Mayor", "district": "Centro", "city": "Madrid"},
                                "geometry": {"coordinates": [-3.7074, 40.4155]}}]}
        with mock.patch("routing.requests.get", return_value=respuesta(photon)):
            res = r.geocodificar("plaza mayor")
        self.assertEqual(res[0]["nombre"], "Plaza Mayor, Centro, Madrid")
        self.assertEqual(r.geocodificar("ab"), [])


if __name__ == "__main__":
    unittest.main()

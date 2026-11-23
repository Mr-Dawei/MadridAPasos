import os
import subprocess
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(os.path.isdir(os.path.join(RAIZ, "data")), "falta la carpeta data/")
class TestAppSmoke(unittest.TestCase):
    def test_la_app_arranca_y_recorre_los_flujos_principales(self):
        r = subprocess.run([sys.executable, os.path.join(RAIZ, "tests", "smoke_app.py")], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-1500:])
        self.assertIn("SMOKE OK", r.stdout)


if __name__ == "__main__":
    unittest.main()

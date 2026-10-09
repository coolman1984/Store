"""The Windows build ships every file the program reads at run time (tools/build_windows.py).

1.2.0 added guide/ and two JSON files beside server/*.py but the build still copied only web/ and licence_keys.txt,
so the compiled program could not start. These checks run on any OS, without Nuitka.
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

import harness  # noqa: F401  (puts server/ on sys.path)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import build_windows  # noqa: E402


class Manifest(unittest.TestCase):
    def setUp(self):
        self.files = dict(build_windows.runtime_files())

    def test_every_non_python_file_beside_the_server_ships_at_the_top_of_the_program_folder(self):
        server = os.path.join(ROOT, 'server')
        for name in os.listdir(server):
            if os.path.isfile(os.path.join(server, name)) and not name.endswith(('.py', '.pyc')):
                self.assertEqual(self.files.get('server/' + name), name, name)

    def test_every_guide_and_web_file_ships_under_its_own_folder(self):
        for top in ('guide', 'web'):
            for folder, dirs, names in os.walk(os.path.join(ROOT, top)):
                dirs[:] = [d for d in dirs if d not in ('__pycache__', '_dev')]
                for name in names:
                    rel = os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, '/')
                    self.assertEqual(self.files.get(rel), rel, rel)
        for must in ('guide/catalogue.json', 'guide/ar.json', 'guide/en.json', 'web/index.html', 'licence_keys.txt', 'licence_relay.txt'):
            self.assertIn(must, self.files)
            self.assertIn(must, build_windows.SHIPPED)

    def test_nuitka_flags_cover_the_whole_manifest(self):
        args = build_windows.nuitka_data_args()
        dirs = {a.split('=', 1)[1].split('=')[0] for a in args if a.startswith('--include-data-dir=')}
        files = {a.split('=', 1)[1].split('=')[0] for a in args if a.startswith('--include-data-files=')}
        for src in self.files:
            self.assertTrue(src.split('/')[0] in dirs or src in files, src)

    def test_a_program_folder_laid_out_from_the_manifest_finds_its_data(self):
        """Lay files out as app.dist and load the vendored modules from there, as the compiled program does."""
        dist = tempfile.mkdtemp(prefix='store-dist-')
        self.addCleanup(shutil.rmtree, dist, True)
        for src, dest in self.files.items():
            os.makedirs(os.path.dirname(os.path.join(dist, dest)) or dist, exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, src), os.path.join(dist, dest))
        for module in ('afguide', 'aftelemetry'):
            shutil.copyfile(os.path.join(ROOT, 'server', module + '.py'), os.path.join(dist, module + '.py'))

        def load(name):
            spec = importlib.util.spec_from_file_location('dist_' + name, os.path.join(dist, name + '.py'))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        guide = load('afguide')
        self.assertTrue(str(guide.STYLE).startswith(dist) and os.path.isfile(guide.STYLE), guide.STYLE)
        catalogue, texts = guide.load_dir(os.path.join(dist, 'guide'))
        self.assertTrue(catalogue['guides'] and texts['ar'])
        self.assertIsNotNone(load('aftelemetry')._taxonomy())


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(harness.HAVE_CRYPTO, 'cryptography needed to sign the run-only licence code')
class Journey(unittest.TestCase):
    """tools/journey_exe.py is what the Windows workflow runs on the installed program before and after the update;
    here it runs on the source so a broken journey is caught on every push, not only on Windows."""

    def test_real_shop_journey_survives_a_restart_of_the_program(self):
        import subprocess
        home = tempfile.mkdtemp(prefix='store-journey-')
        try:
            tool = os.path.join(ROOT, 'tools', 'journey_exe.py')
            app = [sys.executable, os.path.join(ROOT, 'server', 'app.py')]
            for phase in ('first', 'after'):
                r = subprocess.run([sys.executable, tool, phase, home, *app], capture_output=True, text=True, timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn('OK ' + phase, r.stdout)
        finally:
            shutil.rmtree(home, ignore_errors=True)

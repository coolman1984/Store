"""The Windows build ships every file the program reads at run time (tools/build_windows.py).

1.2.0 added guide/ and two JSON files beside server/*.py but the build still copied only web/ and licence_keys.txt,
so the compiled program could not start. These checks run on any OS, without Nuitka.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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


class CustomerRelease(unittest.TestCase):
    SAMPLE_KEY = 'trial-release:' + ('A' * 43)
    SAMPLE_RELAY = 'https://relay.example.com'

    def _env_without_release_secrets(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ('STORE_RELEASE_PUBLIC_KEY', 'STORE_RELEASE_RELAY_URL')}
        env.update(extra)
        return env

    def _run_customer_check(self, **env_extra):
        return subprocess.run(
            [sys.executable, 'tools/build_windows.py', '--check', '--customer'],
            cwd=ROOT, capture_output=True, text=True,
            env=self._env_without_release_secrets(**env_extra),
        )

    def test_check_passes_on_template_files(self):
        r = subprocess.run([sys.executable, 'tools/build_windows.py', '--check'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(build_windows.VERSION, r.stdout)

    def test_customer_check_accepts_a_public_key_and_https_relay(self):
        with tempfile.TemporaryDirectory(prefix='store-customer-') as tmp:
            with open(os.path.join(tmp, 'licence_keys.txt'), 'w', encoding='utf-8') as f:
                f.write(self.SAMPLE_KEY + '\n')
            with open(os.path.join(tmp, 'licence_relay.txt'), 'w', encoding='utf-8') as f:
                f.write(self.SAMPLE_RELAY + '\n')
            with mock.patch.dict(os.environ, self._env_without_release_secrets(), clear=True):
                keys, relay = build_windows.resolve_customer_licence(tmp)
            self.assertEqual(keys.strip(), self.SAMPLE_KEY)
            self.assertEqual(relay.strip(), self.SAMPLE_RELAY)
        r = self._run_customer_check(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
                                     STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_exits_nonzero_for_empty_templates_without_release_env(self):
        r = self._run_customer_check()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_exits_nonzero_when_only_one_release_secret_is_set(self):
        r = self._run_customer_check(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self._run_customer_check(STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_exits_nonzero_for_http_relay_in_release_env(self):
        r = self._run_customer_check(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
                                     STORE_RELEASE_RELAY_URL='http://relay.example.com')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_reads_release_environment_variables(self):
        env = {k: v for k, v in os.environ.items() if k not in ('STORE_RELEASE_PUBLIC_KEY', 'STORE_RELEASE_RELAY_URL')}
        env['STORE_RELEASE_PUBLIC_KEY'] = self.SAMPLE_KEY
        env['STORE_RELEASE_RELAY_URL'] = self.SAMPLE_RELAY
        with mock.patch.dict(os.environ, env, clear=True):
            keys, relay = build_windows.resolve_customer_licence()
        self.assertEqual(keys.strip(), self.SAMPLE_KEY)
        self.assertEqual(relay.strip(), self.SAMPLE_RELAY)

    def test_customer_check_rejects_bad_inputs(self):
        pem = '-----BEGIN ' + 'PRIVATE KEY-----'
        with self.assertRaises(build_windows.CustomerLicenceError):
            build_windows.validate_public_key_line(pem)
        with self.assertRaises(build_windows.CustomerLicenceError):
            build_windows.validate_relay_line('http://relay.example.com')
        with self.assertRaises(build_windows.CustomerLicenceError):
            build_windows.validate_relay_line(self.SAMPLE_RELAY + '?token=abc')
    def test_relay_strict_allowlist_rejects_review_cases(self):
        reject = (
            'https://relay.example.com/eyjhbgci-oijiuzi1nij9',
            'https://relay.example.com/eyjh-bgci/payl-oad/sig-ab12',
            'https://relay.example.com/' + ('a' * 16),
            'https://eyjhbccioijiuzi1nij9.payload.sig.relay.example.com',
            'https://relay.example.com/eyJhbGciOiJIUzI1NiJ9.payload.sig',
            self.SAMPLE_RELAY + '/not-allowed',
        )
        for url in reject:
            with self.assertRaises(build_windows.CustomerLicenceError, msg=url):
                build_windows.validate_relay_line(url)

    def test_relay_host_rejects_ip_literals_punycode_hyphen_tricks_and_bad_suffix(self):
        reject = (
            ('https://192.168.1.10', 'ipv4'),
            ('https://[2001:db8::1]', 'ipv6'),
            ('https://-relay.example.com', 'leading hyphen'),
            ('https://relay-.example.com', 'trailing hyphen'),
            ('https://re--lay.example.com', 'double hyphen'),
            ('https://xn--badlabel.example.com', 'punycode'),
            ('https://relay.notallowed.com', 'suffix'),
            ('https://eyjhbccioijiuzi1nij9.example.com', 'jwt-like subdomain'),
        )
        for url, _why in reject:
            with self.assertRaises(build_windows.CustomerLicenceError, msg=url):
                build_windows.validate_relay_line(url)

    def test_relay_strict_allowlist_accepts_configured_paths(self):
        for url in (
            self.SAMPLE_RELAY,
            self.SAMPLE_RELAY + '/licence-hub',
            self.SAMPLE_RELAY + '/api',
            'https://licence-hub.workers.dev',
            'https://al-store-relay2.workers.dev',
        ):
            build_windows.validate_relay_line(url)

    def test_release_proof_customer_cli_uses_validated_relay(self):
        env = self._env_without_release_secrets(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
                                                 STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY)
        r = subprocess.run([sys.executable, 'tools/build_windows.py', '--release-proof-customer'],
                           cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(),
                         list(build_windows.release_proof_licence_lines(True, self.SAMPLE_RELAY)))

    def test_customer_mode_refuses_template_files_in_the_repo(self):
        env = {k: v for k, v in os.environ.items() if k not in ('STORE_RELEASE_PUBLIC_KEY', 'STORE_RELEASE_RELAY_URL')}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(build_windows.CustomerLicenceError):
                build_windows.resolve_customer_licence(ROOT)

    def test_release_proof_marks_factory_and_customer_builds(self):
        self.assertEqual(build_windows.release_proof_licence_lines(False), ('customer_licence: no',))
        lines = build_windows.release_proof_licence_lines(True, self.SAMPLE_RELAY)
        self.assertEqual(lines[0], 'customer_licence: yes')
        self.assertEqual(lines[1], 'relay_host: relay.example.com')


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

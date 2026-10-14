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
    SAMPLE_KEY = 'trial-hub:' + ('A' * 43)
    SAMPLE_STUDIO_KEY = 'studio:' + ('B' * 43)
    SAMPLE_HOST = 'relay.test.invalid'
    SAMPLE_RELAY = 'https://' + SAMPLE_HOST

    def _env_without_release_secrets(self, **extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ('STORE_RELEASE_PUBLIC_KEY', 'STORE_RELEASE_RELAY_URL', 'STORE_RELEASE_ALLOWED_RELAY_HOSTS')}
        env.setdefault('STORE_RELEASE_ALLOWED_RELAY_HOSTS', self.SAMPLE_HOST)
        env.update(extra)
        return env

    def _allowed_hosts(self, *hosts):
        return {h.lower() for h in hosts}

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

    def test_shipped_relay_hosts_file_lists_no_active_hostnames(self):
        cleaned = {k: v for k, v in os.environ.items() if k != 'STORE_RELEASE_ALLOWED_RELAY_HOSTS'}
        with mock.patch.dict(os.environ, cleaned, clear=True):
            self.assertEqual(build_windows.allowed_relay_hosts(), set())

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

    def test_customer_build_accepts_trial_hub_and_studio_key_lines(self):
        lines = (self.SAMPLE_KEY, self.SAMPLE_STUDIO_KEY)
        with tempfile.TemporaryDirectory(prefix='store-customer-') as tmp:
            with open(os.path.join(tmp, 'licence_keys.txt'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
            with open(os.path.join(tmp, 'licence_relay.txt'), 'w', encoding='utf-8') as f:
                f.write(self.SAMPLE_RELAY + '\n')
            with mock.patch.dict(os.environ, self._env_without_release_secrets(), clear=True):
                keys, relay = build_windows.resolve_customer_licence(tmp)
            self.assertEqual(keys.strip().splitlines(), list(lines))
        env_keys = '\n'.join(lines)
        with mock.patch.dict(os.environ, self._env_without_release_secrets(
            STORE_RELEASE_PUBLIC_KEY=env_keys,
            STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY,
        ), clear=True):
            keys, relay = build_windows.resolve_customer_licence()
        self.assertEqual(keys.strip().splitlines(), list(lines))

    def test_customer_build_rejects_missing_trial_hub_or_bad_kids(self):
        with tempfile.TemporaryDirectory(prefix='store-customer-') as tmp:
            with open(os.path.join(tmp, 'licence_relay.txt'), 'w', encoding='utf-8') as f:
                f.write(self.SAMPLE_RELAY + '\n')
            with mock.patch.dict(os.environ, self._env_without_release_secrets(), clear=True):
                with open(os.path.join(tmp, 'licence_keys.txt'), 'w', encoding='utf-8') as f:
                    f.write(self.SAMPLE_STUDIO_KEY + '\n')
                with self.assertRaises(build_windows.CustomerLicenceError):
                    build_windows.resolve_customer_licence(tmp)
                with open(os.path.join(tmp, 'licence_keys.txt'), 'w', encoding='utf-8') as f:
                    f.write('trial-release:' + ('C' * 43) + '\n')
                with self.assertRaises(build_windows.CustomerLicenceError):
                    build_windows.resolve_customer_licence(tmp)
                with open(os.path.join(tmp, 'licence_keys.txt'), 'w', encoding='utf-8') as f:
                    f.write('\n'.join((self.SAMPLE_KEY, self.SAMPLE_KEY)) + '\n')
                with self.assertRaises(build_windows.CustomerLicenceError):
                    build_windows.resolve_customer_licence(tmp)
                with open(os.path.join(tmp, 'licence_keys.txt'), 'w', encoding='utf-8') as f:
                    f.write('\n'.join((self.SAMPLE_KEY, self.SAMPLE_STUDIO_KEY, self.SAMPLE_STUDIO_KEY)) + '\n')
                with self.assertRaises(build_windows.CustomerLicenceError):
                    build_windows.resolve_customer_licence(tmp)
        r = self._run_customer_check(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
                                     STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_exits_nonzero_for_empty_templates_without_release_env(self):
        env = self._env_without_release_secrets(STORE_RELEASE_ALLOWED_RELAY_HOSTS=self.SAMPLE_HOST)
        env.pop('STORE_RELEASE_PUBLIC_KEY', None)
        env.pop('STORE_RELEASE_RELAY_URL', None)
        r = subprocess.run(
            [sys.executable, 'tools/build_windows.py', '--check', '--customer'],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_exits_nonzero_when_only_one_release_secret_is_set(self):
        r = self._run_customer_check(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
                                     STORE_RELEASE_ALLOWED_RELAY_HOSTS=self.SAMPLE_HOST)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self._run_customer_check(STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY,
                                     STORE_RELEASE_ALLOWED_RELAY_HOSTS=self.SAMPLE_HOST)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_exits_nonzero_for_http_relay_in_release_env(self):
        r = self._run_customer_check(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
                                     STORE_RELEASE_RELAY_URL='http://' + self.SAMPLE_HOST,
                                     STORE_RELEASE_ALLOWED_RELAY_HOSTS=self.SAMPLE_HOST)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_customer_check_reads_release_environment_variables(self):
        with mock.patch.dict(os.environ, self._env_without_release_secrets(
            STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
            STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY,
        ), clear=True):
            keys, relay = build_windows.resolve_customer_licence()
        self.assertEqual(keys.strip(), self.SAMPLE_KEY)
        self.assertEqual(relay.strip(), self.SAMPLE_RELAY)

    def test_customer_check_rejects_bad_inputs(self):
        pem = '-----BEGIN ' + 'PRIVATE KEY-----'
        allowed = self._allowed_hosts(self.SAMPLE_HOST)
        with self.assertRaises(build_windows.CustomerLicenceError):
            build_windows.validate_public_key_line(pem)
        with self.assertRaises(build_windows.CustomerLicenceError):
            build_windows.validate_relay_line('http://' + self.SAMPLE_HOST, allowed=allowed)
        with self.assertRaises(build_windows.CustomerLicenceError):
            build_windows.validate_relay_line(self.SAMPLE_RELAY + '?token=abc', allowed=allowed)

    def test_relay_exact_host_allowlist_rejects_paths_and_unlisted_hosts(self):
        allowed = self._allowed_hosts(self.SAMPLE_HOST)
        reject = (
            self.SAMPLE_RELAY + '/eyjhbgci-oijiuzi1nij9',
            self.SAMPLE_RELAY + '/eyjh-bgci/payl-oad/sig-ab12',
            self.SAMPLE_RELAY + '/' + ('a' * 16),
            self.SAMPLE_RELAY + '/not-allowed',
            'https://shop.eyjhbccioijiuzi1nij9.workers.dev',
            'https://eyjh-bgci-oiji-uzi1.workers.dev',
            'https://192.168.1.10',
            'https://[2001:db8::1]',
        )
        for url in reject:
            with self.assertRaises(build_windows.CustomerLicenceError, msg=url):
                build_windows.validate_relay_line(url, allowed=allowed)

    def test_relay_exact_host_allowlist_accepts_only_listed_host_and_paths(self):
        allowed = self._allowed_hosts(self.SAMPLE_HOST)
        for url in (self.SAMPLE_RELAY, self.SAMPLE_RELAY + '/licence-hub', self.SAMPLE_RELAY + '/api'):
            build_windows.validate_relay_line(url, allowed=allowed)
        other = self._allowed_hosts('licence-hub.workers.dev')
        build_windows.validate_relay_line('https://licence-hub.workers.dev', allowed=other)
        with self.assertRaises(build_windows.CustomerLicenceError):
            build_windows.validate_relay_line(self.SAMPLE_RELAY, allowed=other)

    def test_release_proof_customer_cli_uses_validated_relay(self):
        env = self._env_without_release_secrets(STORE_RELEASE_PUBLIC_KEY=self.SAMPLE_KEY,
                                                 STORE_RELEASE_RELAY_URL=self.SAMPLE_RELAY)
        r = subprocess.run([sys.executable, 'tools/build_windows.py', '--release-proof-customer'],
                           cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(),
                         list(build_windows.release_proof_licence_lines(True, self.SAMPLE_RELAY)))

    def test_customer_mode_refuses_template_files_in_the_repo(self):
        with mock.patch.dict(os.environ, self._env_without_release_secrets(), clear=True):
            with self.assertRaises(build_windows.CustomerLicenceError):
                build_windows.resolve_customer_licence(ROOT)

    def test_release_proof_marks_factory_and_customer_builds(self):
        self.assertEqual(build_windows.release_proof_licence_lines(False), ('customer_licence: no',))
        lines = build_windows.release_proof_licence_lines(True, self.SAMPLE_RELAY)
        self.assertEqual(lines[0], 'customer_licence: yes')
        self.assertEqual(lines[1], 'relay_host: ' + self.SAMPLE_HOST)


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

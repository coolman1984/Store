"""The Codespaces hostname exception must never expose a real shop."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness import ROOT  # noqa: F401 (sets up server imports)
import app as store


class CodespacesPreviewHosts(unittest.TestCase):
    def test_exact_owner_codespace_is_allowed_only_for_practice(self):
        fake = SimpleNamespace(practice=True, cfg={'port': 8097})
        env = {'CODESPACE_NAME': 'fuzzy-giraffe-123', 'ALSTORE_CODESPACES_PREVIEW': '1'}
        with patch.dict(os.environ, env), patch.object(store, 'APP', fake):
            self.assertTrue(store._codespaces_preview_host('fuzzy-giraffe-123-8097.app.github.dev'))
            handler = SimpleNamespace(headers={'Host': 'fuzzy-giraffe-123-8097.app.github.dev'})
            self.assertTrue(store.Handler.host_ok(handler))
            self.assertFalse(store._codespaces_preview_host('other-codespace-8097.app.github.dev'))
            self.assertFalse(store._codespaces_preview_host('fuzzy-giraffe-8097.app.github.dev'))
            self.assertFalse(store._codespaces_preview_host('fuzzy-giraffe-123-8096.app.github.dev'))
            self.assertFalse(store._codespaces_preview_host('fuzzy-giraffe-123-8097.app.github.dev.attacker.com'))
            self.assertFalse(store.Handler.host_ok(SimpleNamespace(headers={'Host': 'other-codespace-8097.app.github.dev'})))

    def test_preview_flag_is_opt_in(self):
        fake = SimpleNamespace(practice=True, cfg={'port': 8097})
        with patch.dict(os.environ, {'CODESPACE_NAME': 'fuzzy-giraffe-123'}, clear=True):
            with patch.object(store, 'APP', fake):
                self.assertFalse(store._codespaces_preview_host('fuzzy-giraffe-123-8097.app.github.dev'))

    def test_real_shop_never_allows_public_cloud_host(self):
        env = {'CODESPACE_NAME': 'fuzzy-giraffe-123', 'ALSTORE_CODESPACES_PREVIEW': '1'}
        fake = SimpleNamespace(practice=False, cfg={'port': 8097})
        with patch.dict(os.environ, env), patch.object(store, 'APP', fake):
            host = 'fuzzy-giraffe-123-8097.app.github.dev'
            self.assertFalse(store._codespaces_preview_host(host))
            self.assertFalse(store.Handler.host_ok(SimpleNamespace(headers={'Host': host})))
            self.assertTrue(store.Handler.host_ok(SimpleNamespace(headers={'Host': 'localhost:8096'})))

    def test_malformed_codespace_name_is_rejected(self):
        fake = SimpleNamespace(practice=True, cfg={'port': 8097})
        for name in ('', '../leak', 'bad.example.com', 'bad space'):
            with self.subTest(name=name):
                with patch.dict(os.environ, {'CODESPACE_NAME': name, 'ALSTORE_CODESPACES_PREVIEW': '1'}):
                    with patch.object(store, 'APP', fake):
                        self.assertFalse(store._codespaces_preview_host('fuzzy-giraffe-123-8097.app.github.dev'))


if __name__ == '__main__':
    unittest.main()

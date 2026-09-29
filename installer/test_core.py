import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / 'payload'
        (self.payload / 'manga_workspace').mkdir(parents=True)
        (self.payload / 'manga_workspace/plugin.py').write_text('new')
        (self.payload / 'manga_workspace.desktop').write_text('desktop-new')
        self.manifest()
        self.resource = self.root / 'resource'
        self.config = self.root / 'kritarc'

    def manifest(self):
        files = {p.relative_to(self.payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.payload.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        (self.payload / 'manifest.json').write_text(json.dumps({'version': 'test', 'files': files}))

    def test_first_install(self):
        core.install(self.payload, self.resource, self.config)
        self.assertEqual(core.setting(self.config.read_text(), 'python', 'enable_manga_workspace'), 'true')
        self.assertEqual((self.resource / 'pykrita/manga_workspace/plugin.py').read_text(), 'new')

    def test_update_preserves_config_and_materials(self):
        old = self.resource / 'pykrita/manga_workspace'
        old.mkdir(parents=True)
        (old / 'plugin.py').write_text('old')
        material = self.resource / 'material.png'
        material.write_bytes(b'original')
        original = b'\xef\xbb\xbfResourceDirectory=C:/custom\r\n[python]\r\nenable_other=true\r\nenable_manga_workspace=false\r\n[manga_workspace]\r\nai_server=http://old:8188\r\nai_positive=original\r\n'
        self.config.write_bytes(original)
        backup = core.install(self.payload, self.resource, self.config, 'http://127.0.0.1:8188')
        self.assertEqual((backup / 'kritarc').read_bytes(), original)
        self.assertEqual((backup / 'manga_workspace/plugin.py').read_text(), 'old')
        self.assertEqual(material.read_bytes(), b'original')
        self.assertTrue(self.config.read_bytes().startswith(b'\xef\xbb\xbf'))
        text = core.read_text(self.config)
        self.assertIn('ResourceDirectory=C:/custom', text)
        self.assertEqual(core.setting(text, 'python', 'enable_other'), 'true')
        self.assertEqual(core.setting(text, 'manga_workspace', 'ai_positive'), 'original')
        self.assertEqual(core.setting(text, 'manga_workspace', 'ai_server'), 'http://127.0.0.1:8188')

    def test_failed_config_write_rolls_back(self):
        old = self.resource / 'pykrita/manga_workspace'
        old.mkdir(parents=True)
        (old / 'plugin.py').write_text('old')
        desktop = old.parent / 'manga_workspace.desktop'
        desktop.write_text('desktop-old')
        self.config.write_bytes(b'[python]\nenable_manga_workspace=false\n')
        real_replace = core.os.replace
        def fail_config(source, destination):
            if Path(destination) == self.config:
                raise PermissionError('test locked config')
            return real_replace(source, destination)
        with patch.object(core.os, 'replace', side_effect=fail_config):
            with self.assertRaises(PermissionError):
                core.install(self.payload, self.resource, self.config)
        self.assertEqual((old / 'plugin.py').read_text(), 'old')
        self.assertEqual(desktop.read_text(), 'desktop-old')
        self.assertEqual(self.config.read_bytes(), b'[python]\nenable_manga_workspace=false\n')

    def test_corrupt_payload_does_not_touch_destination(self):
        (self.payload / 'manga_workspace/plugin.py').write_text('changed')
        with self.assertRaises(ValueError):
            core.install(self.payload, self.resource, self.config)
        self.assertFalse(self.resource.exists())
        self.assertFalse(self.config.exists())

    def test_manga_only_keeps_existing_ai_url(self):
        self.config.write_text('[manga_workspace]\nai_server=http://127.0.0.1:8000\n')
        core.install(self.payload, self.resource, self.config)
        self.assertEqual(core.setting(self.config.read_text(), 'manga_workspace', 'ai_server'), 'http://127.0.0.1:8000')

    def test_invalid_connection_urls(self):
        for url in ('file:///etc/passwd', 'http://user:password@localhost', 'http://localhost\n[python]'):
            with self.assertRaises(ValueError):
                core.check_comfy(url)


if __name__ == '__main__':
    unittest.main()

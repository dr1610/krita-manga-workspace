import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import json
import tempfile
import io

spec = importlib.util.spec_from_file_location('model_previews', Path(__file__).parents[1] / 'manga_workspace/model_previews.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreviewTests(TestCase):
    def test_catalog_versions_are_explicit(self):
        self.assertEqual(module.guessed_version('fnMixAnimaTurbo_v31.safetensors'), 3159847)
        self.assertEqual(module.guessed_version('folder/hybridcelTurboAnima_v30.safetensors'), 3340336)
        self.assertEqual(module.version_id('https://civitai.red/models/1?modelVersionId=3159847'), 3159847)

    def test_only_version_links_are_accepted(self):
        self.assertEqual(module.version_id('https://civitai.com/models/12?modelVersionId=34'), 34)
        self.assertIsNone(module.version_id('https://other.test/?modelVersionId=34'))
        self.assertIsNone(module.version_id('https://civitai.com/models/12'))
        self.assertEqual(module.guessed_version('fnMix_v10_SafeTensor_full_fp16_3056484.safetensors'), 3056484)

    def test_download_manager_suffix_matches_but_other_model_does_not(self):
        files = [{'name': 'fnMix_v10.safetensors'}]
        self.assertTrue(module.filename_matches('fnMix_v10_SafeTensor_full_fp16_3056484.safetensors', files))
        self.assertFalse(module.filename_matches('other_model_3056484.safetensors', files))

    def test_mismatched_version_never_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            response = io.BytesIO(json.dumps({'id': 12, 'modelId': 3, 'files': [{'name': 'other.safetensors'}]}).encode())
            with patch.object(module, 'urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    module.fetch_preview(directory, 'wanted.safetensors', 12)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cache_contains_same_version_source_without_images(self):
        with tempfile.TemporaryDirectory() as directory:
            response = io.BytesIO(json.dumps({'id': 12, 'modelId': 3, 'name': 'v1',
                'files': [{'name': 'wanted.safetensors'}], 'images': []}).encode())
            with patch.object(module, 'urlopen', return_value=response):
                module.fetch_preview(directory, 'wanted.safetensors', 12)
            saved = module.read_preview(directory, 'wanted.safetensors')
            self.assertEqual(saved['url'], 'https://civitai.com/models/3?modelVersionId=12')
            self.assertEqual(saved['images'], [])

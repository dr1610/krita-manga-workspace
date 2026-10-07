import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('model_paths',Path(__file__).parents[1]/'manga_workspace/model_paths.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ModelPathsTests(unittest.TestCase):
    def test_add_change_remove_preserves_other_config(self):
        original='existing: {checkpoints: "other"}\n'
        added=m.update_config(original,[('checkpoints','X:/models'),('loras','X:/LoRA')])
        self.assertIn(original,added)
        changed=m.update_config(added,[('checkpoints','Z:/new')])
        self.assertNotIn('X:/models',changed)
        self.assertEqual(changed.count(m.BEGIN),1)
        self.assertEqual(m.update_config(changed,[]).strip(),original.strip())
    def test_malformed_is_not_overwritten(self):
        with self.assertRaises(ValueError):m.update_config(m.BEGIN,[])
        with self.assertRaises(ValueError):m.update_config('', [('loras','bad\npath')])

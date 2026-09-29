import ast
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

source = Path(__file__).parents[1] / 'manga_workspace' / 'user_materials.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
tree.body = [node for node in tree.body if isinstance(node, (ast.Import, ast.Assign)) or
             isinstance(node, ast.ImportFrom) and node.module == 'pathlib' or
             isinstance(node, ast.ClassDef) and node.name == 'MaterialStore']
namespace = {}
exec(compile(tree, str(source), 'exec'), namespace)
Store = namespace['MaterialStore']

class MaterialStoreTests(unittest.TestCase):
    def test_copy_survives_original_removal_and_set_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original = root / 'original.svg'
            original.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            store = Store(root / 'library')
            item = store.add(original, '試験素材', '吹き出し', '丸 会話')
            original.unlink()
            self.assertTrue((store.root / item['id'] / item['file']).exists())
            item['favorite'] = True; store.save(item)
            self.assertTrue(Store(store.root).entries()[0]['favorite'])
            package = root / 'set.zip'; store.export_set(package)
            other = Store(root / 'other'); self.assertEqual(other.import_set(package), 1)
            restored = other.entries()[0]
            self.assertEqual(restored['name'], '試験素材')
            self.assertEqual(restored['tags'], '丸 会話')
            self.assertTrue(restored['favorite'])
            self.assertNotEqual(restored['id'], item['id'])

    def test_set_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); package = root / 'bad.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr('a/material.json', json.dumps({'file':'../escape.svg', 'name':'bad'}))
                archive.writestr('escape.svg', '<svg/>')
            with self.assertRaises(ValueError): Store(root / 'library').import_set(package)
            self.assertFalse((root / 'escape.svg').exists())

    def test_invalid_metadata_does_not_break_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for index, value in enumerate([[], None, {'file':'source.png','name':14}, {'file':'source.png','name':'ok','category':[], 'tags':5}]):
                folder = Path(directory)/str(index); folder.mkdir()
                (folder/'material.json').write_text(json.dumps(value))
                (folder/'source.png').write_bytes(b'example')
            self.assertEqual(store.entries(), [])

    def test_failed_import_leaves_no_partial_materials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); package=root/'set.zip'; store=Store(root/'library')
            metadata = {'file':'source.svg','name':'ok','category':'その他','tags':''}
            with zipfile.ZipFile(package,'w') as archive:
                archive.writestr('one/material.json',json.dumps(metadata))
                archive.writestr('one/source.svg','<svg/>')
                archive.writestr('two/material.json',json.dumps(metadata))
            with self.assertRaises(KeyError): store.import_set(package)
            self.assertEqual(store.entries(), [])

    def test_export_cannot_overwrite_library_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); original=root/'input.svg'; original.write_text('<svg/>')
            store=Store(root/'library'); item=store.add(original,'ok','その他','')
            saved=store.store_path(item)/item['file']
            with self.assertRaises(ValueError): store.export_set(saved)
            self.assertEqual(saved.read_text(),'<svg/>')

if __name__ == '__main__': unittest.main()

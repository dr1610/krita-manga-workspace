"""RT layer selection must not race new-node registration or page changes."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from unittest.mock import Mock


class LiveLayerLifecycleTests(unittest.TestCase):
    def test_panel_workflow_restores_document_after_validation_error(self):
        source = Path(__file__).parents[1] / 'manga_workspace' / 'live_panel.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if getattr(n, 'name', '')
                 in ('PanelLiveDocument', 'prepare_panel_live')]
        scope = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
        document = SimpleNamespace(filename='original.kra')
        model = SimpleNamespace(_doc=document)
        def prepare():
            self.assertEqual(model._doc.bounds, (30, 50, 200, 300))
            self.assertEqual(model._doc.filename, 'original.kra')
            raise ValueError('model unavailable')
        with self.assertRaises(ValueError):
            scope['prepare_panel_live'](model, prepare, (30, 50, 200, 300), object())
        self.assertIs(model._doc, document)

    def test_generated_art_is_inserted_below_frame(self):
        source = Path(__file__).parents[1] / 'manga_workspace' / 'live_panel.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == 'add_panel_artwork')
        scope = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
        def node(key):
            return SimpleNamespace(uniqueId=lambda: SimpleNamespace(toString=lambda: key))
        art, mask, frame, old_sketch = [node(key) for key in ('art', 'mask', 'frame', 'sketch')]
        group = SimpleNamespace(childNodes=lambda: [art, mask, frame, old_sketch],
                                addChildNode=Mock())
        generated = object()
        scope['add_panel_artwork'](group, generated, {'frame': 'frame'})
        group.addChildNode.assert_called_once_with(generated, mask)

    def fixture(self):
        source = Path(__file__).parents[1] / 'manga_workspace' / 'live_panel.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == 'activate_layer_later')
        queue, selected = [], []
        node = SimpleNamespace(uniqueId=lambda: SimpleNamespace(toString=lambda: 'layer'))
        doc = SimpleNamespace(waitForDone=lambda: None, setActiveNode=selected.append)
        app = SimpleNamespace(activeDocument=lambda: doc)
        nodes = {'layer': node}
        scope = {'__package__': 'rt_test', 'Krita': SimpleNamespace(instance=lambda: app),
                 'QTimer': SimpleNamespace(singleShot=lambda delay, callback: queue.append(callback))}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
        self.modules = patch.dict('sys.modules', {
            'rt_test.panels': SimpleNamespace(node_by_id=lambda document, key: nodes.get(key))})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        return scope['activate_layer_later'], doc, node, app, nodes, queue, selected

    def test_new_layer_is_selected_after_event_returns(self):
        activate, doc, node, app, nodes, queue, selected = self.fixture()
        activate(doc, node)
        self.assertEqual(selected, [])
        queue.pop()()
        self.assertEqual(selected, [node])

    def test_closed_or_switched_document_is_not_selected(self):
        activate, doc, node, app, nodes, queue, selected = self.fixture()
        activate(doc, node)
        app.activeDocument = lambda: None
        queue.pop()()
        self.assertEqual(selected, [])

    def test_removed_layer_is_not_selected(self):
        activate, doc, node, app, nodes, queue, selected = self.fixture()
        activate(doc, node)
        nodes.clear()
        queue.pop()()
        self.assertEqual(selected, [])

    def test_restore_resolves_current_node_instead_of_stale_wrapper(self):
        activate, doc, node, app, nodes, queue, selected = self.fixture()
        activate(doc, node)
        replacement = object()
        nodes['layer'] = replacement
        queue.pop()()
        self.assertEqual(selected, [replacement])

    def test_cleanup_restores_empty_selection_once_and_retains_drawing(self):
        source = Path(__file__).parents[1] / 'manga_workspace' / 'live_panel.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == '_cleanup_session')
        restore = Mock()
        disconnect = Mock()
        scope = {'activate_layer_later': restore, 'disconnect_live_widgets': disconnect}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
        session = SimpleNamespace(
            _closing=False, _start_timer=Mock(), live_ui=object(), model=SimpleNamespace(
                live=SimpleNamespace(is_active=True), workspace='live'),
            _original_prepare_live=object(), extra_references=[Mock(), Mock()],
            _remove_reference=Mock(), _save_layer_session=Mock(), _restore_rt_model=Mock(),
            canvas=SimpleNamespace(has_strokes=True, flush_timer=Mock(), flush=Mock()),
            sketch_layer=Mock(), document=Mock(), previous_selection=None,
            _applied=False, previous_node=object(), _previous_workspace='generate')
        scope['_cleanup_session'](session)
        scope['_cleanup_session'](session)
        session.document.setSelection.assert_called_once_with(None)
        session.sketch_layer.remove.assert_not_called()
        session._remove_reference.assert_called_once_with()
        for slot in session.extra_references:
            slot.cleanup.assert_called_once_with()
        session._start_timer.stop.assert_called_once_with()
        disconnect.assert_called_once_with(session.live_ui)
        restore.assert_not_called()
        self.assertFalse(session.model.live.is_active)
        self.assertEqual(session.model.workspace, 'generate')

    def test_dialog_disposal_releases_nested_model_callbacks(self):
        source = Path(__file__).parents[1] / 'manga_workspace' / 'live_panel.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == 'disconnect_live_widgets')
        disconnected = []
        binding = SimpleNamespace(disconnect_all=lambda items: disconnected.extend(items))
        scope = {'QWidget': object}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
        child = SimpleNamespace(_bindings=['prompt'], _model_connections=['control'])
        ui = SimpleNamespace(_model_bindings=['workspace'], findChildren=lambda _: [child])
        with patch.dict('sys.modules', {
                'ai_diffusion.model.properties': SimpleNamespace(Binding=binding)}):
            scope['disconnect_live_widgets'](ui)
            scope['disconnect_live_widgets'](ui)
        self.assertEqual(disconnected, ['workspace', 'prompt', 'control'])
        self.assertEqual(ui._model_bindings, [])
        self.assertEqual(child._bindings, [])

    def test_apply_rejects_changed_document_before_creating_layer(self):
        source = Path(__file__).parents[1] / 'manga_workspace/live_panel.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'apply_result')
        warnings = Mock()
        scope = {'__package__': 'rt_apply_test',
                 'Krita': SimpleNamespace(instance=lambda: SimpleNamespace(activeDocument=lambda: object())),
                 'QMessageBox': SimpleNamespace(warning=warnings)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
        doc = Mock()
        session = SimpleNamespace(_closing=False, _applying=False, document=doc)
        with patch.dict('sys.modules', {'rt_apply_test.panels': SimpleNamespace(node_by_id=Mock())}):
            scope['apply_result'](session)
        warnings.assert_called_once()
        doc.createNode.assert_not_called()

    def test_popup_does_not_activate_new_layers_in_lifecycle(self):
        source = Path(__file__).parents[1] / 'manga_workspace/live_panel.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        for name in ('_finish_start', '_finish_apply', '_cleanup_session'):
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
            text = ast.unparse(fn)
            self.assertNotIn('setActiveNode', text)
            self.assertNotIn('activate_layer_later', text)

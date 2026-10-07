import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1] / 'manga_workspace'
spec = importlib.util.spec_from_file_location('live_layer_state', ROOT / 'live_layer_state.py')
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


class LayerIsolationTests(TestCase):
    def test_separate_layers_do_not_inherit_prompts_or_seed(self):
        style = SimpleNamespace(filename='model-a.json')
        model = SimpleNamespace(regions=SimpleNamespace(positive='character A', negative='old'),
                                style=style, seed=1234, live=SimpleNamespace(strength=.88))
        saved_a = state.settings_snapshot(model)
        state.apply_settings(model, {}, lambda _: None)
        self.assertEqual(model.regions.positive, '')
        self.assertEqual(model.regions.negative, '')
        self.assertEqual(model.seed, 0)
        self.assertEqual(model.live.strength, .3)
        model.regions.positive = 'background B'
        saved_b = state.settings_snapshot(model)
        state.apply_settings(model, saved_a, lambda _: style)
        self.assertEqual(model.regions.positive, 'character A')
        self.assertEqual(model.seed, 1234)
        self.assertEqual(saved_b['positive'], 'background B')

    def test_sketch_resolves_to_owner_but_output_and_unrelated_layer_do_not(self):
        states = {'layer-a': {'sketch': 'sketch-a', 'outputs': ['result-a']},
                  'layer-b': {'sketch': 'sketch-b', 'outputs': []}}
        self.assertEqual(state.owner_id(states, 'result-a'), 'result-a')
        self.assertEqual(state.owner_id(states, 'sketch-b'), 'layer-b')
        self.assertEqual(state.owner_id(states, 'new-layer'), 'new-layer')

    def test_live_input_uses_layer_provider_and_never_page_projection(self):
        path = ROOT / 'live_panel.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if getattr(n, 'name', '') in
                 ('PanelLiveDocument', 'prepare_panel_live')]
        scope = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
        document = Mock()
        model = SimpleNamespace(_doc=document)
        image, bounds = object(), object()
        provider = Mock(return_value=image)
        with patch.dict('sys.modules', {'ai_diffusion.image': SimpleNamespace(Image=lambda x: x)}):
            result = scope['prepare_panel_live'](
                model, lambda: model._doc.get_image(bounds), (0, 0, 100, 100), object(), provider)
        self.assertIs(result, image)
        self.assertIs(model._doc, document)
        document.get_image.assert_not_called()
        provider.assert_called_once_with(bounds)

    def test_invalid_annotation_is_ignored(self):
        self.assertEqual(state.read_states(SimpleNamespace(annotation=lambda _: b'invalid')), {})

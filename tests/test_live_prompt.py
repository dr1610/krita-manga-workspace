import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / 'manga_workspace'
spec = importlib.util.spec_from_file_location('live_prompt', ROOT / 'live_prompt.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LivePromptTests(TestCase):
    def test_lineart_priority_and_manual_tags(self):
        self.assertEqual(module.effective_prompt('room', False, True), 'room, monochrome, lineart')
        self.assertEqual(module.effective_prompt('room', True, True), 'room, monochrome, lineart')
        self.assertEqual(module.effective_prompt('sketch, lineart', True, True), 'sketch, lineart, monochrome')
        self.assertEqual(module.effective_prompt('room', False, False), 'room')

    def test_toggle_retains_original_text_and_manual_tags(self):
        source = 'classroom, monochrome, '
        self.assertEqual(module.effective_prompt(source, True), 'classroom, monochrome, sketch')
        self.assertEqual(module.effective_prompt(source, False), source)
        self.assertEqual(module.effective_prompt('', True), 'monochrome, sketch')

    def test_duplicate_tags_and_repeated_composition(self):
        for text in ('school', 'MONOCHROME, sketch', 'school,'):
            once = module.effective_prompt(text, True)
            self.assertEqual(module.effective_prompt(once, True), once)

    def test_synchronous_signal_does_not_overwrite_editor(self):
        tree = ast.parse((ROOT / 'live_panel.py').read_text(encoding='utf-8'))
        methods = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in ('_prompt_edited', '_sync_prompt')]
        scope = {'__name__': 'manga_workspace.test', '__package__': 'manga_workspace'}
        exec(compile(ast.Module(body=methods, type_ignores=[]), '<methods>', 'exec'), scope)
        editor = SimpleNamespace(text='empty classroom')
        editor.toPlainText = lambda: editor.text
        editor.setPlainText = lambda text: setattr(editor, 'text', text)
        editor.blockSignals = lambda blocked: None
        checkbox = SimpleNamespace(value=True)
        checkbox.isChecked = lambda: checkbox.value
        lineart = SimpleNamespace(value=False)
        lineart.isChecked = lambda: lineart.value
        controller = SimpleNamespace(prompt_editor=editor, monochrome_sketch=checkbox, lineart=lineart)
        controller._prompt_edited = lambda: scope['_prompt_edited'](controller)
        class Region:
            @property
            def positive(self): return self.value
            @positive.setter
            def positive(self, value):
                self.value = value
                scope['_sync_prompt'](controller, value)
        controller.model = SimpleNamespace(regions=Region())
        with patch.dict(sys.modules, {'manga_workspace.live_prompt': module}):
            controller._prompt_edited()
            self.assertEqual(editor.text, 'empty classroom')
            self.assertEqual(controller.model.regions.positive, 'empty classroom, monochrome, sketch')
            lineart.value = True
            controller._prompt_edited()
            self.assertEqual(controller.model.regions.positive, 'empty classroom, monochrome, lineart')
            self.assertEqual(editor.text, 'empty classroom')
            lineart.value = False
            controller._prompt_edited()
            self.assertEqual(controller.model.regions.positive, 'empty classroom, monochrome, sketch')
            editor.text = 'empty classroom, windows'
            controller._prompt_edited()
            checkbox.value = False
            controller._prompt_edited()
            self.assertEqual(controller.model.regions.positive, 'empty classroom, windows')

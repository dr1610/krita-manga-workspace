import importlib.util
from pathlib import Path
from unittest import TestCase

spec = importlib.util.spec_from_file_location('tool_retention', Path(__file__).parents[1] / 'manga_workspace/tool_retention.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ToolRetentionTests(TestCase):
    def test_layer_change_restores_move_transform_and_selection(self):
        for tool in ('KritaTransform/KisToolMove', 'KisToolTransform', 'InteractionTool', 'KisToolSelectRectangular'):
            guard = module.ToolRetention()
            guard.observe('a', tool, 0)
            self.assertEqual(guard.observe('b', module.BRUSH, .1), tool)
            self.assertEqual(guard.observe('b', module.BRUSH, .2), '')

    def test_explicit_brush_choice_takes_precedence(self):
        guard = module.ToolRetention()
        guard.observe('a', 'InteractionTool', 0)
        guard.layer_operation('InteractionTool', .1)
        guard.explicit_choice()
        self.assertEqual(guard.observe('b', module.BRUSH, .2), '')

    def test_same_layer_reorder_fallback_restores_once(self):
        guard = module.ToolRetention()
        guard.observe('a', 'KisToolTransform', 0)
        guard.layer_operation('KisToolTransform', .1)
        self.assertEqual(guard.observe('a', module.BRUSH, .2), 'KisToolTransform')
        self.assertEqual(guard.observe('a', module.BRUSH, .3), '')

    def test_existing_brush_is_preserved(self):
        guard = module.ToolRetention()
        guard.observe('a', module.BRUSH, 0)
        self.assertEqual(guard.observe('b', module.BRUSH, .2), '')

    def test_document_switch_does_not_restore_old_tool(self):
        guard = module.ToolRetention()
        guard.observe('a', 'InteractionTool', 0)
        guard.reset()
        self.assertEqual(guard.observe('b', module.BRUSH, .2), '')

    def test_no_layer_operation_means_no_forced_tool(self):
        guard = module.ToolRetention()
        guard.observe('a', 'InteractionTool', 0)
        self.assertEqual(guard.observe('a', module.BRUSH, .2), '')

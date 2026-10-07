"""Undo branches must preserve pixels and whether an empty layer can be removed."""
import ast
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest import TestCase
from unittest.mock import Mock


class SketchHistoryTests(TestCase):
    def canvas(self):
        path = Path(__file__).parents[1] / 'manga_workspace/live_panel.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if getattr(n, 'name', '') == 'SketchCanvas')
        names = ('remember', 'restore_history', 'undo', 'redo', 'effective_width')
        scope = {}
        exec(compile(ast.Module(body=[n for n in cls.body if getattr(n, 'name', '') in names],
                                type_ignores=[]), str(path), 'exec'), scope)
        canvas = SimpleNamespace(strokes=[], has_strokes=False, undo_stack=[], redo_stack=[], shape_start=None,
                                 history_limit=2, history_changed=Mock(), flush=Mock(), update=Mock())
        for name in names:
            setattr(canvas, name, MethodType(scope[name], canvas))
        return canvas

    def test_undo_redo_and_new_stroke_branch(self):
        c = self.canvas()
        c.remember()
        c.strokes.append('stroke 1')
        c.has_strokes = True
        c.undo()
        self.assertEqual(c.strokes, [])
        self.assertFalse(c.has_strokes)
        c.redo()
        self.assertEqual(c.strokes, ['stroke 1'])
        self.assertTrue(c.has_strokes)
        c.undo()
        c.remember()
        c.strokes.append('stroke 2')
        c.redo()
        self.assertEqual(c.strokes, ['stroke 2'])
        self.assertEqual(c.redo_stack, [])

    def test_history_is_bounded(self):
        c = self.canvas()
        for i in range(10):
            c.remember()
            c.strokes.append(i)
        self.assertEqual(len(c.undo_stack), 2)
        c.undo()
        c.undo()
        c.undo()
        self.assertEqual(c.strokes, list(range(8)))

    def test_eraser_footprint_does_not_inherit_marker_multiplier(self):
        c = self.canvas()
        c.brush_width, c.brush_kind, c.eraser = 20, 'マーカー', False
        self.assertEqual(c.effective_width(), 40)
        c.eraser = True
        self.assertEqual(c.effective_width(), 20)

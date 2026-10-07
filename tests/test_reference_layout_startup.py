import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import TestCase


def method(file, cls, name, namespace):
    tree = ast.parse((Path(__file__).parents[1] / 'manga_workspace' / file).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    function = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
    function.body = [n for n in function.body if not isinstance(n, ast.ImportFrom)]
    exec(compile(ast.Module(body=[function], type_ignores=[]), file, 'exec'), namespace)
    return namespace[name]


class ReferenceLayoutStartupTests(TestCase):
    def test_height_follows_current_page_only(self):
        hint = lambda h: NS(height=lambda: h)
        layout = NS(activate=lambda: None, sizeHint=lambda: hint(120))
        page = NS(layout=lambda: layout)
        calls = []
        tab = NS(currentWidget=lambda: page, tabBar=lambda: NS(sizeHint=lambda: hint(28)),
                 minimumHeight=lambda: 600, maximumHeight=lambda: 600, setFixedHeight=calls.append)
        fit = method('live_panel.py', 'ContentHeightTabs', 'fit_current_page', {})
        fit(tab)
        self.assertEqual(calls, [156])
        layout.sizeHint = lambda: hint(420)
        fit(tab)
        self.assertEqual(calls[-1], 456)

    def test_startup_retries_reset_and_confirms_actual_tool(self):
        properties, calls, callbacks = {}, [], []
        current = ['brush']
        action = NS(isEnabled=lambda: True, trigger=lambda: (calls.append('select'), current.__setitem__(0, 'InteractionTool')))
        main = NS(property=lambda k: properties.get(k), setProperty=lambda k,v: properties.update({k:v}))
        window = NS(activeView=lambda: object(), qwindow=lambda: main)
        krita = NS(instance=lambda: NS(activeWindow=lambda: window, action=lambda name: action))
        select = method('extension.py', 'WorkspaceExtension', 'select_startup_tool',
                        {'Krita': krita, 'tool_name': lambda m: current[0],
                         'QTimer': NS(singleShot=lambda delay, fn: callbacks.append(fn))})
        owner = NS()
        owner.select_startup_tool = lambda *args: select(owner, *args)
        owner.select_startup_tool(main)
        self.assertFalse(properties.get('manga_startup_tool_selected'))
        current[0] = 'brush'  # Krita restores its default after the first trigger.
        while callbacks:
            callbacks.pop(0)()
        self.assertEqual(calls, ['select', 'select'])
        self.assertTrue(properties['manga_startup_tool_selected'])
        owner.select_startup_tool(main)
        self.assertEqual(len(calls), 2)

    def test_startup_does_not_mark_success_when_action_unavailable(self):
        properties, callbacks = {}, []
        main = NS(property=lambda k: properties.get(k), setProperty=lambda k,v: properties.update({k:v}))
        window = NS(activeView=lambda: object(), qwindow=lambda: main)
        krita = NS(instance=lambda: NS(activeWindow=lambda: window, action=lambda name: None))
        select = method('extension.py', 'WorkspaceExtension', 'select_startup_tool',
                        {'Krita': krita, 'tool_name': lambda m: 'brush',
                         'QTimer': NS(singleShot=lambda delay, fn: callbacks.append(fn))})
        owner = NS()
        owner.select_startup_tool = lambda *args: select(owner, *args)
        owner.select_startup_tool(main)
        count = 0
        while callbacks:
            callbacks.pop(0)()
            count += 1
        self.assertEqual(count, 19)
        self.assertFalse(properties.get('manga_startup_tool_selected'))
        self.assertFalse(properties['manga_startup_tool_pending'])

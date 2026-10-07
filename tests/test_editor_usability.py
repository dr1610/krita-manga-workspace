"""Check target selection and tool transitions without starting Krita."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def methods(filename, class_name, names, **globals_):
    path = Path(__file__).parents[1] / 'manga_workspace' / filename
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    functions = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), globals_)
    return globals_


class Button:
    def setEnabled(self, value): self.enabled = value


class Item:
    def __init__(self, text): self.text = text
    def setData(self, role, value): self.value = value
    def setToolTip(self, text): pass


class List:
    def __init__(self): self.items, self.row = [], -1
    def blockSignals(self, block): pass
    def clear(self): self.items, self.row = [], -1
    def count(self): return len(self.items)
    def addItem(self, item): self.items.append(item)
    def currentRow(self): return self.row
    def setCurrentItem(self, item): self.row = self.items.index(item)
    def setCurrentRow(self, row): self.row = row


class EditorUsabilityTests(unittest.TestCase):
    def realtime_fixture(self, panel_document_matches=True, selected=True):
        events, messages = [], []
        doc = object()
        panel = SimpleNamespace(objectName=lambda: 'manga_panels',
                                document=doc if panel_document_matches else object(),
                                current=lambda: {'id': 'one'} if selected else None,
                                stop_tool=lambda: events.append('stop panel tool'),
                                open_live_panel=lambda: events.append('open live'))
        app = SimpleNamespace(activeDocument=lambda: doc,
                              activeWindow=lambda: SimpleNamespace(dockers=lambda: [panel]))
        owner = SimpleNamespace(_document=doc, rt_status=SimpleNamespace(setText=messages.append),
                                stop_canvas_modes=lambda: events.append('stop AI tools'))
        fn = methods('docker.py', 'MangaDocker', {'open_realtime'},
                     Krita=SimpleNamespace(instance=lambda: app))['open_realtime']
        return lambda: fn(owner), events, messages

    def test_rt_entry_opens_existing_live_editor(self):
        open_rt, events, messages = self.realtime_fixture()
        open_rt()
        self.assertEqual(events, ['stop AI tools', 'stop panel tool', 'open live'])
        self.assertEqual(messages, [''])

    def test_rt_entry_does_not_open_wrong_page(self):
        open_rt, events, messages = self.realtime_fixture(panel_document_matches=False)
        open_rt()
        self.assertEqual(events, [])
        self.assertIn('ページ', messages[0])

    def test_rt_entry_explains_missing_panel_selection(self):
        open_rt, events, messages = self.realtime_fixture(selected=False)
        open_rt()
        self.assertEqual(events, [])
        self.assertIn('コマを選択', messages[0])

    def created_selection_fixture(self):
        callbacks, events = [], []
        doc = SimpleNamespace(waitForDone=lambda: events.append('completed'))
        app = SimpleNamespace(activeDocument=lambda: doc)
        frames = [{'id': 'one'}, {'id': 'two'}]
        listing = List()
        listing.items = [Item('one'), Item('two')]
        owner = SimpleNamespace(document=doc, list=listing,
                                active_panels=lambda: frames,
                                select_panel=lambda row: events.append('highlight'),
                                current=lambda: frames[listing.row] if listing.row >= 0 else None,
                                run=lambda fn: fn(), activate_drawing=lambda: events.append('activate'))
        functions = methods('panels.py', 'PanelDocker', {'select_created_panel'},
                            Krita=SimpleNamespace(instance=lambda: app),
                            QTimer=SimpleNamespace(singleShot=lambda delay, fn: callbacks.append(fn)))
        select = lambda key: functions['select_created_panel'](owner, key)
        return owner, callbacks, events, select

    def test_created_layer_is_not_activated_inside_creation_event(self):
        owner, callbacks, events, select = self.created_selection_fixture()
        select('one')
        self.assertEqual(events, ['completed', 'highlight'])
        callbacks.pop()()
        self.assertEqual(events[-1], 'activate')

    def test_created_layer_activation_is_cancelled_after_page_switch(self):
        owner, callbacks, events, select = self.created_selection_fixture()
        select('one')
        owner.document = object()
        callbacks.pop()()
        self.assertNotIn('activate', events)

    def test_created_layer_activation_does_not_override_user_selection(self):
        owner, callbacks, events, select = self.created_selection_fixture()
        select('one')
        owner.list.row = 1
        callbacks.pop()()
        self.assertNotIn('activate', events)

    def test_only_latest_created_layer_activation_runs(self):
        owner, callbacks, events, select = self.created_selection_fixture()
        select('one')
        select('two')
        for callback in callbacks:
            callback()
        self.assertEqual(events.count('activate'), 1)

    def test_repeated_canvas_notification_keeps_running_tool(self):
        doc = object()
        events = []
        owner = SimpleNamespace(document=doc, data={}, overlay=object(),
                                update_action_state=lambda: events.append('controls'),
                                update_highlight=lambda: events.append('highlight'),
                                stop_tool=lambda: self.fail('Tool was stopped by a refresh'))
        functions = methods('panels.py', 'PanelDocker', {'canvasChanged'})
        functions['canvasChanged'](owner, SimpleNamespace(view=lambda: SimpleNamespace(document=lambda: doc)))
        self.assertEqual(events, ['controls', 'highlight'])

    def test_stale_page_cannot_receive_an_edit(self):
        errors = []
        functions = methods('panels.py', 'PanelDocker', {'run'},
                            Krita=SimpleNamespace(instance=lambda: SimpleNamespace(activeDocument=lambda: object())))
        owner = SimpleNamespace(document=object(), data={}, status=SimpleNamespace(setText=errors.append))
        functions['run'](owner, lambda: self.fail('Wrong-page operation executed'))
        self.assertIn('ページ切り替え中', errors[0])

    def refresh_fixture(self, remembered, active_id):
        listing = List()
        doc = SimpleNamespace(activeNode=lambda: object(), thumbnail=lambda *a: None)
        frames = [{'id': 'one', 'node': 'one'}, {'id': 'two', 'node': 'two'}]
        functions = methods('panels.py', 'PanelDocker', {'refresh'}, QListWidgetItem=Item,
                            Qt=SimpleNamespace(UserRole=0),
                            node_by_id=lambda d, key: SimpleNamespace(name=lambda: key))
        owner = SimpleNamespace(document=doc, list=listing, selection_by_document=remembered,
                                document_key=lambda: 'doc', active_panels=lambda: frames,
                                panel_for_node=lambda n: next((p for p in frames if p['id'] == active_id), None),
                                set_thumbnail=lambda *a: None, select_panel=lambda row: None)
        functions['refresh'](owner)
        return listing.currentRow()

    def test_page_layer_does_not_silently_select_first_panel(self):
        self.assertEqual(self.refresh_fixture({}, None), -1)

    def test_explicitly_cleared_selection_stays_cleared(self):
        self.assertEqual(self.refresh_fixture({'doc': None}, 'two'), -1)

    def test_active_layer_selects_its_panel_on_first_visit(self):
        self.assertEqual(self.refresh_fixture({}, 'two'), 1)

    def test_thumbnail_refresh_keeps_selected_panel(self):
        self.assertEqual(self.refresh_fixture({'doc': 'two'}, 'one'), 1)

    def test_document_selection_key_survives_save_as(self):
        functions = methods('panels.py', 'PanelDocker', {'document_key'}, identity=lambda root: root)
        owner = SimpleNamespace(document=SimpleNamespace(rootNode=lambda: 'stable-id', fileName=lambda: 'before.kra'))
        before = functions['document_key'](owner)
        owner.document.fileName = lambda: 'after.kra'
        self.assertEqual(functions['document_key'](owner), before)

    def test_page_buttons_explain_boundaries_by_disabling_them(self):
        functions = methods('pages.py', 'PageDocker', {'update_page_controls'})
        listing = List()
        listing.items = [Item('1'), Item('2')]
        listing.row = 0
        owner = SimpleNamespace(loading=False, busy=False, list=listing, document=object(),
                                selected=lambda: {'id': 'first'},
                                page_buttons={k: Button() for k in ('add', 'duplicate', 'remove')},
                                navigation_buttons=[Button(), Button()])
        functions['update_page_controls'](owner)
        self.assertFalse(owner.navigation_buttons[0].enabled)
        self.assertTrue(owner.navigation_buttons[1].enabled)
        owner.busy = True
        functions['update_page_controls'](owner)
        self.assertTrue(all(not b.enabled for b in list(owner.page_buttons.values()) + owner.navigation_buttons))

    def test_page_action_cannot_reenter_during_processing(self):
        functions = methods('pages.py', 'PageDocker', {'run'})
        owner = SimpleNamespace(busy=False, update_page_controls=lambda: None)
        calls = []
        def action():
            calls.append('first')
            functions['run'](owner, lambda: calls.append('second'))
        functions['run'](owner, action)
        self.assertEqual(calls, ['first'])
        self.assertFalse(owner.busy)


if __name__ == '__main__':
    unittest.main()

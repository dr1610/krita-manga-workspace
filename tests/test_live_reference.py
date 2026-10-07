import ast
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest import TestCase
from unittest.mock import Mock


def methods(cls):
    path = Path(__file__).parents[1] / 'manga_workspace/live_reference.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if getattr(n, 'name', '') == cls)
    scope = {}
    exec(compile(ast.Module(body=[n for n in node.body if isinstance(n, ast.FunctionDef)],
                            type_ignores=[]), str(path), 'exec'), scope)
    return scope


class ReferenceTests(TestCase):
    def test_preprocessing_never_reads_visible_document(self):
        scope = methods('ReferenceDocument')
        doc = Mock()
        proxy = SimpleNamespace(document=doc, image=object())
        self.assertEqual(scope['create_mask_from_selection'](proxy, object()), (None, None))
        doc.create_mask_from_selection.assert_not_called()
        self.assertIs(scope['__getattr__'](proxy, 'extent'), doc.extent)

    def test_detach_removes_only_owned_control_and_node(self):
        own, other, node = Mock(), Mock(), Mock()
        controls = [other, own]
        slot = SimpleNamespace(control=own, node=node, update_status=Mock(),
                               dialog=SimpleNamespace(model=SimpleNamespace(
                                   regions=SimpleNamespace(control=controls), layers=Mock())))
        detach = methods('ReferenceSlot')['detach']
        detach(slot)
        detach(slot)
        self.assertEqual(controls, [other])
        node.remove.assert_called_once_with()

    def test_disabled_slot_does_not_install(self):
        slot = SimpleNamespace(closed=False, pending=None, image=object(),
                               enabled=Mock(), detach=Mock(), status=Mock(), install=Mock())
        slot.enabled.isChecked.return_value = False
        methods('ReferenceSlot')['sync'](slot)
        slot.detach.assert_called_once_with()
        slot.install.assert_not_called()

    def test_failed_pose_job_can_be_retried(self):
        control = Mock()
        slot = SimpleNamespace(pending=control, pose_finished=Mock(), detach=Mock(), status=Mock())
        methods('ReferenceSlot')['job_finished'](slot, SimpleNamespace(control=control))
        self.assertIsNone(slot.pending)
        slot.detach.assert_called_once_with()

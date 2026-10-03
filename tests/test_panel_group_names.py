"""Check layer-folder migration without requiring a running Krita window."""
import ast
from pathlib import Path
import unittest


source = Path(__file__).parents[1] / "manga_workspace" / "panels.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
docker = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PanelDocker")
method = next(node for node in docker.body if isinstance(node, ast.FunctionDef) and node.name == "reconcile_group_names")


class Group:
    def __init__(self, name, label=0):
        self._name = name
        self._label = label

    def name(self):
        return self._name

    def setName(self, name):
        self._name = name

    def colorLabel(self):
        return self._label

    def setColorLabel(self, label):
        self._label = label


namespace = {"PANEL_COLOR_LABEL": 3, "node_by_id": lambda document, key: document.get(key)}
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)


class Owner:
    reconcile_group_names = namespace["reconcile_group_names"]

    def __init__(self, nodes, panels):
        self.document = nodes
        self.data = {"panels": panels}


class PanelGroupNameTests(unittest.TestCase):
    def test_legacy_groups_match_thumbnail_order_and_custom_names_survive(self):
        first = Group("コマ aaaaaaaa")
        second = Group("背景用", 5)
        owner = Owner({"first": first, "second": second}, [
            {"id": "aaaaaaaa-1", "node": "first", "active": True},
            {"id": "bbbbbbbb-2", "node": "second", "active": True},
        ])
        self.assertTrue(owner.reconcile_group_names())
        self.assertEqual(first.name(), "コマ 01")
        self.assertEqual(first.colorLabel(), 3)
        self.assertEqual(second.name(), "背景用")
        self.assertEqual(second.colorLabel(), 5)

        first.setName("扉絵")
        first.setColorLabel(2)
        owner.reconcile_group_names()
        self.assertEqual((first.name(), first.colorLabel()), ("扉絵", 2))

    def test_split_and_restore_relabel_only_managed_groups(self):
        parent = Group("コマ cccccccc")
        child = Group("コマ dddddddd")
        p = {"id": "cccccccc-1", "node": "parent", "active": True}
        c = {"id": "dddddddd-2", "node": "child", "active": True}
        owner = Owner({"parent": parent, "child": child}, [p, c])
        owner.reconcile_group_names()
        p["active"] = False
        owner.reconcile_group_names()
        self.assertEqual(parent.name(), "分割前｜コマ 01")
        self.assertEqual(child.name(), "コマ 01")
        p["active"] = True
        c["active"] = False
        owner.reconcile_group_names()
        self.assertEqual(parent.name(), "コマ 01")
        self.assertTrue(child.name().startswith("分割前｜"))


if __name__ == "__main__":
    unittest.main()

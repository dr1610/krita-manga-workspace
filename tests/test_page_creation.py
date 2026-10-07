"""Page addition must never write frames through a changing active canvas."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).parents[1] / "manga_workspace"
KEY = "manga_workspace/frames-v1"
PAGE_KEY = "manga_workspace/page-settings-v1"


def load_functions(filename, names, namespace, class_name=None):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    body = tree.body
    if class_name:
        body = next(n for n in body if isinstance(n, ast.ClassDef) and n.name == class_name).body
    chosen = [n for n in body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=chosen, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class Node:
    def __init__(self, name):
        self.label, self.children, self.color = name, [], 0
        self.uid = str(uuid4())

    def name(self): return self.label
    def setName(self, name): self.label = name
    def uniqueId(self): return SimpleNamespace(toString=lambda: self.uid)
    def childNodes(self): return self.children
    def addChildNode(self, child, above): self.children.append(child)
    def setColorLabel(self, color): self.color = color


class Document:
    def __init__(self, name):
        self.name, self.root, self.annotations = name, Node(name), {}
        self.modified, self.refreshes, self.cloned = False, 0, False

    def annotation(self, key): return self.annotations.get(key, b"")
    def setAnnotation(self, key, description, value): self.annotations[key] = bytes(value)
    def setModified(self, value): self.modified = value
    def refreshProjection(self): self.refreshes += 1
    def rootNode(self): return self.root
    def createGroupLayer(self, name): return Node(name)
    def createNode(self, name, kind): return Node(name)
    def colorModel(self): return "RGBA"
    def colorDepth(self): return "U8"
    def width(self): return 800
    def height(self): return 1200
    def resolution(self): return 300
    def setActiveNode(self, node): self.active = node
    def saveAs(self, path): self.saved = path; return True
    def clone(self): self.cloned = True; return Document("duplicate")


def snapshot(doc):
    def node(n): return (n.name(), n.uid, n.color, [node(c) for c in n.children])
    return deepcopy((node(doc.root), doc.annotations, doc.modified, doc.refreshes))


def frame_namespace():
    def raster(doc, polygon, group, width):
        mask, frame = Node("mask"), Node("frame")
        group.addChildNode(mask, None)
        group.addChildNode(frame, None)
        return mask, frame
    return load_functions("panels.py", {"node_by_id", "create_frame_on_document", "initialize_page_frame"}, {
        "json": json, "QByteArray": bytes, "uuid4": uuid4, "KEY": KEY, "PANEL_COLOR_LABEL": 3,
        "geometry": SimpleNamespace(rectangle=lambda a, b, w, h: [a, [b[0], a[1]], b, [a[0], b[1]]]),
        "build_shape_on_document": raster,
    })


class PageCreationTests(unittest.TestCase):
    def test_add_initializes_new_document_before_old_canvas_can_be_rebound(self):
        self.run_create(False, True)

    def test_duplicate_does_not_initialize_another_basic_frame(self):
        self.run_create(True, True)

    def test_add_without_page_settings_leaves_source_untouched(self):
        self.run_create(False, False)

    def run_create(self, duplicate, has_settings):
        source = Document("existing-page")
        source.root.addChildNode(Node("existing-art"), None)
        source.annotations[KEY] = b'{"panels": [{"id": "existing-layout"}]}'
        before = snapshot(source)
        fresh = Document("new-page")
        settings = {"basic_frame_px": [30, 40, 760, 1150], "frame_line_mm": .5}
        fresh.annotations[PAGE_KEY] = json.dumps(settings).encode()
        events = []
        # Mimic delayed view activation: the canvas still belongs to the old page.
        window = SimpleNamespace(addView=lambda doc: events.append(("show", doc)) or
                                 SimpleNamespace(canvas=lambda: SimpleNamespace(view=lambda:
                                     SimpleNamespace(document=lambda: source))))
        app = SimpleNamespace(activeWindow=lambda: window, createDocument=lambda *args: fresh)
        frames = frame_namespace()
        module = ModuleType("manga_workspace.panels")
        def initialize(doc, config):
            self.assertEqual(events, [])
            self.assertIs(doc, fresh)
            events.append(("frame", doc))
            frames["initialize_page_frame"](doc, config)
        module.initialize_page_frame = initialize
        namespace = load_functions("pages.py", {"create_page"}, {
            "__package__": "manga_workspace", "json": json, "Path": Path,
            "uuid4": uuid4, "PAGE_SETTINGS_KEY": PAGE_KEY,
            "Krita": SimpleNamespace(instance=lambda: app),
            "project": SimpleNamespace(page=lambda path: {"id": "added", "file": str(path)}),
        }, "PageDocker")
        owner = SimpleNamespace(project_path="/test/book.manga.json", document=source,
            data={"pages": [{"id": "first"}, {"id": "second"}], "settings": settings if has_settings else None},
            selected=lambda: {"id": "first"}, open_page=lambda identity: source,
            document_page_settings=lambda doc: None, persist=lambda: None, refresh=lambda: None,
            create_manga_document=lambda config, number: fresh,
            list=SimpleNamespace(currentRow=lambda: 0))
        with patch.dict("sys.modules", {"manga_workspace.panels": module}):
            namespace["create_page"](owner, duplicate)
        self.assertEqual(snapshot(source), before)
        expected_index = 1 if duplicate else 2
        self.assertEqual(owner.data["pages"][expected_index]["id"], "added")
        self.assertEqual([e[0] for e in events], ["frame", "show"] if has_settings and not duplicate else ["show"])
        if has_settings and not duplicate:
            self.assertEqual(len(json.loads(fresh.annotation(KEY))["panels"]), 1)
            self.assertEqual(fresh.root.children[0].name(), "コマ 01")

    def test_existing_layout_cannot_be_initialized_again(self):
        doc = Document("existing")
        doc.annotations[KEY] = b'{"panels": []}'
        before = snapshot(doc)
        with self.assertRaises(ValueError):
            frame_namespace()["initialize_page_frame"](doc, {})
        self.assertEqual(snapshot(doc), before)


if __name__ == "__main__":
    unittest.main()

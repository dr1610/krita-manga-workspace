from krita import Extension, Krita
from PyQt5.QtCore import Qt, QTimer, QByteArray, QEvent, QPoint, QSize
from PyQt5.QtWidgets import QMenu, QToolBar, QApplication, QAbstractButton, QStyle
from PyQt5.QtWidgets import QAction
from .compact import CompactScroll, scroll_content
from .onomatopoeia import OnomatopoeiaMaterialDialog, OnomatopoeiaSettingsDialog, make_icon
from .updater import UpdateDialog, UpdateManager


class WorkspaceExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self._tool_press = {}
        self._tool_dragging = None
        self._update_managers = {}

    def setup(self):
        pass

    def createActions(self, window):
        main = window.qwindow()
        QTimer.singleShot(1000, lambda: self.connect_main(main))

    def connect_main(self, main):
        window = next((w for w in Krita.instance().windows() if w.qwindow() == main), None)
        if window:
            self.connect_window(window)

    def connect_window(self, window):
        main = window.qwindow()
        if main.property("manga_workspace_menu"):
            return
        docks = {d.objectName(): d for d in window.dockers()}
        pages = docks.get("manga_pages")
        if not pages:
            QTimer.singleShot(1000, lambda: self.connect_main(main))
            return
        menu = QMenu("ページ管理", main)
        menu.setObjectName("manga_pages_menu")
        main.menuBar().addMenu(menu)
        for identity, title in [("manga_pages", "ページ管理を表示"),
                                ("manga_panels", "コマ割りを表示"),
                                ("manga_workspace", "AI作画を表示")]:
            dock = docks.get(identity)
            if dock:
                action = dock.toggleViewAction()
                if identity == "manga_workspace":
                    action.triggered.connect(lambda checked, p=pages: p.show_ai() if checked else None)
                menu.addAction(action)
        ai_dock = docks.get("manga_workspace")
        if ai_dock:
            menu.addAction("AI作画の設定…", lambda checked=False, d=ai_dock, p=pages:
                           self.open_ai_settings(p, d))
        menu.addSeparator()
        for title, fn in [("コミック作品として保存…", pages.new_project), ("コミック作品を開く…", pages.open_project),
                          ("漫画原稿設定…", pages.configure_page),
                          ("ページ追加", pages.add_page), ("ページ複製", pages.duplicate),
                          ("選択ページを削除", pages.delete_page),
                          ("前のページ", lambda: pages.step(-1)), ("次のページ", lambda: pages.step(1)),
                          ("ページを保存", pages.save), ("作品をすべて保存", pages.save_all)]:
            menu.addAction(title, lambda checked=False, f=fn: pages.run(f))
        menu.addSeparator()
        menu.addAction("左右パネルをコンパクトに", lambda: self.with_window(main, self.compact))
        menu.addAction("漫画用の配置に整える", lambda: self.with_window(main, self.arrange))
        panel_position = menu.addMenu("コマ一覧の配置")
        for title, area in (("下に横長で配置", Qt.BottomDockWidgetArea),
                            ("左に縦長で配置", Qt.LeftDockWidgetArea),
                            ("右に縦長で配置", Qt.RightDockWidgetArea)):
            panel_position.addAction(title, lambda checked=False, a=area:
                                     self.place_panel_dock(main, a))
        menu.addAction("この配置を保存", lambda: self.save_layout(main))
        menu.addAction("保存した配置に戻す", lambda: self.restore_layout(main))
        sound_menu = main.menuBar().addMenu("オノマトペ")
        sound_menu.setObjectName("manga_onomatopoeia_menu")
        sound_menu.addAction(make_icon(), "オノマトペ素材を作成…",
                             lambda checked=False, m=main: self.open_onomatopoeia_material(m))
        sound_menu.addAction("オノマトペ設定…",
                             lambda checked=False, m=main: self.open_onomatopoeia_settings(m))
        menu.addSeparator()
        update_action = menu.addAction("拡張機能の更新…")
        manager = UpdateManager(main)
        self._update_managers[id(main)] = manager
        update_action.triggered.connect(lambda checked=False, m=main, u=manager: UpdateDialog(u, m).exec_())
        manager.available.connect(lambda release, m=main, a=update_action:
                                  self.update_available(m, a, release))
        QTimer.singleShot(7000, manager.check)
        self.install_history_buttons(main)
        self.install_toolbox_drag(main, window)
        self.install_onomatopoeia_tool(main)
        bar = QToolBar("漫画制作", main)
        bar.setObjectName("manga_workspace_toolbar")
        bar.addAction("漫画作画", lambda: self.with_window(main, self.show_manga))
        bar.addAction("AI作画", lambda: self.with_window(main, self.show_ai))
        bar.addAction("全体にフィット", lambda: self.native_action_preserving_docks(main, "zoom_to_fit"))
        bar.addAction("ページ確認", lambda: self.with_window(main, lambda w: self.arrange(w, True)))
        bar.addSeparator()
        bar.addAction("作品を開く", lambda: pages.run(pages.open_project))
        bar.addAction("作品を保存", lambda: pages.run(pages.save_all))
        main.addToolBarBreak(Qt.TopToolBarArea)
        main.addToolBar(Qt.TopToolBarArea, bar)
        bar.show()
        main.installEventFilter(self)
        main.setProperty("manga_workspace_menu", True)
        # Adapt the installed AI docker only at runtime; disabling this plugin
        # and restarting leaves its source and standard layout behavior intact.
        for dock in window.dockers():
            if type(dock).__name__ == "ImageDiffusionWidget" and not isinstance(dock.widget(), CompactScroll):
                scroll_content(dock, dock.widget())
        # Krita is still restoring its own dock/widget state while Python
        # extensions are created.  Calling restoreState()/arrange() from a
        # startup timer can re-enter Qt/Python callbacks and crash Krita.
        # Keep the restored Krita workspace untouched at startup.  Users can
        # explicitly apply or restore the manga layout from the menu.

    def install_onomatopoeia_tool(self, main):
        """Add a stable vertical tool beside Krita's native left toolbox."""
        if main.findChild(QToolBar, "manga_onomatopoeia_toolbar"):
            return
        toolbar = QToolBar("オノマトペ", main)
        toolbar.setObjectName("manga_onomatopoeia_toolbar")
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setIconSize(QSize(30, 30))
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        action = toolbar.addAction(make_icon(32), "オノマトペ素材")
        action.setToolTip("オノマトペ素材を作成")
        action.triggered.connect(lambda checked=False, m=main: self.open_onomatopoeia_material(m))
        main.addToolBar(Qt.LeftToolBarArea, toolbar)
        toolbar.show()

    @staticmethod
    def open_onomatopoeia_material(main):
        OnomatopoeiaMaterialDialog(main).exec_()

    @staticmethod
    def open_onomatopoeia_settings(main):
        OnomatopoeiaSettingsDialog(main).exec_()

    @staticmethod
    def update_available(main, action, release):
        tag = str(release.get("tag_name", "")).lstrip("v")
        action.setText("● 更新あり：" + tag + "…")
        action.setIcon(main.style().standardIcon(QStyle.SP_BrowserReload))
        main.statusBar().showMessage("漫画ワークスペースの更新があります：" + tag, 15000)

    def install_toolbox_drag(self, main, window):
        """A normal click selects a tool; dragging pulls out Tool Options."""
        installed = 0
        for button in main.findChildren(QAbstractButton):
            if button.metaObject().className() != "KoToolBoxButton":
                continue
            if not button.property("manga_tool_drag"):
                button.installEventFilter(self)
                button.setProperty("manga_tool_drag", True)
            button.setToolTip((button.toolTip() + "\n" if button.toolTip() else "") +
                              "ドラッグ：ツールのオプションを引き出す")
            installed += 1
        return installed

    def show_tool_options(self, main, global_position=None):
        window = next((w for w in Krita.instance().windows() if w.qwindow() == main), None)
        options = next((d for d in window.dockers() if d.objectName() == "sharedtooldocker"), None) if window else None
        if not options:
            main.statusBar().showMessage("ツールのオプションが見つかりません", 4000)
            return None
        options.setFloating(True)
        options.resize(360, 520)
        if global_position is not None:
            screen = QApplication.desktop().availableGeometry(global_position)
            x = min(global_position.x() + 14, screen.right() - options.width())
            y = min(global_position.y() + 14, screen.bottom() - options.height())
            options.move(max(screen.left(), x), max(screen.top(), y))
        options.show()
        options.raise_()
        main.statusBar().showMessage("ツールのオプションを引き出しました", 3000)
        return options

    def install_history_buttons(self, main):
        """Put explicit history buttons in Krita's always-visible file bar."""
        toolbar = main.findChild(QToolBar, "mainToolBar")
        if not toolbar or main.findChild(QAction, "manga_workspace_undo"):
            return
        undo_native = Krita.instance().action("edit_undo")
        redo_native = Krita.instance().action("edit_redo")
        toolbar.addSeparator()
        for identity, title, native in (
                ("manga_workspace_undo", "↶ 戻る", undo_native),
                ("manga_workspace_redo", "↷ 進む", redo_native)):
            action = QAction(native.icon() if native else main.windowIcon(), title, main)
            action.setObjectName(identity)
            action.setToolTip(title + "（Krita標準）")
            action.triggered.connect(lambda checked=False, a=native: a.trigger() if a else None)
            toolbar.addAction(action)
        toolbar.show()

    def start_window(self, main):
        if QApplication.activeModalWidget():
            QTimer.singleShot(500, lambda: self.start_window(main))
            return
        window = next((w for w in Krita.instance().windows() if w.qwindow() == main), None)
        if not window:
            return
        # Krita restores its document dock state when the first view opens.
        # Apply our saved arrangement after that transition has completed.
        QTimer.singleShot(500, lambda: self.finish_layout(main))

    def with_window(self, main, fn):
        window = next((w for w in Krita.instance().windows() if w.qwindow() == main),None)
        if window:
            fn(window)

    @staticmethod
    def native_action(identity):
        action = Krita.instance().action(identity)
        if action:
            action.trigger()

    def native_action_preserving_docks(self, main, identity):
        """Run a canvas action without changing the active tabs in dock groups."""
        window = next((w for w in Krita.instance().windows() if w.qwindow() == main), None)
        active = ([dock for dock in window.dockers()
                   if dock.isVisible() and not dock.visibleRegion().isEmpty()]
                  if window else [])
        self.native_action(identity)
        def restore_tabs():
            for dock in active:
                if dock.isVisible():
                    dock.raise_()
        QTimer.singleShot(0, restore_tabs)

    def finish_layout(self, main):
        window = next((w for w in Krita.instance().windows() if w.qwindow() == main), None)
        if not window:
            return
        if not self.restore_layout(main):
            self.arrange(window)
        bar = main.findChild(QToolBar, "manga_workspace_toolbar")
        if bar:
            bar.show()
        self.install_history_buttons(main)

    def save_layout(self, main):
        Krita.instance().writeSetting("manga_workspace", "layout_v5", bytes(main.saveState().toBase64()).decode("ascii"))
        main.statusBar().showMessage("漫画制作の配置を保存しました", 4000)

    def restore_layout(self, main):
        value = Krita.instance().readSetting("manga_workspace", "layout_v5", "")
        return bool(value) and main.restoreState(QByteArray.fromBase64(value.encode("ascii")))

    def show_ai(self, window):
        # Opening AI must not relocate the user's standard Layers docker.
        # Show the AI docker in its current/saved dock position and leave all
        # standard docks untouched.
        main = window.qwindow()
        ai = next((dock for dock in window.dockers() if dock.objectName() == "manga_workspace"), None)
        if not ai:
            return
        if ai.isFloating():
            ai.show()
        else:
            if main.dockWidgetArea(ai) == Qt.NoDockWidgetArea:
                main.addDockWidget(Qt.RightDockWidgetArea, ai)
            ai.show()
        ai.raise_()

    def show_manga(self, window):
        """Reveal manga controls while preserving every existing dock position."""
        main = window.qwindow()
        defaults = (("manga_pages", Qt.LeftDockWidgetArea),
                    ("manga_panels", Qt.BottomDockWidgetArea))
        for identity, default_area in defaults:
            dock = next((item for item in window.dockers()
                         if item.objectName() == identity), None)
            if not dock:
                continue
            if not dock.isFloating() and main.dockWidgetArea(dock) == Qt.NoDockWidgetArea:
                main.addDockWidget(default_area, dock)
            dock.show()

    @staticmethod
    def open_ai_settings(pages, ai_dock):
        pages.show_ai()
        if hasattr(ai_dock, "open_settings"):
            ai_dock.open_settings()

    def place_panel_dock(self, main, area):
        window = next((w for w in Krita.instance().windows() if w.qwindow() == main), None)
        if not window:
            return
        panels = next((dock for dock in window.dockers() if dock.objectName() == "manga_panels"), None)
        if not panels:
            return
        panels.setFloating(False)
        panels.setAllowedAreas(Qt.AllDockWidgetAreas)
        main.removeDockWidget(panels)
        main.addDockWidget(area, panels)
        panels.show()
        if area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
            main.resizeDocks([panels], [260], Qt.Horizontal)
        else:
            main.resizeDocks([panels], [190], Qt.Vertical)
        QTimer.singleShot(0, lambda p=panels, a=area: p.set_dock_orientation(a))
        self.save_layout(main)

    def eventFilter(self, obj, event):
        if isinstance(obj, QAbstractButton) and obj.metaObject().className() == "KoToolBoxButton":
            typ = event.type()
            if typ == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._tool_press[obj] = event.pos()
                return False
            if typ == QEvent.MouseMove and obj in self._tool_press and event.buttons() & Qt.LeftButton:
                moved = (event.pos() - self._tool_press[obj]).manhattanLength()
                if self._tool_dragging is obj or moved >= QApplication.startDragDistance():
                    if self._tool_dragging is not obj:
                        obj.setDown(False)
                        obj.click()
                        self._tool_dragging = obj
                    main = obj.window()
                    self.show_tool_options(main, event.globalPos())
                    return True
            if typ == QEvent.MouseButtonRelease:
                self._tool_press.pop(obj, None)
                if self._tool_dragging is obj:
                    obj.setDown(False)
                    self._tool_dragging = None
                    return True
        if event.type() == QEvent.Close and obj.property("manga_workspace_menu"):
            self.save_layout(obj)
        return False

    def arrange(self, window, review=False, ai_mode=False):
        main = window.qwindow()
        brushbar = main.findChild(QToolBar,"BrushesAndStuff")
        if brushbar:
            brushbar.setVisible(not review)
        manga_bar = main.findChild(QToolBar,"manga_workspace_toolbar")
        if manga_bar:
            main.insertToolBarBreak(manga_bar)
        docks = {d.objectName(): d for d in window.dockers()}
        pages, panels = docks.get("manga_pages"), docks.get("manga_panels")
        toolbox = next((d for d in window.dockers() if "toolbox" in d.objectName().lower()), None)
        if toolbox:
            toolbox.show()
        if pages:
            pages.setFloating(False)
            main.addDockWidget(Qt.LeftDockWidgetArea, pages)
            if toolbox:
                main.splitDockWidget(toolbox, pages, Qt.Horizontal)
            pages.show()
        if panels:
            panels.setFloating(False)
            panels.setMinimumHeight(165)
            main.addDockWidget(Qt.BottomDockWidgetArea, panels)
            panels.show()
        # A working drawing layout using Krita's real docks, without a dummy AI form.
        right = [docks.get(n) for n in ("OverviewDocker", "KisLayerBox", "PresetDocker")]
        previous = None
        for dock in right:
            if not dock:
                continue
            dock.setFloating(False)
            main.addDockWidget(Qt.RightDockWidgetArea, dock)
            if previous:
                main.splitDockWidget(previous, dock, Qt.Vertical)
            dock.setVisible(not review)
            previous = dock
        overview, layers, presets = right
        color = docks.get("ColorSelectorNg")
        if color and overview:
            color.setFloating(False)
            main.addDockWidget(Qt.RightDockWidgetArea, color)
            main.tabifyDockWidget(overview, color)
            color.setVisible(not review)
            overview.raise_()
        options = docks.get("sharedtooldocker")
        if options and presets:
            options.setFloating(False)
            main.addDockWidget(Qt.RightDockWidgetArea, options)
            main.tabifyDockWidget(presets, options)
            options.setVisible(not review)
            presets.raise_()
        ai = docks.get("manga_workspace")
        if ai:
            ai.setFloating(False)
            ai.setMinimumWidth(260)
            main.addDockWidget(Qt.RightDockWidgetArea, ai)
            anchor = layers or overview or presets
            if anchor:
                main.splitDockWidget(anchor, ai, Qt.Vertical)
            ai.setVisible(ai_mode and not review)
            if ai_mode and not review:
                ai.raise_()
        for identity in ("imageDiffusion", "comics_project_manager_docker"):
            if docks.get(identity):
                docks[identity].hide()
        visible = [d for d in right if d and not review]
        if visible:
            main.resizeDocks(visible, [210,360,250][:len(visible)], Qt.Vertical)
        self.compact(window)
        if ai and ai_mode and not review:
            main.resizeDocks([ai], [340], Qt.Horizontal)
            if layers:
                main.resizeDocks([layers, ai], [330, 380], Qt.Vertical)
        if toolbox:
            main.resizeDocks([toolbox], [40], Qt.Horizontal)
        if panels:
            main.resizeDocks([panels], [190], Qt.Vertical)
        self.save_layout(main)

    def compact(self, window):
        main = window.qwindow()
        for area, width in [(Qt.LeftDockWidgetArea, 230), (Qt.RightDockWidgetArea, 290)]:
            docks = [d for d in window.dockers() if not d.isFloating()
                     and d.isVisible() and main.dockWidgetArea(d) == area
                     and "toolbox" not in d.objectName().lower()
                     and d.objectName() != "manga_workspace"]
            if docks:
                main.resizeDocks(docks, [width]*len(docks), Qt.Horizontal)

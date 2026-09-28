"""Keep a dock's content accessible without imposing its minimum on the canvas."""
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QScrollArea, QSizePolicy


class CompactScroll(QScrollArea):
    def sizeHint(self):
        return QSize(270, 340)

    def minimumSizeHint(self):
        return QSize(120, 70)

    def fit_content_width(self):
        content = self.widget()
        if content:
            # A child layout can report a width larger than the docker. Since
            # the horizontal scrollbar is intentionally hidden, constrain the
            # form to the real viewport so its editors actually wrap.
            content.setFixedWidth(max(1, self.viewport().width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_content_width()


def scroll_content(dock, content):
    scroll = CompactScroll(dock)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setMinimumSize(120, 70)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    # Reparent first: QDockWidget must not dispose of the old content.
    content.setParent(scroll)
    content.setMinimumWidth(0)
    content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
    scroll.setWidget(content)
    scroll.fit_content_width()
    dock.setWidget(scroll)
    dock.setMinimumSize(120, 90)
    return scroll

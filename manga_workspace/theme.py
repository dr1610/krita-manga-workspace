"""Small semantic helpers; colors are inherited from the active Krita theme."""


def apply_panel_theme(widget):
    widget.setObjectName("mangaPanelRoot")
    widget.setStyleSheet("")


def section(label):
    label.setProperty("role", "section")
    return label


def muted(label):
    label.setProperty("role", "muted")
    return label

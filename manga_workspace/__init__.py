from krita import Krita, DockWidgetFactory, DockWidgetFactoryBase
from .docker import MangaDocker
from .pages import PageDocker
from .panels import PanelDocker
from .extension import WorkspaceExtension

Krita.instance().addDockWidgetFactory(
    DockWidgetFactory("manga_workspace", DockWidgetFactoryBase.DockRight, MangaDocker)
)
Krita.instance().addDockWidgetFactory(
    DockWidgetFactory("manga_pages", DockWidgetFactoryBase.DockLeft, PageDocker)
)
Krita.instance().addDockWidgetFactory(
    DockWidgetFactory("manga_panels", DockWidgetFactoryBase.DockLeft, PanelDocker)
)
Krita.instance().addExtension(WorkspaceExtension(Krita.instance()))

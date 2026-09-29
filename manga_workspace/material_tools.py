"""Material shortcuts that wrap inside a narrow native toolbox."""
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import QWidget, QGridLayout, QToolButton, QSizePolicy, QLayout

class MaterialTools(QWidget):
    def __init__(self, parent, icon_factory, open_material):
        super().__init__(parent)
        self.setObjectName('manga_onomatopoeia_toolbar')
        self.setMinimumWidth(28)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.grid=QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SetNoConstraint)
        self.grid.setContentsMargins(0,0,0,0); self.grid.setSpacing(2)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.buttons=[]; self.columns=0
        for kind,label in (('描き文字','描'),('吹き出し','吹'),('効果線','線')):
            button=QToolButton(self); button.setFixedSize(28,28)
            button.setIcon(icon_factory(22,label)); button.setIconSize(QSize(22,22))
            button.setToolTip(kind+'の素材を開く'); button.setAccessibleName(kind)
            button.clicked.connect(lambda checked=False,value=kind:open_material(value))
            self.buttons.append(button)
        self.reflow(88)

    def sizeHint(self): return QSize(88,self.height())

    def reflow(self,width):
        columns=max(1,min(3,(width+2)//30))
        if columns==self.columns: return
        self.columns=columns
        for button in self.buttons: self.grid.removeWidget(button)
        for index,button in enumerate(self.buttons):
            self.grid.addWidget(button,index//columns,index%columns)
        self.setFixedHeight(((3+columns-1)//columns)*30-2)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.reflow(event.size().width())

"""Editable COCO-18 body pose, using the installed KAD skeleton convention."""
import copy
import math
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QImage, QPainter, QPen, QColor
from PyQt5.QtWidgets import QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialogButtonBox


class PoseCanvas(QWidget):
    def __init__(self, size, points=None, parent=None):
        super().__init__(parent)
        from ai_diffusion.pose import default_positions, bone_connection, colors
        self.connections, self.colors = bone_connection, colors
        self.aspect = size[0] / size[1]
        self.default = [[p.x / 304, p.y / 460] for p in default_positions]
        valid = isinstance(points, list) and len(points) == 18 and all(
            isinstance(p, (list, tuple)) and len(p) == 2 and
            all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in p)
            for p in points)
        self.points = copy.deepcopy(points if valid else self.default)
        self.undo_stack, self.redo_stack = [], []
        self.drag = None
        self.setMinimumSize(320, 360)

    def target(self):
        w = min(self.width(), self.height() * self.aspect)
        h = w / self.aspect
        return QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)

    def draw(self, painter, width, height):
        painter.setRenderHint(QPainter.Antialiasing)
        points = [QPointF(x*width, y*height) for x, y in self.points]
        radius = max(2, min(width, height) / 140)
        for index, (a, b) in enumerate(self.connections):
            painter.setPen(QPen(QColor('#'+self.colors[index]), radius*1.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(points[a], points[b])
        painter.setPen(Qt.NoPen)
        for index, point in enumerate(points):
            painter.setBrush(QColor('#'+self.colors[index]))
            painter.drawEllipse(point, radius, radius)

    def render_pose(self, width, height):
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.black)
        painter = QPainter(image)
        self.draw(painter, width, height)
        painter.end()
        return image

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#303030'))
        target = self.target()
        painter.fillRect(target, Qt.black)
        painter.translate(target.topLeft())
        self.draw(painter, target.width(), target.height())
        # Large handles are editor-only; the control image uses small joints.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(Qt.white, 1))
        for x, y in self.points:
            painter.drawEllipse(QPointF(x*target.width(), y*target.height()), 7, 7)

    def remember(self):
        self.undo_stack.append(copy.deepcopy(self.points))
        self.undo_stack = self.undo_stack[-50:]
        self.redo_stack.clear()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        target = self.target()
        pos = event.localPos() - target.topLeft()
        distances = [(math.hypot(x*target.width()-pos.x(), y*target.height()-pos.y()), i)
                     for i, (x, y) in enumerate(self.points)]
        distance, index = min(distances)
        if distance <= 15:
            self.remember()
            self.drag = index

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.LeftButton:
            target = self.target()
            self.points[self.drag] = [max(0, min(1, (event.x()-target.x())/target.width())),
                                     max(0, min(1, (event.y()-target.y())/target.height()))]
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def history(self, undo):
        source, target = (self.undo_stack, self.redo_stack) if undo else (self.redo_stack, self.undo_stack)
        if source:
            target.append(copy.deepcopy(self.points))
            self.points = source.pop()
            self.update()

    def reset(self):
        self.remember()
        self.points = copy.deepcopy(self.default)
        self.update()


class PoseEditor(QDialog):
    def __init__(self, size, points=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('OpenPose人形 · 関節編集')
        self.resize(540, 700)
        layout = QVBoxLayout(self)
        note = QLabel('関節の白丸をドラッグしてポーズを編集。\n身体1人の2D骨格です。手指・3D回転・画像からの再編集は対象外です。\n生成への反映には、選択モデル用のPose ControlNetが必要です。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.canvas = PoseCanvas(size, points, self)
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        for label, action in [('戻す', lambda: self.canvas.history(True)), ('やり直す', lambda: self.canvas.history(False)), ('初期姿勢', self.canvas.reset)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('ポーズ参照に適用')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

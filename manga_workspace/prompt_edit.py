"""Prompt editor with local English tags and Japanese aliases."""
import csv
from pathlib import Path
from PyQt5.QtCore import Qt, QTimer, QModelIndex
from PyQt5.QtGui import QTextCursor, QTextOption, QStandardItemModel, QStandardItem, QColor, QBrush
from PyQt5.QtWidgets import QCompleter, QPlainTextEdit, QTreeView, QAbstractItemView, QHeaderView


TAG_ALIASES = (
    ("最高品質", "masterpiece"), ("高品質", "best_quality"), ("精密", "detailed"),
    ("高解像度", "highres"), ("美しい", "very_aesthetic"), ("漫画", "manga"),
    ("漫画線画", "manga_lineart"), ("線画", "lineart"), ("モノクロ", "monochrome"),
    ("グレースケール", "greyscale"), ("スクリーントーン", "screentone"),
    ("カラー", "color"), ("一人の女性", "1girl"), ("一人の男性", "1boy"),
    ("二人の女性", "2girls"), ("二人の男性", "2boys"), ("男女", "1girl, 1boy"),
    ("複数人物", "multiple_people"), ("全身", "full_body"), ("上半身", "upper_body"),
    ("顔アップ", "close-up"), ("横顔", "profile"), ("背中", "from_behind"),
    ("正面", "front_view"), ("俯瞰", "from_above"), ("煽り", "from_below"),
    ("広角", "wide_shot"), ("動的構図", "dynamic_composition"),
    ("赤髪", "red_hair"), ("黒髪", "black_hair"), ("金髪", "blonde_hair"),
    ("茶髪", "brown_hair"), ("青髪", "blue_hair"), ("長髪", "long_hair"),
    ("短髪", "short_hair"), ("ポニーテール", "ponytail"), ("ツインテール", "twintails"),
    ("笑顔", "smile"), ("真剣", "serious"), ("泣く", "crying"),
    ("赤面", "blush"), ("目を閉じる", "closed_eyes"), ("見る", "looking_at_viewer"),
    ("立つ", "standing"), ("座る", "sitting"), ("歩く", "walking"),
    ("走る", "running"), ("手をつなぐ", "holding_hands"), ("抱擁", "hug"),
    ("物を持つ", "holding_object"), ("制服", "school_uniform"), ("シャツ", "shirt"),
    ("スカート", "skirt"), ("ズボン", "pants"), ("ジャケット", "jacket"),
    ("教室", "classroom"), ("学校", "school"), ("街", "city"), ("室内", "indoors"),
    ("屋外", "outdoors"), ("公園", "park"), ("駅", "train_station"),
    ("朝", "morning"), ("夕方", "sunset"), ("夜", "night"), ("雨", "rain"),
    ("青空", "blue_sky"), ("窓", "window"), ("机", "desk"),
    ("低品質", "worst_quality"), ("ぼやけ", "blurry"), ("低解像度", "lowres"),
    ("文字", "text"), ("透かし", "watermark"), ("手の崩れ", "bad_hands"),
    ("人体崩れ", "bad_anatomy"), ("余分な指", "extra_fingers"),
    ("余分な手足", "extra_limbs"), ("重複人物", "duplicate_person"),
)


TYPE_COLORS = {
    0: "#8bd5ff",  # general
    1: "#d88cff",  # artist
    3: "#d6b36a",  # copyright
    4: "#8bd98b",  # character
    5: "#c3c8d4",  # meta
}
TYPE_LABELS = {0: "一般", 1: "作者", 3: "作品", 4: "キャラクター", 5: "メタ情報"}
JAPANESE_BY_TAG = {tag: japanese for japanese, tag in TAG_ALIASES if "," not in tag}


def completion_entries():
    return [{"tag": tag, "type": 0, "count": 0, "aliases": japanese,
             "japanese": japanese}
            for japanese, tag in TAG_ALIASES if "," not in tag]


_COMPLETION_VALUES = None
_COMPLETION_INDEX = None
_COMPLETION_SOURCE = "内蔵候補"


def completion_catalog():
    """Load SFW and NSFW Danbooru tags; packaged CSVs have priority."""
    global _COMPLETION_VALUES, _COMPLETION_INDEX, _COMPLETION_SOURCE
    if _COMPLETION_VALUES is not None:
        return _COMPLETION_VALUES, _COMPLETION_INDEX, _COMPLETION_SOURCE
    records = {item["tag"]: item for item in completion_entries()}
    package = Path(__file__).resolve().parent
    candidates = (
        (package / "tags" / "Danbooru.csv",
         package / "tags" / "Danbooru NSFW.csv"),
        (package.parent / "ai_diffusion" / "tags" / "Danbooru.csv",
         package.parent / "ai_diffusion" / "tags" / "Danbooru NSFW.csv"),
    )
    source = "内蔵候補"
    for paths in candidates:
        loaded = 0
        for path in paths:
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as stream:
                    for row in csv.DictReader(stream):
                        tag = (row.get("tag") or "").strip()
                        if tag:
                            try:
                                tag_type = int(row.get("type") or 0)
                            except ValueError:
                                tag_type = 0
                            try:
                                count = int(row.get("count") or 0)
                            except ValueError:
                                count = 0
                            existing = records.get(tag, {})
                            records[tag] = {
                                "tag": tag,
                                "type": tag_type,
                                "count": count,
                                "aliases": (row.get("aliases") or existing.get("aliases") or "").strip(),
                                "japanese": JAPANESE_BY_TAG.get(tag, existing.get("japanese", "")),
                            }
                loaded += 1
            except (OSError, UnicodeError, csv.Error):
                continue
        if loaded:
            source = "Danbooru 全体（SFW＋NSFW）" if loaded == 2 else "Danbooru（一部辞書）"
            break
    values = tuple(sorted(records.values(), key=lambda item: (-item["count"], item["tag"])))
    index = {}
    for value in values:
        tag = normalized_tag(value["tag"])
        aliases = normalized_tag(value.get("aliases", ""))
        japanese = normalized_tag(value.get("japanese", ""))
        for candidate in {tag, aliases, japanese}:
            for length in (1, 2):
                if len(candidate) >= length:
                    index.setdefault(candidate[:length], []).append(value)
    _COMPLETION_VALUES, _COMPLETION_INDEX, _COMPLETION_SOURCE = values, index, source
    return _COMPLETION_VALUES, _COMPLETION_INDEX, _COMPLETION_SOURCE


def normalized_tag(value):
    return "_".join(value.lower().strip().split())


def matching_entries(token, force=False):
    """Match Japanese aliases and tags while accepting spaces in English input."""
    query = normalized_tag(token)
    values, index, _ = completion_catalog()
    if not query:
        return list(values[:300]) if force else []
    candidates = index.get(query[:min(2, len(query))], ())
    prefix, contains = [], []
    for value in candidates:
        tag = normalized_tag(value["tag"])
        aliases = normalized_tag(value.get("aliases", ""))
        japanese = normalized_tag(value.get("japanese", ""))
        searchable = " ".join((tag, aliases, japanese))
        if tag.startswith(query) or aliases.startswith(query) or japanese.startswith(query):
            prefix.append(value)
        elif query in searchable or query in tag:
            contains.append(value)
    return prefix + contains


def compact_count(value):
    if value >= 1_000_000:
        return ("%.1fM" % (value / 1_000_000)).replace(".0M", "M")
    if value >= 1_000:
        return ("%.1fK" % (value / 1_000)).replace(".0K", "K")
    return str(value) if value else ""


class TagPromptEdit(QPlainTextEdit):
    """QPlainTextEdit that completes comma-separated tags; Ctrl+Space always opens it."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Prompt tags are frequently one long comma-separated token stream.
        # Wrap at any character so a narrow docker never hides the prompt to
        # the right or requires horizontal scrolling.
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAnywhere)
        option = self.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapAnywhere)
        self.document().setDefaultTextOption(option)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(0)
        self.completion_enabled = True
        self.completer = QCompleter(self)
        self.completion_model = QStandardItemModel(0, 2, self.completer)
        self.completer.setModel(self.completion_model)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setMaxVisibleItems(10)
        popup = QTreeView(self)
        popup.setRootIsDecorated(False)
        popup.setHeaderHidden(True)
        popup.setUniformRowHeights(True)
        popup.setSelectionBehavior(QAbstractItemView.SelectRows)
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # QTreeView has no columns until QCompleter installs its model.
        # Krita 5.2's bundled Qt 5.15.7 can access-violate when resize mode
        # is assigned to column 1 before that model is attached.
        self.completer.setPopup(popup)
        popup.header().setSectionResizeMode(0, QHeaderView.Stretch)
        popup.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.completer.setWidget(self)
        self.completer.activated[QModelIndex].connect(self.insert_completion_index)
        values, _, source = completion_catalog()
        self.setToolTip(
            "Tag補完ON：日本語1文字／英語2文字から候補表示。"
            "英語は空白・_の両方に対応。Ctrl+Spaceで一覧表示。%s・%d件" %
            (source, len(values)))

    def current_token(self):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
        before = cursor.selectedText()
        start = max(before.rfind(mark) for mark in (",", "、", ";")) + 1
        return before[start:].strip()

    def insert_completion(self, value):
        tag = value.strip()
        cursor = self.textCursor()
        block = cursor.block()
        position = cursor.positionInBlock()
        before = block.text()[:position]
        separator = max(before.rfind(mark) for mark in (",", "、", ";"))
        start = separator + 1
        # Select only the token immediately before the caret. The previous
        # implementation cleared a StartOfBlock selection at its left edge,
        # causing every completion to be inserted at the beginning of a line.
        cursor.setPosition(block.position() + start)
        cursor.setPosition(block.position() + position, QTextCursor.KeepAnchor)
        prefix = " " if separator >= 0 else ""
        cursor.insertText(prefix + tag + ", ")
        self.setTextCursor(cursor)

    def insert_completion_index(self, index):
        tag = index.sibling(index.row(), 0).data(Qt.UserRole) or index.data()
        self.insert_completion(str(tag))

    def keyPressEvent(self, event):
        if not self.completion_enabled:
            self.completer.popup().hide()
            super().keyPressEvent(event)
            return
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab,
                                                  Qt.Key_Backtab, Qt.Key_Escape):
            event.ignore()
            return
        shortcut = event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Space
        super().keyPressEvent(event)
        if not shortcut and event.text() in (",", "、", ";", "\n"):
            popup.hide()
            return
        self.show_completion(bool(shortcut))

    def inputMethodEvent(self, event):
        """Refresh suggestions after a Japanese IME commits text."""
        committed = bool(event.commitString())
        super().inputMethodEvent(event)
        if committed and self.completion_enabled:
            QTimer.singleShot(0, self.show_completion)

    def show_completion(self, force=False):
        if not self.completion_enabled:
            return
        token = self.current_token()
        minimum = 1 if any(ord(char) > 127 for char in token) else 2
        popup = self.completer.popup()
        if not force and len(token) < minimum:
            popup.hide()
            return
        matches = matching_entries(token, force)
        if not matches:
            popup.hide()
            return
        self.completion_model.clear()
        self.completion_model.setColumnCount(2)
        for match in matches:
            japanese = match.get("japanese", "")
            title = match["tag"] + (("［%s］" % japanese) if japanese else "")
            tag_item = QStandardItem(title)
            tag_item.setData(match["tag"], Qt.UserRole)
            tag_item.setEditable(False)
            tag_item.setForeground(QBrush(QColor(TYPE_COLORS.get(match.get("type", 0), "#c3c8d4"))))
            tag_item.setToolTip("%s%s" % (
                TYPE_LABELS.get(match.get("type", 0), "タグ"),
                ("／別名: " + match["aliases"]) if match.get("aliases") else ""))
            count_item = QStandardItem(compact_count(match.get("count", 0)))
            count_item.setEditable(False)
            count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            count_item.setForeground(QBrush(QColor("#8b93a3")))
            self.completion_model.appendRow((tag_item, count_item))
        self.completer.setCompletionPrefix("")
        self.completer.popup().setCurrentIndex(self.completion_model.index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(max(320, min(560, popup.sizeHintForColumn(0) +
                                   popup.sizeHintForColumn(1) + 36)))
        self.completer.complete(rect)

    def set_completion_enabled(self, enabled):
        self.completion_enabled = bool(enabled)
        if not self.completion_enabled:
            self.completer.popup().hide()

    def set_completion_visible_count(self, count):
        self.completer.setMaxVisibleItems(max(3, min(30, int(count))))

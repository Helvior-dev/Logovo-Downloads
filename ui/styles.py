import re
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QRegion
from PyQt6.QtWidgets import QComboBox, QFrame


THEME_PALETTES = {
    "green": {
        "root_bg": "#080b09", "tooltip_bg": "#111a13", "tab_bg": "#0d150f",
        "button_bg": "#0c120e", "button_hover": "#142018", "button_pressed": "#1a3020",
        "primary_bg": "#14271a", "primary_hover": "#1a3422", "input_bg": "#070a08",
        "disabled_bg": "#0a0f0b", "popup_bg": "#0a100c", "table_bg": "#080d09",
        "card_bg": "#0b120d", "card_hover": "#101a12", "selection_bg": "#23442c",
        "new_badge_bg": "#183923", "border": "#354a38", "border_soft": "#28392b",
        "card_border": "#2a3a2c", "card_edge": "#456c4d", "card_hover_border": "#527b58",
        "accent": "#91e5a3", "accent_fill": "#65c77e", "accent_hover": "#4f9e62",
        "accent_border_hover": "#5e9a69", "focus": "#79cb8b", "accent_text": "#a6efb4",
        "accent_bright": "#c1ffcd", "selection_text": "#b5f2bf", "accent_muted": "#91b197",
        "primary_border": "#65a875", "scroll": "#344a37", "scroll_hover": "#5c8b63",
        "checkbox_border": "#526b55", "grid": "#1c281e", "table_line": "#19231b",
        "disabled_text": "#59675a", "disabled_border": "#202c22", "disabled_hint": "#647064",
        "input_text": "#d2ddd3", "input_selection": "#d9ffe0", "accent_deep": "#3d7a4a",
        "accent_pressed": "#315f39", "text_dim": "#849184", "text_secondary": "#aab7aa",
    },
    "blue": {
        "root_bg": "#080b10", "tooltip_bg": "#111823", "tab_bg": "#0d1420",
        "button_bg": "#0c111a", "button_hover": "#142033", "button_pressed": "#1a2c43",
        "primary_bg": "#14273d", "primary_hover": "#1a3553", "input_bg": "#070a0f",
        "disabled_bg": "#0a0f14", "popup_bg": "#0a1018", "table_bg": "#080d14",
        "card_bg": "#0b121b", "card_hover": "#101a27", "selection_bg": "#23435f",
        "new_badge_bg": "#183349", "border": "#354b63", "border_soft": "#28394c",
        "card_border": "#2a3c50", "card_edge": "#456883", "card_hover_border": "#527a9a",
        "accent": "#91c5ff", "accent_fill": "#65a4e8", "accent_hover": "#4f86c2",
        "accent_border_hover": "#5e93cc", "focus": "#79b0ed", "accent_text": "#a6d3ff",
        "accent_bright": "#c1e3ff", "selection_text": "#b5dcff", "accent_muted": "#91afd1",
        "primary_border": "#6597cd", "scroll": "#344b67", "scroll_hover": "#5c82a8",
        "checkbox_border": "#526b88", "grid": "#1c2938", "table_line": "#192532",
        "disabled_text": "#596579", "disabled_border": "#202c3a", "disabled_hint": "#64748b",
        "input_text": "#d2dce8", "input_selection": "#d9eaff", "accent_deep": "#3d6f9f",
        "accent_pressed": "#315b83", "text_dim": "#849bc0", "text_secondary": "#aabbd0",
    },
    "pink": {
        "root_bg": "#0c080b", "tooltip_bg": "#1b1118", "tab_bg": "#160d14",
        "button_bg": "#150d12", "button_hover": "#251321", "button_pressed": "#35182b",
        "primary_bg": "#30162a", "primary_hover": "#411d38", "input_bg": "#0b070a",
        "disabled_bg": "#10090d", "popup_bg": "#110b10", "table_bg": "#0d090c",
        "card_bg": "#130a10", "card_hover": "#1b0e16", "selection_bg": "#512844",
        "new_badge_bg": "#3a1d31", "border": "#593448", "border_soft": "#3c2633",
        "card_border": "#402a38", "card_edge": "#70435f", "card_hover_border": "#8e5a7d",
        "accent": "#ffa6d8", "accent_fill": "#e77fba", "accent_hover": "#bb5d94",
        "accent_border_hover": "#ce70a6", "focus": "#e78aba", "accent_text": "#ffc1e4",
        "accent_bright": "#ffd7ed", "selection_text": "#ffd0eb", "accent_muted": "#c69bb5",
        "primary_border": "#b76593", "scroll": "#54364a", "scroll_hover": "#865673",
        "checkbox_border": "#77526a", "grid": "#2a1a25", "table_line": "#23151e",
        "disabled_text": "#6c5865", "disabled_border": "#30222c", "disabled_hint": "#806779",
        "input_text": "#e8d2df", "input_selection": "#ffe0f0", "accent_deep": "#8c476f",
        "accent_pressed": "#753a5e", "text_dim": "#ad8ba2", "text_secondary": "#c5aabd",
    },
    "red": {
        "root_bg": "#0d0808", "tooltip_bg": "#1c1111", "tab_bg": "#180d0d",
        "button_bg": "#160b0b", "button_hover": "#291414", "button_pressed": "#3a1b1b",
        "primary_bg": "#321616", "primary_hover": "#461e1e", "input_bg": "#0c0707",
        "disabled_bg": "#100909", "popup_bg": "#120a0a", "table_bg": "#0e0808",
        "card_bg": "#150909", "card_hover": "#1d0b0b", "selection_bg": "#582b2b",
        "new_badge_bg": "#3d1d1d", "border": "#593434", "border_soft": "#3d2525",
        "card_border": "#412929", "card_edge": "#754343", "card_hover_border": "#945b5b",
        "accent": "#ff9696", "accent_fill": "#e87373", "accent_hover": "#bf5252",
        "accent_border_hover": "#d46363", "focus": "#e47b7b", "accent_text": "#ffb0b0",
        "accent_bright": "#ffd0d0", "selection_text": "#ffc3c3", "accent_muted": "#c89696",
        "primary_border": "#b96262", "scroll": "#553737", "scroll_hover": "#895959",
        "checkbox_border": "#775050", "grid": "#2a1a1a", "table_line": "#231515",
        "disabled_text": "#6d5757", "disabled_border": "#302222", "disabled_hint": "#826666",
        "input_text": "#e8d2d2", "input_selection": "#ffe0e0", "accent_deep": "#8c4242",
        "accent_pressed": "#733737", "text_dim": "#b58d8d", "text_secondary": "#c7aaaa",
    },
    "amber": {
        "root_bg": "#0e0b07", "tooltip_bg": "#1c170f", "tab_bg": "#1a140b",
        "button_bg": "#171108", "button_hover": "#2b200f", "button_pressed": "#3b2b12",
        "primary_bg": "#35240e", "primary_hover": "#483217", "input_bg": "#0c0906",
        "disabled_bg": "#130f0a", "popup_bg": "#151006", "table_bg": "#100c07",
        "card_bg": "#191208", "card_hover": "#241909", "selection_bg": "#60401a",
        "new_badge_bg": "#443016", "border": "#604727", "border_soft": "#46351c",
        "card_border": "#493820", "card_edge": "#82602e", "card_hover_border": "#9b7333",
        "accent": "#f6c66e", "accent_fill": "#dfa349", "accent_hover": "#b87d2b",
        "accent_border_hover": "#c48c3d", "focus": "#e2af52", "accent_text": "#ffdb95",
        "accent_bright": "#ffe9bb", "selection_text": "#ffdfa6", "accent_muted": "#c7a977",
        "primary_border": "#bd8c43", "scroll": "#5a4527", "scroll_hover": "#8b6940",
        "checkbox_border": "#81633b", "grid": "#2d2214", "table_line": "#281c10",
        "disabled_text": "#736651", "disabled_border": "#332a1c", "disabled_hint": "#89775d",
        "input_text": "#e9ddc9", "input_selection": "#fff0cc", "accent_deep": "#93692e",
        "accent_pressed": "#765323", "text_dim": "#b7a082", "text_secondary": "#cdbda3",
    },
    "cyan": {
        "root_bg": "#071011", "tooltip_bg": "#102022", "tab_bg": "#0c1c1f",
        "button_bg": "#0a1719", "button_hover": "#123035", "button_pressed": "#174248",
        "primary_bg": "#123a40", "primary_hover": "#18515a", "input_bg": "#060d0f",
        "disabled_bg": "#0a1416", "popup_bg": "#0a181b", "table_bg": "#081316",
        "card_bg": "#0b1c20", "card_hover": "#102a2f", "selection_bg": "#20545e",
        "new_badge_bg": "#1a454a", "border": "#31565b", "border_soft": "#254349",
        "card_border": "#294c52", "card_edge": "#40818a", "card_hover_border": "#4c9aa4",
        "accent": "#87e9e8", "accent_fill": "#50c4ca", "accent_hover": "#3e9ea7",
        "accent_border_hover": "#50afb6", "focus": "#6dd6da", "accent_text": "#a4f5f0",
        "accent_bright": "#c3fff8", "selection_text": "#b3f7f3", "accent_muted": "#8bbbc0",
        "primary_border": "#60adb6", "scroll": "#315a60", "scroll_hover": "#4d8992",
        "checkbox_border": "#4b777d", "grid": "#193034", "table_line": "#15292e",
        "disabled_text": "#577378", "disabled_border": "#1d3539", "disabled_hint": "#648489",
        "input_text": "#d1e5e5", "input_selection": "#d8fffb", "accent_deep": "#307b84",
        "accent_pressed": "#266169", "text_dim": "#85adb3", "text_secondary": "#aecbd0",
    },
    "violet": {
        "root_bg": "#0b0911", "tooltip_bg": "#191425", "tab_bg": "#151124",
        "button_bg": "#120e1c", "button_hover": "#231a35", "button_pressed": "#322348",
        "primary_bg": "#2c1b44", "primary_hover": "#40275b", "input_bg": "#090711",
        "disabled_bg": "#100d18", "popup_bg": "#100b1b", "table_bg": "#0d0a17",
        "card_bg": "#150f22", "card_hover": "#1e1730", "selection_bg": "#493368",
        "new_badge_bg": "#35234d", "border": "#4d3d69", "border_soft": "#382e50",
        "card_border": "#3d3256", "card_edge": "#70558f", "card_hover_border": "#8868a9",
        "accent": "#c6a6ff", "accent_fill": "#a579e6", "accent_hover": "#8861c5",
        "accent_border_hover": "#9b72d3", "focus": "#b38af1", "accent_text": "#d8c2ff",
        "accent_bright": "#e8d9ff", "selection_text": "#e0cbff", "accent_muted": "#b7a0d0",
        "primary_border": "#9571c0", "scroll": "#4c3a65", "scroll_hover": "#785c96",
        "checkbox_border": "#67527f", "grid": "#261e36", "table_line": "#201a2d",
        "disabled_text": "#70647f", "disabled_border": "#292236", "disabled_hint": "#837491",
        "input_text": "#dfd7ed", "input_selection": "#f0e3ff", "accent_deep": "#72529f",
        "accent_pressed": "#583d7d", "text_dim": "#a895bd", "text_secondary": "#c6b9d7",
    },
}

_COLOR_ROLE_BY_VALUE = {
    color.lower(): role
    for palette in THEME_PALETTES.values()
    for role, color in palette.items()
}


def normalize_theme(theme_name: str | None) -> str:
    theme_name = str(theme_name or "green").lower()
    return theme_name if theme_name in THEME_PALETTES else "green"


def get_theme_colors(theme_name: str | None = None) -> dict[str, str]:
    return THEME_PALETTES[normalize_theme(theme_name)]


def square_combo_popup(popup: QFrame) -> None:
    try:
        popup.setFrameShape(QFrame.Shape.NoFrame)
        popup.setLineWidth(0)
        popup.setMidLineWidth(0)
        if popup.rect().isValid():
            popup.setMask(QRegion(popup.rect()))
    except RuntimeError:
        # The combo box may have been deleted before the deferred resize callback.
        pass


def theme_stylesheet(stylesheet: str, theme_name: str | None = None) -> str:
    palette = get_theme_colors(theme_name)

    def replace_color(match):
        role = _COLOR_ROLE_BY_VALUE.get(match.group(0).lower())
        return palette[role] if role else match.group(0)

    return re.sub(r"#[0-9a-fA-F]{6}", replace_color, stylesheet)


def configure_combo_popup(combo: QComboBox, theme_name: str | None = None) -> None:
    view = combo.view()
    view.setFrameShape(QFrame.Shape.NoFrame)

    popup = view.window()
    if not isinstance(popup, QFrame):
        return

    colors = get_theme_colors(theme_name)
    popup.setObjectName("TerminalComboPopup")
    popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    square_combo_popup(popup)
    popup.setStyleSheet(f"""
        QFrame#TerminalComboPopup {{
            background-color: {colors['popup_bg']};
            color: #cbd5cc;
            border: 1px solid {colors['border']};
            border-radius: 0px;
        }}
        QAbstractItemView {{
            background-color: {colors['popup_bg']};
            color: #cbd5cc;
            border: none;
            border-radius: 0px;
            selection-background-color: {colors['selection_bg']};
            selection-color: {colors['selection_text']};
            outline: none;
        }}
        QAbstractItemView::item {{
            padding: 5px 8px;
            border: none;
        }}
        QAbstractItemView::item:selected {{
            background-color: {colors['selection_bg']};
            color: {colors['selection_text']};
            border-left: 2px solid {colors['accent']};
        }}
    """)


def get_resource_path(rel: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / rel
    return Path(__file__).resolve().parent.parent / rel


def get_stylesheet(theme_name: str | None = None) -> str:
    arrow_svg = get_resource_path("media/down_arrow.svg").resolve().as_posix()
    css = r"""
    QWidget {
        color: #cbd5cc;
        font-family: "Cascadia Mono", "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace;
        font-size: 12px;
    }
    QMainWindow, QWidget#DownloadsTab, QWidget#PlaylistsTab, QWidget#HistoryTab,
    QWidget#SettingsTab, QWidget#AboutTab, QWidget#QueueContainer,
    QWidget#SettingsContainer, QWidget#SettingsScrollWrapper,
    QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {
        background-color: #080b09;
        background: #080b09;
    }
    QDialog, QMessageBox {
        background-color: #080b09;
        color: #cbd5cc;
    }
    QToolTip {
        background-color: #111a13;
        color: #cbd5cc;
        border: 1px solid #354a38;
        border-radius: 0px;
        padding: 4px 7px;
    }
    QTabBar::tab {
        background: transparent;
        color: #849184;
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0px;
        padding: 9px 14px;
        margin: 0px 3px;
        font-family: "Cascadia Mono", "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace;
        font-size: 12px;
        font-weight: normal;
    }
    QTabBar::tab:selected {
        color: #91e5a3;
        background: #0d150f;
        border-bottom: 2px solid #65c77e;
    }
    QTabBar::tab:hover:!selected {
        color: #cbd5cc;
        background: #0d150f;
    }
    QPushButton {
        background-color: #0c120e;
        color: #cbd5cc;
        border: 1px solid #354a38;
        border-radius: 0px;
        padding: 7px 12px;
        font-family: "Cascadia Mono", "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace;
        font-size: 12px;
        font-weight: normal;
    }
    QPushButton:hover {
        background-color: #142018;
        color: #a6efb4;
        border-color: #5e9a69;
    }
    QPushButton:pressed {
        background-color: #1a3020;
    }
    QPushButton:focus {
        border: 1px solid #91e5a3;
    }
    QPushButton:disabled {
        background-color: #0a0f0b;
        color: #59675a;
        border-color: #202c22;
    }
    QPushButton#PrimaryButton {
        background-color: #14271a;
        color: #a6efb4;
        border: 1px solid #65a875;
    }
    QPushButton#PrimaryButton:disabled {
        background-color: #0a0f0b;
        color: #59675a;
        border-color: #202c22;
    }
    QPushButton#PrimaryButton:hover {
        background-color: #1a3422;
        color: #c1ffcd;
        border-color: #91e5a3;
    }
    QPushButton#DangerButton {
        background-color: #1b100f;
        color: #e39a91;
        border: 1px solid #70413d;
        border-radius: 0px;
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 22px;
        border: none;
    }
    QComboBox::down-arrow {
        image: url("__ARROW_SVG__");
        width: 10px;
        height: 10px;
        margin-right: 6px;
    }
    QTabWidget, QTabWidget::pane {
        background: transparent;
        border: none;
    }
    QLineEdit, QComboBox {
        background-color: #070a08;
        color: #d2ddd3;
        border: 1px solid #354a38;
        border-radius: 0px;
        padding: 6px 9px;
        selection-background-color: #23442c;
        selection-color: #d9ffe0;
    }
    QLineEdit:focus, QComboBox:focus {
        border: 1px solid #79cb8b;
    }
    QLineEdit:disabled, QComboBox:disabled {
        background-color: #0a0f0b;
        color: #647064;
        border-color: #202c22;
    }
    QComboBox QAbstractItemView, QAbstractItemView {
        background-color: #0a100c;
        color: #cbd5cc;
        border: 1px solid #354a38;
        border-radius: 0px;
        selection-background-color: #1a3020;
        selection-color: #a6efb4;
        outline: none;
    }
    QProgressBar {
        background-color: #0a100c;
        border: 1px solid #28392b;
        border-radius: 0px;
        text-align: center;
        color: transparent;
    }
    QProgressBar::chunk {
        background-color: #65c77e;
        border-radius: 0px;
    }
    QWidget#QueueItemCard, QWidget#PlaylistCard {
        background-color: #0b120d;
        border: 1px solid #2a3a2c;
        border-left: 1px solid #456c4d;
        border-radius: 0px;
        margin: 0px 2px;
    }
    QWidget#QueueItemCard:hover, QWidget#PlaylistCard:hover {
        background-color: #101a12;
        border-color: #527b58;
        border-left-color: #91e5a3;
    }
    QScrollBar:vertical, QScrollBar:horizontal {
        background: #080b09;
        border: none;
        width: 9px;
        height: 9px;
        margin: 0px;
    }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
        background: #344a37;
        border-radius: 0px;
        min-height: 24px;
        min-width: 24px;
    }
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
        background: #5c8b63;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: none;
    }
    QLabel {
        color: #aab7aa;
    }
    QHeaderView::section {
        background-color: #0d150f;
        color: #91b197;
        border: none;
        border-bottom: 1px solid #354a38;
        padding: 6px 8px;
        font-weight: normal;
    }
    QTableWidget, QTreeWidget, QListWidget {
        background-color: #080d09;
        color: #cbd5cc;
        border: 1px solid #28392b;
        border-radius: 0px;
        gridline-color: #1c281e;
        selection-background-color: #1a3020;
        selection-color: #b5f2bf;
        outline: none;
    }
    QTableWidget::item, QTreeWidget::item, QListWidget::item {
        padding: 5px 7px;
        border-bottom: 1px solid #19231b;
    }
    QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {
        background-color: #1a3020;
        color: #b5f2bf;
    }
    QGroupBox {
        border: 1px solid #2a3a2c;
        border-radius: 0px;
        margin-top: 10px;
        padding: 12px 9px 9px 9px;
        color: #91b197;
        font-weight: normal;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 8px;
        padding: 0px 4px;
        color: #91e5a3;
    }
    QCheckBox, QRadioButton {
        color: #cbd5cc;
        spacing: 7px;
    }
    QCheckBox::indicator {
        width: 14px;
        height: 14px;
        border: 1px solid #526b55;
        border-radius: 0px;
        background-color: #080d09;
    }
    QCheckBox::indicator:checked {
        background-color: #65c77e;
        border-color: #91e5a3;
    }
    QRadioButton::indicator {
        width: 14px;
        height: 14px;
        border: 1px solid #526b55;
        background-color: #080d09;
    }
    QRadioButton::indicator:checked {
        background-color: #65c77e;
        border: 3px solid #080d09;
    }
    QPlainTextEdit, QTextEdit {
        background-color: #080d09;
        color: #cbd5cc;
        border: 1px solid #28392b;
        border-radius: 0px;
        selection-background-color: #23442c;
    }
    QMenu {
        background-color: #0b120d;
        color: #cbd5cc;
        border: 1px solid #354a38;
    }
    QMenu::item:selected {
        background-color: #1a3020;
        color: #a6efb4;
    }
    QPushButton#TagPill {
        background-color: #0b120d;
        color: #91e5a3;
        border: 1px solid #354a38;
        border-radius: 0px;
    }
    QPushButton#TagPill:hover {
        background-color: #142018;
        color: #c1ffcd;
        border-color: #79cb8b;
    }
    """
    css = css.replace("__ARROW_SVG__", arrow_svg)
    return theme_stylesheet(css, theme_name)

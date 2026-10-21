"""Application themes: light, dark, and system-following.

INF Avis is a Qt desktop app, so theming is done with a QPalette plus an
application-wide stylesheet. Call :func:`apply_theme` once after the
:class:`QApplication` exists, then again whenever the user picks a new mode.
"""

from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import QApplication

THEMES = ("light", "dark", "system")

# --------------------------------------------------------------------------- colours

LIGHT = {
    "name": "light",
    "window": "#f5f5f7",
    "window_text": "#1a1a1a",
    "base": "#ffffff",
    "alternate_base": "#eaeaea",
    "text": "#1a1a1a",
    "bright_text": "#ffffff",
    "button": "#f0f0f0",
    "button_text": "#1a1a1a",
    "highlight": "#4a90d9",
    "highlighted_text": "#ffffff",
    "link": "#4a90d9",
    "border": "#c8c8c8",
    "mid": "#d8d8d8",
    "shadow": "#b8b8b8",
    # Semantic colours used by the custom widgets (sidebar, cards).
    "card_bg": "#ffffff",
    "card_border": "#c8c8c8",
    "card_hover_border": "#4a90d9",
    "card_hover_bg": "#eef5ff",
    "card_selected_bg": "#dcebff",
    "sidebar_bg": "#f5f5f7",
    "sidebar_border": "#dddddd",
    "fav_zone_bg": "#ffffff",
    "fav_zone_border": "#bbbbbb",
    "fav_zone_hover_border": "#4a90d9",
    "fav_zone_hover_bg": "#eef5ff",
    "item_bg": "#ffffff",
    "item_border": "transparent",
    "item_selected_bg": "#dcebff",
    "item_selected_border": "#4a90d9",
    "item_hover_bg": "#f0f4ff",
    "muted_text": "#666666",
    "dim_text": "#999999",
    "accent": "#4a90d9",
    "accent_hover": "#357abd",
    "danger": "#c0392b",
    "input_bg": "#ffffff",
    "input_border": "#c8c8c8",
    "input_focus_border": "#4a90d9",
    "section_title": "#555555",
    "scrollbar_bg": "#e0e0e0",
    "scrollbar_handle": "#b8b8b8",
    "scrollbar_handle_hover": "#a0a0a0",
}

DARK = {
    "name": "dark",
    "window": "#2d2d30",
    "window_text": "#e8e8e8",
    "base": "#1e1e1e",
    "alternate_base": "#2a2a2d",
    "text": "#e8e8e8",
    "bright_text": "#ffffff",
    "button": "#3a3a3d",
    "button_text": "#e8e8e8",
    "highlight": "#4a90d9",
    "highlighted_text": "#ffffff",
    "link": "#6ca0e6",
    "border": "#4a4a50",
    "mid": "#5a5a60",
    "shadow": "#3a3a40",
    # Semantic colours used by the custom widgets (sidebar, cards).
    "card_bg": "#2a2a2d",
    "card_border": "#4a4a50",
    "card_hover_border": "#6ca0e6",
    "card_hover_bg": "#35353c",
    "card_selected_bg": "#3a3a4a",
    "sidebar_bg": "#2d2d30",
    "sidebar_border": "#4a4a50",
    "fav_zone_bg": "#2a2a2d",
    "fav_zone_border": "#666666",
    "fav_zone_hover_border": "#6ca0e6",
    "fav_zone_hover_bg": "#35353c",
    "item_bg": "#2a2a2d",
    "item_border": "transparent",
    "item_selected_bg": "#3a3a4a",
    "item_selected_border": "#6ca0e6",
    "item_hover_bg": "#35353c",
    "muted_text": "#a8a8a8",
    "dim_text": "#888888",
    "accent": "#6ca0e6",
    "accent_hover": "#8cb8f0",
    "danger": "#e74c3c",
    "input_bg": "#1e1e1e",
    "input_border": "#4a4a50",
    "input_focus_border": "#6ca0e6",
    "section_title": "#aaaaaa",
    "scrollbar_bg": "#2a2a2d",
    "scrollbar_handle": "#5a5a60",
    "scrollbar_handle_hover": "#6a6a70",
}

# --------------------------------------------------------------------------- palette

def _make_palette(colors):
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(colors["window"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(colors["window_text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(colors["base"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["alternate_base"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    pal.setColor(QPalette.ColorRole.BrightText, QColor(colors["bright_text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(colors["button"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(colors["button_text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(colors["highlight"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["highlighted_text"]))
    pal.setColor(QPalette.ColorRole.Link, QColor(colors["link"]))
    return pal


def _system_is_dark(app: QApplication) -> bool:
    window_color = app.palette().color(QPalette.ColorRole.Window)
    return window_color.lightness() < 128


def resolve_mode(mode: str, app: QApplication) -> str:
    """Turn 'system' into 'light' or 'dark' based on the OS palette."""
    if mode == "system":
        return "dark" if _system_is_dark(app) else "light"
    return mode


# --------------------------------------------------------------------------- stylesheet

def _stylesheet(colors):
    c = colors
    return f"""
        /* Base widgets ------------------------------------------------- */
        QWidget, QMainWindow {{
            background-color: {c['window']};
            color: {c['text']};
            font-size: 13px;
        }}
        QMainWindow::separator {{
            background: {c['border']};
            width: 2px;
            height: 2px;
        }}
        QSplitter::handle {{
            background: {c['border']};
        }}
        QSplitter::handle:horizontal {{
            width: 2px;
        }}
        QSplitter::handle:vertical {{
            height: 2px;
        }}

        /* Inputs ------------------------------------------------------- */
        QLineEdit {{
            background: {c['input_bg']};
            color: {c['text']};
            border: 1px solid {c['input_border']};
            border-radius: 4px;
            padding: 4px 8px;
            selection-background-color: {c['highlight']};
            selection-color: {c['highlighted_text']};
        }}
        QLineEdit:focus {{
            border: 1px solid {c['input_focus_border']};
        }}
        QLineEdit::placeholder {{
            color: {c['dim_text']};
        }}

        QComboBox {{
            background: {c['input_bg']};
            color: {c['text']};
            border: 1px solid {c['input_border']};
            border-radius: 4px;
            padding: 3px 8px;
            min-width: 120px;
        }}
        QComboBox:focus {{
            border: 1px solid {c['input_focus_border']};
        }}
        QComboBox QAbstractItemView {{
            background: {c['base']};
            color: {c['text']};
            border: 1px solid {c['border']};
            selection-background-color: {c['highlight']};
            selection-color: {c['highlighted_text']};
            outline: none;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}

        QTextEdit {{
            background: {c['base']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 4px;
        }}

        /* Buttons ------------------------------------------------------ */
        QPushButton {{
            background: {c['button']};
            color: {c['button_text']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 5px 12px;
            min-height: 26px;
        }}
        QPushButton:hover {{
            background: {c['accent_hover']};
            border-color: {c['accent']};
        }}
        QPushButton:pressed {{
            background: {c['shadow']};
        }}
        QPushButton:disabled {{
            color: {c['dim_text']};
            border-color: {c['mid']};
            background: {c['mid']};
        }}

        /* Avatar cards ------------------------------------------------- */
        QFrame {{
            background: {c['card_bg']};
            color: {c['text']};
            border: 1px solid {c['card_border']};
            border-radius: 6px;
        }}
        QFrame:hover {{
            border-color: {c['card_hover_border']};
            background: {c['card_hover_bg']};
        }}

        /* Checkboxes --------------------------------------------------- */
        QCheckBox {{
            color: {c['text']};
            spacing: 6px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid {c['border']};
            background: {c['base']};
            border-radius: 3px;
        }}
        QCheckBox::indicator:checked {{
            background: {c['highlight']};
            border-color: {c['highlight']};
        }}
        QCheckBox::indicator:indeterminate {{
            background: {c['mid']};
            border-color: {c['mid']};
        }}

        /* Labels ------------------------------------------------------- */
        QLabel {{
            color: {c['text']};
            background: transparent;
        }}

        /* Dialogs ------------------------------------------------------ */
        QDialog {{
            background: {c['window']};
            color: {c['text']};
        }}
        QDialog QLabel {{ color: {c['text']}; }}
        QDialogButtonBox QPushButton {{
            min-width: 80px;
        }}

        /* Menus -------------------------------------------------------- */
        QMenuBar {{
            background: {c['window']};
            color: {c['text']};
            border-bottom: 1px solid {c['border']};
            padding: 2px;
        }}
        QMenuBar::item {{
            background: transparent;
            padding: 4px 10px;
            border-radius: 3px;
        }}
        QMenuBar::item:selected {{
            background: {c['highlight']};
            color: {c['highlighted_text']};
        }}
        QMenu {{
            background: {c['base']};
            color: {c['text']};
            border: 1px solid {c['border']};
        }}
        QMenu::item {{
            padding: 5px 20px;
            border: none;
        }}
        QMenu::item:selected {{
            background: {c['highlight']};
            color: {c['highlighted_text']};
        }}
        QMenu::separator {{
            height: 1px;
            background: {c['border']};
            margin: 4px 8px;
        }}

        /* Lists -------------------------------------------------------- */
        QListWidget {{
            background: {c['sidebar_bg']};
            color: {c['text']};
            border: none;
            outline: none;
        }}
        QListWidget::item {{
            background: {c['item_bg']};
            color: {c['text']};
            border: 1px solid {c['item_border']};
            border-radius: 4px;
            padding: 6px 10px;
            margin: 2px 6px;
        }}
        QListWidget::item:selected {{
            background: {c['item_selected_bg']};
            border: 1px solid {c['item_selected_border']};
        }}
        QListWidget::item:hover {{
            background: {c['item_hover_bg']};
        }}

        /* Scroll bars -------------------------------------------------- */
        QScrollBar:vertical {{
            background: {c['scrollbar_bg']};
            width: 12px;
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {c['scrollbar_handle']};
            min-height: 30px;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {c['scrollbar_handle_hover']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background: {c['scrollbar_bg']};
            height: 12px;
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background: {c['scrollbar_handle']};
            min-width: 30px;
            border-radius: 6px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {c['scrollbar_handle_hover']};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}

        /* Tooltips ----------------------------------------------------- */
        QToolTip {{
            background: {c['base']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 4px 8px;
        }}

        /* Progress ----------------------------------------------------- */
        QProgressBar {{
            border: 1px solid {c['border']};
            border-radius: 4px;
            text-align: center;
            background: {c['base']};
            color: {c['text']};
        }}
        QProgressBar::chunk {{
            background: {c['highlight']};
            border-radius: 3px;
        }}

        /* Danger buttons ---------------------------------------------- */
        QPushButton[destructive="true"] {{
            background: {c['danger']};
            border-color: {c['danger']};
            color: {c['bright_text']};
        }}
        QPushButton[destructive="true"]:hover {{
            background: #b03a2e;
        }}
    """


# --------------------------------------------------------------------------- current theme state

CURRENT_COLORS = LIGHT


def current_colors() -> dict:
    """The colours of the currently applied theme."""
    return CURRENT_COLORS


# --------------------------------------------------------------------------- application

def apply_theme(app: QApplication, mode: str = "system") -> str:
    """Apply a theme to `app`. Returns the resolved mode ('light' or 'dark')."""
    global CURRENT_COLORS
    resolved = resolve_mode(mode, app)
    colors = LIGHT if resolved == "light" else DARK
    CURRENT_COLORS = colors
    app.setPalette(_make_palette(colors))
    app.setStyleSheet(_stylesheet(colors))
    return resolved


def palette_colour(app: QApplication, role: QPalette.ColorRole) -> QColor:
    """Read a colour out of the current application palette."""
    return app.palette().color(role)

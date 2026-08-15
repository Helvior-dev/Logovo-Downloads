def get_stylesheet():
    return """
    QMainWindow {
        background-color: #0b0e14;
    }
    QWidget {
        color: #e2e8f0;
        font-family: "Segoe UI", "Inter", sans-serif;
    }
    QTabWidget::pane {
        border: 0px;
        background: transparent;
    }
    QTabWidget::tab-bar {
        alignment: center;
    }
    QTabBar::tab {
        background-color: transparent;
        color: #64748b;
        padding: 8px 16px;
        margin: 4px 8px;
        border-radius: 8px;
        font-weight: bold;
        font-size: 13px;
        text-transform: uppercase;
        border: 1px solid transparent;
    }
    QTabBar::tab:selected {
        color: #ffffff;
        background-color: #1e293b;
        border: 1px solid #334155;
    }
    QTabBar::tab:hover:!selected {
        background-color: #0f172a;
        color: #94a3b8;
    }
    QPushButton {
        background-color: #1e293b;
        color: #ffffff;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #334155;
    }
    QPushButton:pressed {
        background-color: #475569;
    }
    QPushButton:disabled {
        background-color: #0f172a;
        color: #475569;
        border: 1px solid #1e293b;
    }
    QLineEdit, QComboBox {
        background-color: #0b0e14;
        border: 1px solid #1e293b;
        border-radius: 6px;
        padding: 8px;
        color: #ffffff;
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 30px;
        border: none;
        background: transparent;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid #94a3b8;
        border-bottom: 0px solid transparent;
        width: 0px;
        height: 0px;
        margin-right: 12px;
    }
    QLineEdit:focus, QComboBox:focus {
        border: 1px solid #1b7a78;
    }
    QComboBox QAbstractItemView {
        background-color: #0f172a;
        border: 1px solid #334155;
        border-radius: 6px;
        color: #e2e8f0;
        selection-background-color: #1e293b;
        selection-color: #38bdf8;
        padding: 4px;
        outline: none;
    }
    QComboBox QAbstractItemView::item {
        min-height: 26px;
        padding: 4px 8px;
    }
    QProgressBar {
        background-color: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 4px;
        text-align: center;
        color: transparent;
    }
    QProgressBar::chunk {
        background-color: #1b7a78;
        border-radius: 4px;
    }
    
    QScrollArea#QueueScrollArea {
        background: transparent;
        border: none;
    }
    QWidget#QueueContainer {
        background: transparent;
    }
    QWidget#QueueItemCard {
        background-color: #1e293b;
        border-radius: 8px;
        margin: 0px 5px;
    }
    QWidget#QueueItemCard:hover {
        background-color: #334155;
    }
    
    QScrollBar:vertical {
        border: none;
        background: #0f172a;
        width: 8px;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical {
        background: #475569;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical:hover {
        background: #64748b;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
    QLabel {
        color: #94a3b8;
    }
    QWidget:disabled {
        color: #475569;
    }
    QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {
        color: #475569;
    }
    QHeaderView::section {

        background-color: transparent;
        color: #94a3b8;
        padding: 5px;
        border: none;
        border-bottom: 1px solid #1e293b;
        font-weight: bold;
    }
    QTableWidget {
        background-color: #0b0e14;
        gridline-color: transparent;
        border: none;
        outline: none;
    }
    QTableWidget::item {
        padding: 8px 5px;
        border-bottom: 1px solid #1e293b;
    }
    QTableWidget::item:selected {
        background-color: #1e293b;
    }
    QCheckBox {
        color: #e2e8f0;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid #334155;
        background-color: #0b0e14;
    }
    QCheckBox::indicator:checked {
        background-color: #1b7a78;
        border: 1px solid #1b7a78;
    }
    QRadioButton {
        color: #e2e8f0;
    }
    QRadioButton::indicator {
        width: 16px;
        height: 16px;
        border-radius: 9px;
        border: 1px solid #334155;
        background-color: #0b0e14;
    }
    QRadioButton::indicator:checked {
        background-color: #1b7a78;
        border: 4px solid #0b0e14;
    }
    """

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
    QProgressBar {
        background-color: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 4px;
        text-align: center;
        color: transparent;
    }
    QProgressBar::chunk {
        background-color: #1b7a78;
        border-radius: 3px;
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

        background-color: #0f172a;
        color: #94a3b8;
        padding: 5px;
        border: 1px solid #1e293b;
    }
    QTableWidget {
        background-color: #0b0e14;
        gridline-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 6px;
    }
    QTableWidget::item {
        padding: 5px;
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

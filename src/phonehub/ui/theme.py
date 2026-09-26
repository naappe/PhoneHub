APP_STYLE = """
QWidget {
    background: #f4f7fb;
    color: #172033;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QWidget#Root {
    background: #f4f7fb;
}
QScrollArea {
    border: none;
    background: #f4f7fb;
}
QLabel {
    background: transparent;
}
QLabel#PageTitle {
    font-size: 30px;
    font-weight: 700;
    color: #111827;
}
QLabel#Muted {
    color: #667085;
}
QLabel#Status {
    font-size: 20px;
    font-weight: 700;
    color: #137a4b;
}
QLabel#CardTitle {
    font-size: 15px;
    font-weight: 700;
    color: #202939;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #dfe5ee;
    border-radius: 16px;
}
QPushButton {
    min-height: 38px;
    padding: 0 16px;
    background: #ffffff;
    color: #344054;
    border: 1px solid #cfd7e3;
    border-radius: 10px;
    font-weight: 600;
}
QPushButton:hover {
    background: #f8fafc;
    border-color: #98a7bc;
}
QPushButton:pressed {
    background: #eef2f7;
}
QPushButton#Primary {
    background: #2563eb;
    color: #ffffff;
    border: 1px solid #2563eb;
}
QPushButton#Primary:hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}
QLineEdit {
    min-height: 38px;
    padding: 0 12px;
    background: #ffffff;
    color: #172033;
    border: 1px solid #cfd7e3;
    border-radius: 10px;
    selection-background-color: #2563eb;
}
QLineEdit:focus {
    border: 1px solid #2563eb;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: #c5ceda;
    min-height: 36px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
"""

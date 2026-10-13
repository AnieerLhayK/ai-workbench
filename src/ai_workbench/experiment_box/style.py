"""Dark native design tokens shared by the window and its forms."""
STYLE = """
QWidget { background: #17191d; color: #eef1f5; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 17px; }
QMainWindow, QDialog { background: #17191d; }
QWidget#header { border-bottom: 1px solid #343a43; }
QLabel#brand { font-size: 22px; font-weight: 600; }
QLabel#heading { font-size: 32px; font-weight: 700; }
QLabel#sectionHeading { font-size: 23px; font-weight: 600; }
QLabel#muted, QLabel#hint { color: #a7afbb; }
QLabel#error { color: #f3a4a4; }
QWidget#sidebar { background: #1e2126; border-right: 1px solid #343a43; }
QFrame#panel { background: #20242a; border: 1px solid #343a43; border-radius: 8px; }
QFrame#panel QLabel { background: transparent; }
QLineEdit, QPlainTextEdit, QComboBox { background: #1e2126; border: 1px solid #414954; border-radius: 6px; padding: 10px 12px; selection-background-color: #397a8d; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid #61b9d0; }
QPushButton { background: #252a31; border: 1px solid #48515d; border-radius: 6px; padding: 11px 20px; font-size: 17px; }
QPushButton:hover { background: #303841; }
QPushButton:focus { border: 2px solid #61b9d0; }
QPushButton#primary { background: #61b9d0; color: #10212a; border: 1px solid #61b9d0; font-weight: 600; }
QPushButton#primary:hover { background: #79c8dc; }
QPushButton:disabled { background: #262c32; color: #76818d; border-color: #343a43; }
QPushButton#primary:disabled { background: #262c32; color: #76818d; border-color: #343a43; }
QListWidget { background: #1e2126; border: none; outline: none; }
QListWidget::item { border-bottom: 1px solid #343a43; padding: 0; }
QListWidget::item:selected { background: #263640; border-left: 4px solid #61b9d0; }
QListWidget::item:hover:!selected { background: #252b32; }
QScrollArea { border: none; background: #17191d; }
QScrollBar:vertical { background: #17191d; width: 10px; }
QScrollBar::handle:vertical { background: #414954; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialogButtonBox { background: transparent; }
"""

"""Dark native design tokens shared by the window and its forms."""
STYLE = """
QWidget { background: #101b27; color: #eef1f5; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 16px; }
QMainWindow, QDialog { background: #101b27; }
QWidget#header { border-bottom: 1px solid #343a43; }
QLabel#brand { font-size: 22px; font-weight: 600; }
QLabel#heading { font-size: 32px; font-weight: 700; }
QLabel#sectionHeading { font-size: 23px; font-weight: 600; }
QLabel#muted, QLabel#hint { color: #a7afbb; }
QLabel#error { color: #f3a4a4; }
QWidget#sidebar { background: #121f2c; border-right: 1px solid #2d465a; }
QWidget#assistantPanel { background: #111e2c; border-left: 1px solid #2d465a; }
QLabel#bubble { background: #202e3e; border-radius: 8px; padding: 16px; }
QFrame#panel { background: #142231; border: 1px solid #2d465a; border-radius: 6px; }
QPushButton:checked { background: #173447; color: #61d4f1; border: 1px solid #61d4f1; }
QFrame#panel QLabel { background: transparent; }
QLineEdit, QPlainTextEdit, QComboBox { background: #121e2b; border: 1px solid #30475a; border-radius: 6px; padding: 10px 12px; selection-background-color: #397a8d; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid #61b9d0; }
QPushButton { background: #152331; border: 1px solid #30475a; border-radius: 6px; padding: 9px 16px; font-size: 16px; }
QPushButton:hover { background: #303841; }
QPushButton:focus { border: 2px solid #61b9d0; }
QPushButton#primary { background: #61b9d0; color: #10212a; border: 1px solid #61b9d0; font-weight: 600; }
QPushButton#primary:hover { background: #79c8dc; }
QPushButton:disabled { background: #262c32; color: #76818d; border-color: #343a43; }
QPushButton#primary:disabled { background: #262c32; color: #76818d; border-color: #343a43; }
QListWidget { background: #121f2c; border: none; outline: none; }
QListWidget::item { border-bottom: 1px solid #343a43; padding: 0; }
QListWidget::item:selected { background: #183142; border: 1px solid #61cbe8; border-radius: 6px; }
QListWidget::item:hover:!selected { background: #252b32; }
QScrollArea { border: none; background: #101b27; }
QScrollBar:vertical { background: #101b27; width: 8px; }
QScrollBar::handle:vertical { background: #414954; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialogButtonBox { background: transparent; }
"""

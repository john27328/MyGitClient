from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class OperationOutputDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 420)
        self.status = QLabel()
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setObjectName("operationOutputEdit")
        copy_button = QPushButton("Copy all")
        copy_button.clicked.connect(self._copy_all)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(copy_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.output)
        layout.addLayout(buttons)

    def update_output(self, status: str, output: str) -> None:
        self.status.setText(status)
        scrollbar = self.output.verticalScrollBar()
        at_end = scrollbar.value() >= scrollbar.maximum() - 2
        self.output.setPlainText(output or "Waiting for output…")
        if at_end:
            scrollbar.setValue(scrollbar.maximum())

    def _copy_all(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.output.toPlainText())

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from mygitclient import __version__
from mygitclient.updates import (
    UpdateChecker,
    UpdateDownloader,
    UpdateInfo,
    launch_updater,
    portable_install_directory,
)


class UpdateController(QObject):
    """Owns update checks, downloads, and the portable-install flow."""

    def __init__(self, parent_widget: QWidget, *, set_status: Callable[[str], None]) -> None:
        super().__init__(parent_widget)
        self._parent_widget = parent_widget
        self._set_status = set_status
        self._checker = UpdateChecker(self)
        self._downloader = UpdateDownloader(self)
        self._progress: QProgressDialog | None = None
        self._manual_check = False
        self._checker.update_available.connect(self._update_available)
        self._checker.up_to_date.connect(self._update_is_current)
        self._checker.failed.connect(self._update_check_failed)
        self._downloader.progress.connect(self._download_progress)
        self._downloader.ready.connect(self._downloaded)
        self._downloader.failed.connect(self._download_failed)
        self._downloader.cancelled.connect(self._download_cancelled)

    @Slot()
    def check_automatically(self) -> None:
        self._manual_check = False
        self._checker.check()

    @Slot()
    def check_manually(self) -> None:
        self._manual_check = True
        self._set_status("Checking for updates…")
        self._checker.check()

    @Slot(object)
    def _update_available(self, value: object) -> None:
        if not isinstance(value, UpdateInfo):
            return
        self._manual_check = False
        install_directory = portable_install_directory()
        can_install = (
            install_directory is not None
            and value.archive_url is not None
            and value.checksum_url is not None
        )
        if not can_install:
            answer = QMessageBox.question(
                self._parent_widget,
                "Update available",
                f"MyGitClient {value.version} is available.\n\n"
                f"You are using {__version__}. Open the download page?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(value.page_url))
            return
        answer = QMessageBox.question(
            self._parent_widget,
            "Update available",
            f"MyGitClient {value.version} is available.\n\n"
            "Download it, install it, and restart MyGitClient?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        progress = QProgressDialog("Downloading update…", "Cancel", 0, 0, self._parent_widget)
        progress.setObjectName("updateDownloadProgress")
        progress.setWindowTitle("Updating MyGitClient")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._downloader.cancel)
        self._progress = progress
        progress.show()
        self._downloader.download(value)

    @Slot(int, int)
    def _download_progress(self, received: int, total: int) -> None:
        progress = self._progress
        if progress is None:
            return
        if total <= 0:
            progress.setRange(0, 0)
        else:
            progress.setRange(0, total)
            progress.setValue(received)
        progress.setLabelText(f"Downloading update… {received / 1024 / 1024:.1f} MB")

    @Slot(object)
    def _downloaded(self, value: object) -> None:
        self._close_progress()
        if not isinstance(value, Path):
            return
        install_directory = portable_install_directory()
        if install_directory is None:
            QMessageBox.warning(
                self._parent_widget, "Update failed", "This installation is not portable."
            )
            return
        if not launch_updater(value, install_directory):
            QMessageBox.warning(
                self._parent_widget, "Update failed", "Could not start the update installer."
            )
            return
        application = QApplication.instance()
        if application is not None:
            application.quit()

    @Slot(str)
    def _download_failed(self, message: str) -> None:
        self._close_progress()
        QMessageBox.warning(self._parent_widget, "Update failed", message)

    @Slot()
    def _download_cancelled(self) -> None:
        self._close_progress()
        self._set_status("Update cancelled")

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    @Slot()
    def _update_is_current(self) -> None:
        if self._manual_check:
            QMessageBox.information(
                self._parent_widget,
                "No updates",
                f"MyGitClient {__version__} is the latest version.",
            )
        self._manual_check = False

    @Slot(str)
    def _update_check_failed(self, message: str) -> None:
        if self._manual_check:
            QMessageBox.warning(self._parent_widget, "Update check failed", message)
        self._manual_check = False

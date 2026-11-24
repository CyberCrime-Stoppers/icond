"""icond_gui.py — PySide6 window for icond, with resolution-change autosave.

Structure
---------
MainWindow
 ├─ Profile list (left)      : saved layouts w/ resolution + timestamp
 ├─ Buttons (right column)   : Save new / Restore / Delete / Rename / Refresh
 └─ Bottom bar                : session info + resolution-change autosave state

The resolution watcher polls QScreen geometry every 3 s (a QTimer, no
external dependencies). If the combined screen fingerprint changes —
monitor plugged/unplugged, resolution switch — it silently saves a
profile named `auto-<timestamp>-<fingerprint>` so nothing is ever lost.
DesktopOK behaves the same way on Windows.
"""

import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView,
    QInputDialog, QFileDialog,
)

import icond_backend as backend
import icond_profiles as profiles


AUTOSAVE_PREFIX = "auto-"
POLL_SECONDS = 3


class ResolutionWatcher(QTimer):
    """Polls the combined screen geometry; emits `changed` on any difference."""

    changed = Signal(str, str)  # (old_fingerprint, new_fingerprint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last: str | None = None
        self.setInterval(POLL_SECONDS * 1000)
        self.timeout.connect(self._poll)

    @staticmethod
    def fingerprint(app) -> str:
        screens = app.screens()
        parts = []
        for s in screens:
            g = s.geometry()
            parts.append(f"{s.name()}:{g.width()}x{g.height()}@{s.devicePixelRatio()}")
        return ", ".join(parts)

    @staticmethod
    def summary(app) -> tuple[str, str]:
        screens = app.screens()
        sizes = ", ".join(
            f"{s.name()} {s.geometry().width()}x{s.geometry().height()}"
            for s in screens
        )
        fp = ResolutionWatcher.fingerprint(app)
        return sizes, fp

    def begin(self, app):
        self._last = self.fingerprint(app)
        self.start()

    def _poll(self):
        cur = self.fingerprint(QApplication_instance())
        if cur != self._last:
            old = self._last or "?"
            self._last = cur
            self.changed.emit(old, cur)


def QApplication_instance():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("icond — Desktop Icon Layout Manager (KDE Plasma)")
        self.resize(780, 480)
        self.autosaved_label = None
        self._build_ui()
        self.watcher = ResolutionWatcher(self)
        self.watcher.changed.connect(self.on_resolution_changed)
        self.watcher.begin(QApplication_instance())
        self.refresh()

    # ---------------- UI construction ----------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        header = QLabel(
            "Save and restore your desktop icon layout — the Linux DesktopOK."
        )
        f = QFont()
        f.setBold(True)
        header.setFont(f)
        outer.addWidget(header)

        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

        # Left: profile table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Profile", "Resolution", "Saved (local)", "Status"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._restore_selected)
        body.addWidget(self.table, stretch=1)

        # Right: button column
        btns = QVBoxLayout()
        b_save = QPushButton("💾 Save current layout…")
        b_restore = QPushButton("♻ Restore selected")
        b_export = QPushButton("📤 Export selected…")
        b_rename = QPushButton("✏ Rename selected")
        b_delete = QPushButton("🗑 Delete selected")
        b_refresh = QPushButton("🔄 Refresh list")
        for w in (b_save, b_restore, b_export, b_rename, b_delete, b_refresh):
            btns.addWidget(w)
        btns.addStretch(1)
        self.chk_autosave = QPushButton("Autosave: ON (click to disable)")
        self.chk_autosave.setToolTip(
            "When a monitor is added/removed or the resolution changes, "
            "icond silently saves the icon layout first so nothing is lost."
        )
        btns.addWidget(self.chk_autosave)
        body.addLayout(btns)

        b_save.clicked.connect(self.save_dialog)
        b_restore.clicked.connect(self._restore_selected)
        b_export.clicked.connect(self.export_selected)
        b_rename.clicked.connect(self.rename_selected)
        b_delete.clicked.connect(self.delete_selected)
        b_refresh.clicked.connect(self.refresh)
        self.chk_autosave.clicked.connect(self.toggle_autosave)

        # Bottom status bar
        bottom = QHBoxLayout()
        self.status = QLabel("Starting…")
        bottom.addWidget(self.status, stretch=1)
        outer.addLayout(bottom)

        self.autosave_enabled = True

    # ---------------- helpers ----------------

    def _screen_summary(self) -> tuple[str, str]:
        return ResolutionWatcher.summary(QApplication_instance())

    def _selected_name(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).text()

    def refresh(self):
        self.table.setRowCount(0)
        rows = profiles.list_profiles()
        sizes, fp = self._screen_summary()
        for meta in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(meta["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(meta["resolution"]))
            self.table.setItem(r, 2, QTableWidgetItem(meta["saved_at"]))
            tag = "MATCHES NOW" if meta["geometry"] == fp else ""
            self.table.setItem(r, 3, QTableWidgetItem(tag))
        self.table.sortItems(2, Qt.SortOrder.DescendingOrder)
        session = "KDE Plasma" if backend.is_plasma_session() else "NOT PLASMA!"
        self.status.setText(
            f"Session: {session}   |   Screens: {sizes}   |   Profiles: {len(rows)}"
        )

    # ---------------- actions ----------------

    def save_dialog(self):
        if not backend.is_plasma_session():
            QMessageBox.warning(
                self, "Not a Plasma session",
                "icond can only save layouts from inside a KDE Plasma session."
            )
            return
        sizes, fp = self._screen_summary()
        name, ok = QInputDialog.getText(
            self, "Save layout",
            f"Profile name:\n(current screens: {sizes})",
        )
        if not ok:
            return
        try:
            text = backend.snapshot_appletsrc()
            profiles.save_profile(name, text, sizes, fp)
        except (backend.IcondError, profiles.ProfileError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.refresh()
        self.status.setText(f"Saved profile '{name}' ✔")

    def _restore_selected(self):
        name = self._selected_name()
        if not name:
            self.status.setText("Select a profile first.")
            return
        doc = None
        try:
            doc = profiles.load_profile(name)
        except profiles.ProfileError:
            pass  # fall through to confirmation below
        reply = QMessageBox.question(
            self, "Restore layout",
            f"Restore layout '{name}'?\n\n"
            "plasmashell will restart and the desktop will flicker briefly.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if doc is None:
                doc = profiles.load_profile(name)
            bak = backend.restore_appletsrc(doc["appletsrc"])
        except (backend.IcondError, profiles.ProfileError) as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        msg = f"Restored '{name}'."
        if bak:
            msg += f"\nSafety backup of the previous layout: {bak}"
        QMessageBox.information(self, "Restore done", msg)
        self.refresh()

    def export_selected(self):
        name = self._selected_name()
        if not name:
            self.status.setText("Select a profile first.")
            return
        suggested = f"{name}.kdl"
        home = os.path.expanduser("~")
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export profile",
            os.path.join(home, suggested),
            "icond profile (*.kdl)",
        )
        if not dest:
            return
        try:
            out = profiles.export_profile(name, dest)
        except profiles.ProfileError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status.setText(f"Exported '{name}' → {out}")

    def rename_selected(self):
        name = self._selected_name()
        if not name:
            return
        new, ok = QInputDialog.getText(self, "Rename", f"New name for '{name}':", text=name)
        if not ok or not new or new == name:
            return
        try:
            profiles.rename_profile(name, new)
        except profiles.ProfileError as exc:
            QMessageBox.critical(self, "Rename failed", str(exc))
            return
        self.refresh()

    def delete_selected(self):
        name = self._selected_name()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete profile", f"Permanently delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        profiles.delete_profile(name)
        self.refresh()

    def toggle_autosave(self):
        self.autosave_enabled = not self.autosave_enabled
        self.chk_autosave.setText(
            "Autosave: ON (click to disable)" if self.autosave_enabled
            else "Autosave: OFF (click to enable)"
        )
        if self.autosave_enabled:
            self.watcher.start()
        else:
            self.watcher.stop()

    def on_resolution_changed(self, old_fp: str, new_fp: str):
        if not self.autosave_enabled:
            self.status.setText(
                f"Resolution changed ({new_fp}) but autosave is disabled — "
                "save manually to protect your layout."
            )
            return
        try:
            text = backend.snapshot_appletsrc()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            name = f"{AUTOSAVE_PREFIX}{stamp}"
            profiles.save_profile(name, text, new_fp, new_fp)
            self.status.setText(
                f"Autosaved layout '{name}' — resolution changed to {new_fp}"
            )
        except (backend.IcondError, profiles.ProfileError, OSError):
            # Never crash the GUI over an autosave; surface it gently.
            self.status.setText("Autosave FAILED — save manually to protect your layout.")

    def closeEvent(self, event: QCloseEvent):
        self.watcher.stop()
        super().closeEvent(event)

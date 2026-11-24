#!/usr/bin/env python3
"""icond — Icon Layout Manager for KDE Plasma (Linux DesktopOK equivalent).

Saves and restores the desktop icon layout by snapshotting Plasma's
desktop configuration file and bouncing plasmashell to apply changes.
"""

import os
import sys

# Make flat module imports work no matter where the repo is launched from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from icond_gui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("icond")
    app.setOrganizationName("CyberCrime-Stoppers")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

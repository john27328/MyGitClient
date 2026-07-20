from __future__ import annotations

import sys

from PySide6.QtCore import QTimer

from mygitclient.app import create_application


def main() -> int:
    app, window = create_application(sys.argv)
    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(750, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

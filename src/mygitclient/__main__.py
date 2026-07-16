from __future__ import annotations

import sys

from mygitclient.app import create_application


def main() -> int:
    app, window = create_application(sys.argv)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())


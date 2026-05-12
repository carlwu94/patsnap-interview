from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    uvicorn.run("app.web.main:app", host="127.0.0.1", port=9876, reload=False)


if __name__ == "__main__":
    main()

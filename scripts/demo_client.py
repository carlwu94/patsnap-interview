from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> int:
    base_url = "http://127.0.0.1:9876"
    with httpx.Client(timeout=10.0) as client:
        health = client.get(f"{base_url}/api/health").json()
        search = client.post(
            f"{base_url}/api/search",
            json={"keyword": "锂离子电池", "limit": 3},
        ).json()
        chat = client.post(
            f"{base_url}/api/chat",
            json={"message": "最热门的5个IPC分类号是什么？"},
        ).json()

    print("Health:")
    print(json.dumps(health, ensure_ascii=False, indent=2))
    print("\nSearch:")
    print(json.dumps(search, ensure_ascii=False, indent=2))
    print("\nChat:")
    print(json.dumps(chat, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

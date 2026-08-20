import json
from pathlib import Path

from easyaudit_next.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    contract = json.loads((ROOT / "openapi" / "openapi.json").read_text(encoding="utf-8"))
    runtime = create_app().openapi()

    assert runtime["openapi"] == contract["openapi"]
    assert runtime["info"]["title"] == contract["info"]["title"]
    assert runtime["info"]["version"] == contract["info"]["version"]

    for path, methods in contract["paths"].items():
        for method, operation in methods.items():
            actual = runtime["paths"][path][method]
            assert actual["operationId"] == operation["operationId"]
            assert actual["tags"] == operation["tags"]

    print("OpenAPI contract check passed.")


if __name__ == "__main__":
    main()

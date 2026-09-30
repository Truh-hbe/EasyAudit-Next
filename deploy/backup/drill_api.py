#!/usr/bin/env python3
"""API side of the restore drill: seed business data through the gateway, check it after restore.

Stdlib only. Talks to the real HTTPS API; the session cookie is handled by hand because the
cookie is `__Host-`/Secure and must not depend on the client's cookie-jar policy.

  drill_api.py prepare-objects DIR              write deterministic test objects + objects.json
  drill_api.py whoami   --base URL ...          print the admin's organization id
  drill_api.py seed     --base URL ... --objects objects.json --state state.json
  drill_api.py check    --base URL ... --state state.json
"""

import argparse
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

COOKIE = "__Host-easyaudit_session"
OWNER_LOGIN = "drill-owner"
OWNER_PASSWORD = "drill-owner-password-1"
OBJECT_COUNT = 3


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, base: str, cacert: str | None) -> None:
        self.base = base.rstrip("/")
        self.context = ssl.create_default_context(cafile=cacert) if cacert else None
        if self.context is not None:
            # The drill trusts one throwaway self-signed certificate; skip strict extension checks.
            self.context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        self.token: str | None = None
        # Never route drill traffic through an ambient (system) proxy.
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=self.context)
        )

    def request(self, method: str, path: str, body: object | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"content-type": "application/json"}
        if self.token:
            headers["cookie"] = f"{COOKIE}={self.token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=15) as resp:
                raw = resp.read()
                set_cookie = resp.headers.get_all("set-cookie") or []
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ApiError(f"{method} {path} -> {exc.code}: {detail}") from exc
        for value in set_cookie:
            if value.startswith(COOKIE + "="):
                self.token = value.split(";", 1)[0].split("=", 1)[1]
        return json.loads(raw) if raw else None

    def login(self, login_name: str, password: str) -> Any:
        self.token = None
        return self.request(
            "POST", "/api/v1/auth/login", {"login_name": login_name, "password": password}
        )


def object_specs(count: int = OBJECT_COUNT) -> list[dict[str, Any]]:
    """Deterministic test objects; keys look like the server-generated keys of Pilot-4."""
    specs = []
    for index in range(count):
        content = f"restore-drill evidence object {index}\n".encode() * (50 + index * 700)
        specs.append(
            {
                "storage_key": f"drill/{index:02d}/{hashlib.sha256(content).hexdigest()[:16]}.txt",
                "original_name": f"drill-evidence-{index}.txt",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content": content,
            }
        )
    return specs


def prepare_objects(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    listing = []
    for spec in object_specs():
        path = directory / spec["storage_key"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(spec.pop("content"))
        listing.append(spec)
    (directory.parent / "objects.json").write_text(json.dumps(listing, indent=2))


def whoami(client: Client, login: str, password: str) -> None:
    print(client.login(login, password)["user"]["organization_id"])


def seed(client: Client, args: argparse.Namespace) -> None:
    objects = json.loads(Path(args.objects).read_text())
    admin = client.login(args.login, args.password)["user"]
    department = client.request("POST", "/api/v1/admin/departments", {"name": "Drill Department"})
    owner = client.request(
        "POST",
        "/api/v1/admin/users",
        {
            "display_name": "Drill Owner",
            "login_name": OWNER_LOGIN,
            "initial_password": OWNER_PASSWORD,
            "primary_department_id": department["id"],
            "must_change_password": False,
        },
    )
    start = datetime.now(UTC)
    plan = client.request(
        "POST",
        "/api/v1/review-plans",
        {
            "title": "Restore drill plan",
            "planned_start_at": start.isoformat(),
            "planned_end_at": (start + timedelta(days=30)).isoformat(),
        },
    )
    case = client.request(
        "POST",
        "/api/v1/review-cases",
        {
            "plan_id": plan["id"],
            "scenario_key": "process_review",
            "scenario_version": 1,
            "title": "Restore drill case",
            "scenario_data": {"area_code": "ASSY", "review_type": "routine"},
        },
    )
    for action in ("schedule", "start"):
        client.request("POST", f"/api/v1/review-cases/{case['id']}/transitions", {"action": action})
    finding = client.request(
        "POST",
        f"/api/v1/review-cases/{case['id']}/findings",
        {
            "title": "Restore drill finding",
            "description": "Created through the gateway before the backup",
            "severity": "high",
            "scenario_data": {"issue_type": "control_gap", "project_category": "assembly"},
        },
    )
    for kind, actor_id, role in (
        ("user", owner["id"], "owner"),
        ("department", department["id"], "responsible_department"),
    ):
        client.request(
            "POST",
            f"/api/v1/findings/{finding['id']}/participants",
            {"actor_kind": kind, "actor_id": actor_id, "role_key": role},
        )
    client.request("POST", f"/api/v1/findings/{finding['id']}/transitions", {"action": "issue"})

    client.login(OWNER_LOGIN, OWNER_PASSWORD)
    action_item = client.request(
        "POST", f"/api/v1/findings/{finding['id']}/actions", {"title": "Restore drill action"}
    )
    client.request(
        "POST",
        f"/api/v1/action-items/{action_item['id']}/assignees",
        {"actor_kind": "user", "actor_id": owner["id"], "role": "primary"},
    )
    for action in ("start", "complete"):
        client.request(
            "POST", f"/api/v1/action-items/{action_item['id']}/transitions", {"action": action}
        )
    evidences = [
        client.request(
            "POST",
            f"/api/v1/action-items/{action_item['id']}/evidences",
            {**spec, "content_type": "text/plain", "description": "restore drill object"},
        )
        for spec in objects
    ]
    state = {
        "admin_user_id": admin["id"],
        "plan_id": plan["id"],
        "case": {"id": case["id"], "title": case["title"]},
        "finding": {"id": finding["id"], "title": finding["title"]},
        "action_item_id": action_item["id"],
        "evidences": [
            {k: e[k] for k in ("id", "storage_key", "sha256", "size_bytes")} for e in evidences
        ],
    }
    Path(args.state).write_text(json.dumps(state, indent=2))
    print(f"seeded case={case['id']} finding={finding['id']} evidences={len(evidences)}")


def check(client: Client, args: argparse.Namespace) -> None:
    state = json.loads(Path(args.state).read_text())
    problems: list[str] = []

    def expect(label: str, actual: object, expected: object) -> None:
        if actual != expected:
            problems.append(f"{label}: expected {expected!r}, got {actual!r}")

    me = client.login(args.login, args.password)["user"]
    expect("admin user id", me["id"], state["admin_user_id"])
    client.login(OWNER_LOGIN, OWNER_PASSWORD)  # a second, non-admin account also survives
    client.login(args.login, args.password)
    case = client.request("GET", f"/api/v1/review-cases/{state['case']['id']}")
    expect("case id", case["id"], state["case"]["id"])
    expect("case title", case["title"], state["case"]["title"])
    finding = client.request("GET", f"/api/v1/findings/{state['finding']['id']}")
    expect("finding id", finding["id"], state["finding"]["id"])
    expect("finding title", finding["title"], state["finding"]["title"])
    # EXTENSION POINT (Pilot-4B): once the download endpoint exists, fetch every Evidence
    # through the API here and compare the downloaded bytes' sha256 with `sha256` below.
    evidences = client.request("GET", f"/api/v1/action-items/{state['action_item_id']}/evidences")
    expect(
        "evidence metadata",
        sorted((e["id"], e["storage_key"], e["sha256"], e["size_bytes"]) for e in evidences),
        sorted(
            (e["id"], e["storage_key"], e["sha256"], e["size_bytes"]) for e in state["evidences"]
        ),
    )
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(1)
    print("API check ok: login, case, finding, evidence metadata")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare-objects")
    prep.add_argument("directory", type=Path)
    for name in ("whoami", "seed", "check"):
        p = sub.add_parser(name)
        p.add_argument("--base", required=True)
        p.add_argument("--cacert")
        p.add_argument("--login", required=True)
        p.add_argument("--password", required=True)
        if name == "seed":
            p.add_argument("--objects", required=True)
        if name != "whoami":
            p.add_argument("--state", required=True)
    args = parser.parse_args()
    if args.command == "prepare-objects":
        prepare_objects(args.directory)
        return
    client = Client(args.base, args.cacert)
    if args.command == "whoami":
        whoami(client, args.login, args.password)
    elif args.command == "seed":
        seed(client, args)
    else:
        check(client, args)


if __name__ == "__main__":
    main()

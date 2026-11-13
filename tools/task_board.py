"""Manage the shared board instance. Agent reporting uses task_board_client.py."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board.store import BoardStore, BoardError
from task_board.projects import ProjectHub


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=lifecycle.DEFAULT_STATE)
    parser.add_argument(
        "--project",
        default=None,
        help="explicit project for project-scoped management",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--public-url", required=True)
    init.add_argument("--network-record", type=Path)
    init.add_argument("--tailnet-identity", type=Path)
    init.add_argument('--port',type=int,default=24710)
    adapter=sub.add_parser('import-json',help='Explicit project-specific JSON adapter')
    adapter.add_argument('--source',type=Path,required=True)
    for name in ("start", "stop", "serve", "status", "verify", "operator"):
        sub.add_parser(name)
    export = sub.add_parser("export")
    export.add_argument("--out", type=Path, required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--out", type=Path, required=True)
    invite = sub.add_parser("invite")
    invite.add_argument("--actor", required=True)
    invite.add_argument("--out", type=Path, required=True)
    invite.add_argument("--connect-ip")
    invite.add_argument("--role", choices=("agent", "reviewer"), default="agent")
    sub.add_parser("projects")
    project = sub.add_parser("project-add")
    project.add_argument("--id", required=True)
    project.add_argument("--name", required=True)
    project.add_argument("--description", required=True)
    catalog_export = sub.add_parser("catalog-export")
    catalog_export.add_argument("--out", type=Path, required=True)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--actor", required=True)
    revoke.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command in ('verify','operator','export','snapshot','invite','revoke','import-json') and not args.project:
        parser.error('此管理动作必须显式指定 --project')
    state = args.state.resolve()
    try:
        if args.command == "init":
            network = (
                lifecycle.read(args.network_record) if args.network_record else None
            )
            login = (
                lifecycle.read(args.tailnet_identity)["allowed_login"]
                if args.tailnet_identity
                else None
            )
            result = lifecycle.init_state(
                state, public_url=args.public_url, network=network, login=login,port=args.port
            )
        elif args.command=='import-json':
            from task_board.catalog import import_catalog
            hub=ProjectHub(state);identity=hub.resolve(lifecycle.read(state/'_private/admin.json')['token'])
            entries,source=import_catalog(args.source)
            result={'imported':hub.store(args.project).import_tasks(identity['actor'],entries,source),'source':source}
        elif args.command == "start":
            result = lifecycle.start(state)
        elif args.command == "stop":
            result = lifecycle.stop(state)
        elif args.command == "serve":
            lifecycle.run_service(state)
            return 0
        elif args.command == "status":
            result = lifecycle.read(state / "service.json")
            result["identity_matches"] = bool(lifecycle.exact_owner(result))
            result = {
                k: v
                for k, v in result.items()
                if k
                in (
                    "pid",
                    "created",
                    "ready",
                    "closed",
                    "public_url",
                    "identity_matches",
                    "purpose",
                    "started",
                )
            }
        elif args.command == "projects":
            hub = ProjectHub(state)
            identity = hub.resolve(
                lifecycle.read(state / "_private/admin.json")["token"]
            )
            result = {"projects": hub.list_projects(identity)}
        elif args.command == "catalog-export":
            hub = ProjectHub(state)
            identity = hub.resolve(
                lifecycle.read(state / "_private/admin.json")["token"]
            )
            result = hub.export_catalog(identity, args.out)
        elif args.command == "project-add":
            hub = ProjectHub(state)
            identity = hub.resolve(
                lifecycle.read(state / "_private/admin.json")["token"]
            )
            result = hub.create(
                identity,
                {"id": args.id, "name": args.name, "description": args.description},
            )
        elif args.command == "verify":
            hub = ProjectHub(state)
            result = {
                "project_id": args.project,
                **hub.store(args.project).verify(),
                "catalog": hub.verify(),
            }
        elif args.command == "operator":
            result = lifecycle.operator_portal(state, project=args.project)
        elif args.command == "export":
            result = ProjectHub(state).store(args.project).export_events(args.out)
        elif args.command == "snapshot":
            if args.out.exists():
                raise BoardError("快照目标已存在，拒绝覆盖历史文件", 409)
            result = ProjectHub(state).store(args.project).snapshot()
            result["project_id"] = args.project
            lifecycle.write(args.out, result)
            result = {
                "snapshot": str(args.out),
                "head": result["head"],
                "tasks": len(result["tasks"]),
            }
        elif args.command == "invite":
            if args.out.exists():
                raise BoardError("身份目标已存在，拒绝覆盖", 409)
            hub = ProjectHub(state)
            profile = lifecycle.read(state / "_private/admin.json")
            identity = hub.resolve(profile["token"])
            if not identity["global_admin"]:
                raise BoardError("需全局管理身份", 403)
            record = {
                **hub.invite(args.project, args.actor, args.role),
                "url": profile["url"],
            }
            if args.connect_ip:
                record["connect_ip"] = args.connect_ip
            lifecycle.write(args.out, record)
            result = {
                "invited": args.actor,
                "role": args.role,
                "project_id": args.project,
                "private_profile": str(args.out),
                "secret_printed": False,
            }
        elif args.command == "revoke":
            hub = ProjectHub(state)
            identity = hub.resolve(
                lifecycle.read(state / "_private/admin.json")["token"]
            )
            result = hub.revoke(identity, args.project, args.actor, args.reason)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except BoardError as exc:
        print(json.dumps({"error": str(exc), "status": exc.status}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

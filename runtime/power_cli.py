"""CLI entrypoint for scheduled power actions.

Usage (from project root):
  python -m runtime.power_cli start <process_name>
  python -m runtime.power_cli stop <process_name>
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="runtime.power_cli",
        description="Start or stop a managed process via the supervisor.",
    )
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("process_name")
    args = parser.parse_args(argv)

    # Import after parse so --help stays light; app applies gevent monkey-patch.
    from app import app
    from models.process import Process
    from runtime import init_runtime

    with app.app_context():
        process = Process.query.filter_by(name=args.process_name).first()
        if not process:
            print(f"Process not found: {args.process_name}", file=sys.stderr)
            return 1

        runtime = init_runtime(app, load_processes=False, docker_events=False)
        if args.action == "start":
            result = runtime.start(process.name, process.type)
        else:
            result = runtime.stop(process.name, process.type)

        if not result.get("success"):
            print(result.get("error") or "Power action failed", file=sys.stderr)
            return 1

        print(result.get("message") or f"{args.action} ok")
        return 0


if __name__ == "__main__":
    sys.exit(main())

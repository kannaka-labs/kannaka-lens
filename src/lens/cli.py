"""lens — watch a clip, write what was seen.

    python -m lens run CLIP [--project DIR] [--force]
    python -m lens show --project DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contract import StageAborted, run_pipeline, summarise
from .stages.media import STAGES as MEDIA_STAGES

PIPELINE = list(MEDIA_STAGES)


def _run(args: argparse.Namespace) -> int:
    source = Path(args.clip).expanduser().resolve()
    if not source.exists():
        print(f"lens: {source} does not exist", file=sys.stderr)
        return 2
    project = Path(args.project).expanduser().resolve() if args.project \
        else source.with_suffix("").parent / f"{source.stem}.lens"

    print(f"lens: {source.name} -> {project}", flush=True)
    try:
        record = run_pipeline(PIPELINE, project, source, force=args.force)
    except StageAborted as exc:
        sys.stdout.flush()
        print(f"lens: run aborted -- {exc}", file=sys.stderr)
        return 1
    print(summarise(record))
    return 0


def _show(args: argparse.Namespace) -> int:
    path = Path(args.project).expanduser().resolve() / "project.json"
    if not path.exists():
        print(f"lens: no project record at {path}", file=sys.stderr)
        return 2
    record = json.loads(path.read_text("utf-8"))
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(record["source"])
        print(summarise(record))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lens", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the pipeline over a clip")
    r.add_argument("clip")
    r.add_argument("--project", help="where to write the project (default: CLIP.lens)")
    r.add_argument("--force", action="store_true", help="redo stages already done")
    r.set_defaults(fn=_run)

    s = sub.add_parser("show", help="print an existing project record")
    s.add_argument("--project", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=_show)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

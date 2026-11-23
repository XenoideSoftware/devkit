"""Command-line entry point for the devkit task implementation."""

import argparse
import os
import sys
from pathlib import Path

from . import build, libs, quality, setup
from .config import Config, Context, parse_config, validate_config
from .util import DevkitError, fail, info


def _config(ctx, value):
    return ctx.config(value)


def _add_config(parser, help_text="Config <toolchain>-<flavor> (default: active/host)"):
    parser.add_argument("--config", "-c", default=None, help=help_text)


def _bool(text):
    if text is None:
        return False
    if isinstance(text, bool):
        return text
    return str(text).strip().lower() not in ("", "0", "false", "no", "off")


def _add_bool(parser, name, help_text=None):
    parser.add_argument(name, nargs="?", const=True, default=False, type=_bool,
                        help=help_text)



def build_parser():
    parser = argparse.ArgumentParser(prog="xenoide", description="Xenoide devkit tasks")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup")
    _add_bool(p, "--skip-doctor")

    sub.add_parser("sync")
    sub.add_parser("doctor")
    sub.add_parser("configs")

    p = sub.add_parser("use")
    p.add_argument("config")

    p = sub.add_parser("deps")
    _add_config(p)

    p = sub.add_parser("build")
    _add_config(p)
    p.add_argument("--target", default=None)

    p = sub.add_parser("test")
    _add_config(p)
    p.add_argument("--filter", default=None)

    p = sub.add_parser("clean")
    _add_config(p)
    _add_bool(p, "--all")

    p = sub.add_parser("lock")
    _add_config(p)

    p = sub.add_parser("format")
    _add_bool(p, "--check")
    p.add_argument("--file", action="append", default=None)

    p = sub.add_parser("tidy")
    _add_config(p)
    _add_bool(p, "--fix")
    _add_bool(p, "--full")
    p.add_argument("--file", default=None)

    p = sub.add_parser("cppcheck")
    _add_config(p)
    _add_bool(p, "--full")
    p.add_argument("--file", default=None)

    p = sub.add_parser("cmake-check")
    _add_config(p)

    p = sub.add_parser("sanitize")
    _add_config(p)
    p.add_argument("--kind", choices=["asan", "tsan"], default="asan")

    p = sub.add_parser("coverage")
    _add_config(p)
    p.add_argument("--export", choices=["text", "html", "csv"], default="text")
    p.add_argument("--check", default=None)
    p.add_argument("--output-dir", default=None)
    _add_bool(p, "--clean")

    p = sub.add_parser("mutation")
    _add_config(p)
    p.add_argument("--target", default=None)
    p.add_argument("--threshold", default=None)
    _add_bool(p, "--generate")
    _add_bool(p, "--clean")

    p = sub.add_parser("valgrind")
    _add_config(p)
    p.add_argument("--tool", default="memcheck",
                   choices=["memcheck", "helgrind", "drd", "callgrind",
                            "cachegrind", "massif"])
    p.add_argument("--target", default=None)
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("debug")
    _add_config(p)
    p.add_argument("target")
    p.add_argument("--debugger", choices=["gdb", "lldb"], default=None)
    p.add_argument("--test", dest="test_name", default=None)
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("debug-core")
    _add_config(p)
    p.add_argument("core", nargs="?", default=None)

    p = sub.add_parser("debug-launch-json")
    _add_config(p)

    p = sub.add_parser("editable-add")
    p.add_argument("path")

    p = sub.add_parser("editable-remove")
    p.add_argument("path")

    p = sub.add_parser("libs-create")
    p.add_argument("name")
    p.add_argument("--dir", default=None)

    p = sub.add_parser("release")
    p.add_argument("--name", default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    ctx = Context(os.getcwd())
    command = args.command

    try:
        if command == "setup":
            setup.setup(ctx, skip_doctor=args.skip_doctor)
        elif command == "sync":
            setup.sync(ctx)
        elif command == "doctor":
            setup.doctor(ctx)
        elif command == "configs":
            build.configs(ctx)
        elif command == "use":
            build.use(ctx, validate_config(parse_config(args.config)))
        elif command == "deps":
            build.deps(ctx, _config(ctx, args.config))
        elif command == "build":
            build.build(ctx, _config(ctx, args.config), target=args.target)
        elif command == "test":
            build.test(ctx, _config(ctx, args.config), filter=args.filter or None)
        elif command == "clean":
            if args.all:
                build.clean(ctx)
            else:
                build.clean(ctx, _config(ctx, args.config))
        elif command == "lock":
            cfg = parse_config(args.config) if args.config else None
            build.lock(ctx, cfg)
        elif command == "format":
            quality.format_sources(ctx, check=args.check, files=args.file)
        elif command == "tidy":
            quality.tidy(ctx, _config(ctx, args.config), fix=args.fix,
                         full=args.full, file=args.file or None)
        elif command == "cppcheck":
            quality.cppcheck(ctx, _config(ctx, args.config), full=args.full,
                             file=args.file or None)
        elif command == "cmake-check":
            quality.cmake_check(ctx, _config(ctx, args.config))
        elif command == "sanitize":
            cfg = parse_config(args.config) if args.config else None
            quality.sanitize(ctx, kind=args.kind, config=cfg)
        elif command == "coverage":
            cfg = parse_config(args.config) if args.config else None
            quality.coverage(ctx, config=cfg, export=args.export,
                             check=float(args.check) if args.check else None,
                             output_dir=args.output_dir or None, clean=args.clean)
        elif command == "mutation":
            cfg = parse_config(args.config) if args.config else None
            quality.mutation(ctx, config=cfg, target=args.target or None,
                             threshold=float(args.threshold) if args.threshold else None,
                             dry_run=args.generate,
                             clean=args.clean)
        elif command == "valgrind":
            cfg = parse_config(args.config) if args.config else None
            extra = [item for item in args.args if item != "--"]
            quality.valgrind(ctx, tool=args.tool, config=cfg, target=args.target or None,
                             args=extra)
        elif command == "debug":
            extra = [item for item in args.args if item != "--"]
            quality.debug(ctx, _config(ctx, args.config), args.target,
                          debugger=args.debugger or None, args=extra,
                          test_name=args.test_name or None)
        elif command == "debug-core":
            quality.debug_core(ctx, _config(ctx, args.config), core=args.core or None)
        elif command == "debug-launch-json":
            quality.launch_json(ctx, _config(ctx, args.config))
        elif command == "editable-add":
            libs.editable_add(ctx, args.path)
        elif command == "editable-remove":
            libs.editable_remove(ctx, args.path)
        elif command == "libs-create":
            libs.create_library(ctx, args.name, directory=args.dir)
        elif command == "release":
            libs.release(ctx, name=args.name)
        else:  # pragma: no cover - argparse enforces the set
            fail(f"unknown command {command}")
    except DevkitError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Dependency, build, test, clean, config-selection and lock tasks."""

import os
import shutil
from pathlib import Path

from .config import Config, print_configs, valid_configs_for_host, validate_config
from .util import capture, fail, info, run, warn


def deps(ctx, config):
    ctx.require_devkit()
    build = ctx.build_dir(config)
    build.mkdir(parents=True, exist_ok=True)
    run(["conan", *ctx.conan_args(config)], cwd=ctx.root)
    info(f"==> Dependencies ready for {config.name} in {build}")


def _configure_if_needed(ctx, config):
    cache = ctx.build_dir(config) / "CMakeCache.txt"
    if cache.is_file():
        return
    run(["cmake", "--preset", ctx.preset(config)], cwd=ctx.root)


def build(ctx, config, target=None):
    deps(ctx, config)
    _configure_if_needed(ctx, config)
    args = ["cmake", "--build", "--preset", ctx.preset(config), "--parallel"]
    if target:
        args += ["--target", target]
    run(args, cwd=ctx.root)


def test(ctx, config, filter=None):
    build(ctx, config)
    cmd = ["ctest", "--preset", ctx.preset(config), "--output-on-failure"]
    if filter:
        cmd += ["-R", filter]
    run(cmd, cwd=ctx.root)


def clean(ctx, config=None):
    if config is None:
        build_root = ctx.build_root
        if build_root.is_dir():
            shutil.rmtree(build_root)
            info(f"==> Removed {build_root}")
        return
    build_dir = ctx.build_dir(config)
    if build_dir.is_dir():
        shutil.rmtree(build_dir)
        info(f"==> Removed {build_dir}")


def configs(ctx):
    print_configs()


def use(ctx, config):
    validate_config(config)
    state = ctx.root / ".xenoide"
    state.mkdir(parents=True, exist_ok=True)
    (state / "active").write_text(config.name + "\n", encoding="utf-8")

    compile_commands = ctx.compile_commands(config)
    link = ctx.build_root / "compile_commands.json"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
    except OSError:
        pass
    if compile_commands.is_file():
        try:
            link.symlink_to(compile_commands)
        except OSError:
            shutil.copy2(compile_commands, link)
        info(f"==> Active config: {config.name} (compile_commands.json updated)")
    else:
        warn(f"{compile_commands} does not exist yet; run `mise run deps` for this config")
        info(f"==> Active config: {config.name}")


def _lock_args(ctx, config):
    args = ctx.conan_args(config)
    args = ["conan", "lock", "create"] + args[1:]
    return [item for item in args if item != "--build=missing"]


def lock(ctx, config=None):
    """Regenerate and merge conan.lock for every valid host config."""
    ctx.require_devkit()
    configs_to_lock = [validate_config(config)] if config else valid_configs_for_host()

    if len(configs_to_lock) == 1:
        cfg = configs_to_lock[0]
        build = ctx.build_dir(cfg)
        build.mkdir(parents=True, exist_ok=True)
        lock_path = build / "conan.lock"
        run([*_lock_args(ctx, cfg), f"--lockfile-out={lock_path}"], cwd=ctx.root)
        shutil.copy2(lock_path, ctx.root / "conan.lock")
        info(f"==> Wrote {ctx.root / 'conan.lock'}")
        return

    lockfiles = []
    for cfg in configs_to_lock:
        build = ctx.build_dir(cfg)
        build.mkdir(parents=True, exist_ok=True)
        lock_path = build / "conan.lock"
        run([*_lock_args(ctx, cfg), f"--lockfile-out={lock_path}"], cwd=ctx.root)
        if lock_path.is_file():
            lockfiles.append(lock_path)

    merged = ctx.root / "conan.lock"
    if not lockfiles:
        fail("no lockfiles were generated")
    if len(lockfiles) == 1:
        shutil.copy2(lockfiles[0], merged)
    else:
        args = ["conan", "lock", "merge"]
        for lockfile in lockfiles:
            args += ["--lockfile", str(lockfile)]
        args += ["--lockfile-out", str(merged)]
        run(args, cwd=ctx.root)
    info(f"==> Wrote merged {merged}")

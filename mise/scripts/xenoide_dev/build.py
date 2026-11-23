"""Dependency, build, test, clean, config-selection and lock tasks."""

import os
import re
import shutil
from pathlib import Path

from .config import (Config, print_configs, valid_configs_for_all_toolchains,
                     valid_configs_for_host, validate_config)
from .util import capture, fail, info, run, warn


def deps(ctx, config):
    ctx.require_devkit()
    build = ctx.build_dir(config)
    build.mkdir(parents=True, exist_ok=True)
    run(["conan", *ctx.conan_args(config)], cwd=ctx.root)
    info(f"==> Dependencies ready for {config.name} in {build}")


def _expected_cxx(config):
    if config.toolchain in ("clang", "clang-cl", "apple-clang", "msvc"):
        name = os.environ.get("XENOIDE_CXX", "clang++")
    elif config.toolchain in ("gcc", "mingw-gcc", "legacy-i686-gcc5"):
        name = os.environ.get("XENOIDE_CXX", "g++")
    else:
        return None
    return shutil.which(name)


def _cached_compiler(build):
    cache = build / "CMakeCache.txt"
    if cache.is_file():
        for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("CMAKE_CXX_COMPILER:"):
                return line.split("=", 1)[1].strip()
    for candidate in build.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"):
        match = re.search(r'set\(CMAKE_CXX_COMPILER "([^"]+)"\)',
                          candidate.read_text(encoding="utf-8", errors="replace"))
        if match:
            return match.group(1)
    return None


def _compiler_changed(config, build):
    """True when the build tree was configured with a different compiler.

    CMake cannot switch compilers in an existing tree; the toolchain's
    `set(... CACHE)` leaves the old path in place. A stale compiler plus a
    different Mull/LLVM major crashes clang, so reconfigure from scratch.
    """
    expected = _expected_cxx(config)
    if not expected:
        return False
    actual = _cached_compiler(build)
    if not actual:
        return False
    try:
        return os.path.realpath(actual) != os.path.realpath(expected)
    except OSError:
        return True


def _configure_if_needed(ctx, config):
    build = ctx.build_dir(config)
    cache = build / "CMakeCache.txt"
    # Always let CMake re-run the configure step: `conan install` rewrites the
    # generators (new package folders, option changes) without necessarily
    # touching conan_toolchain.cmake, and a `CMakeCache.txt` alone never
    # proves that the tree still matches the current graph (C1).
    fresh = _compiler_changed(config, build)
    args = ["cmake", "--preset", ctx.preset(config)]
    if fresh and cache.is_file():
        info(f"==> Compiler changed for {config.name}; reconfiguring from scratch")
        args.append("--fresh")
    run(args, cwd=ctx.root)


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
    # A lock is being *created*: feeding the previous one back in would
    # preserve stale revisions (conancenter shadowing local recipes, missing
    # test_requires) and defeat the purpose of regenerating it.
    filtered = []
    skip_next = False
    for item in args:
        if skip_next:
            skip_next = False
            continue
        if item == "--lockfile":
            skip_next = True
            continue
        if str(item).startswith("--lockfile="):
            continue
        filtered.append(item)
    # Conan auto-loads ./conan.lock even for `lock create`; an explicit empty
    # lockfile is required to start from a clean resolution.
    filtered = [item for item in filtered if item != "--build=missing"]
    filtered.append("--lockfile=")
    return filtered


def lock(ctx, config=None):
    """Regenerate and merge conan.lock for every valid config of every toolchain."""
    ctx.require_devkit()
    configs_to_lock = [validate_config(config)] if config else valid_configs_for_all_toolchains()

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

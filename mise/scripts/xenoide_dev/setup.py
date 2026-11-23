"""`setup`, `doctor`, dependency checkout and lockfile generation."""

import json
import os
import re
import shutil
from pathlib import Path

from .config import Config, validate_config
from .util import (DevkitError, capture, fail, git, info, is_linux, is_windows,
                   require, run, warn)


DEFAULT_URL_BASE = "https://github.com/XenoideSoftware"


# --------------------------------------------------------------------- helpers

def _dep_url(ctx, name):
    override = os.environ.get(f"XENOIDE_DEP_{name.upper().replace('-', '_')}_URL")
    if override:
        return override
    # Developer mode: when the devkit is linked to a sibling checkout, resolve
    # in-house repositories from the sibling layout too. This is what makes the
    # editable loop work before anything is pushed.
    if os.environ.get("XENOIDE_DEVKIT_PATH"):
        sibling = ctx.root.parent / name
        if sibling.is_dir():
            return str(sibling)
    return f"{DEFAULT_URL_BASE}/{name}.git"


def checkout(ctx, name, ref):
    """Check out ``name`` at ``ref`` in ``.deps/<name>`` (idempotent)."""
    deps = ctx.root / ".deps"
    deps.mkdir(parents=True, exist_ok=True)
    target = deps / name
    url = _dep_url(ctx, name)
    if (target / ".git").is_dir():
        info(f"==> Updating .deps/{name} to {ref}")
        git(["fetch", "--tags", "--force", url, ref], cwd=target, check=False)
    else:
        if target.exists():
            shutil.rmtree(target)
        info(f"==> Cloning {url} -> .deps/{name}")
        run(["git", "clone", "--quiet", url, str(target)])
    run(["git", "-c", "advice.detachedHead=false", "checkout", "--force", ref], cwd=target)
    return target


def _editable_registered(name):
    result = run(["conan", "editable", "list"], capture=True, check=False)
    if result.returncode != 0:
        return False
    return re.search(rf"(?m)^\s*{re.escape(name)}/", result.stdout) is not None


def parse_packages(value):
    packages = []
    for item in (value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "@" not in item:
            fail(f"invalid XENOIDE_PACKAGES entry '{item}' (expected repo@tag)")
        name, ref = item.rsplit("@", 1)
        packages.append((name.strip(), ref.strip()))
    return packages


def _profile_args(ctx, config):
    toolchain = ctx.devkit / "conan" / "profiles" / "toolchain" / config.toolchain
    flavor = ctx.devkit / "conan" / "profiles" / "flavor" / config.flavor
    return ["-pr:h", str(toolchain), "-pr:h", str(flavor),
            "-pr:b", str(toolchain), "-s:b", "build_type=Release"]


# ------------------------------------------------------------------------ setup

def sync(ctx):
    """Clone (or link) the pinned devkit checkout into ``.devkit/``."""
    ref = os.environ.get("DEVKIT_REF", "v0.1.0")
    url = os.environ.get("DEVKIT_URL", f"{DEFAULT_URL_BASE}/devkit.git")
    local = os.environ.get("XENOIDE_DEVKIT_PATH")
    devkit = ctx.devkit

    if local:
        local_path = Path(local).expanduser().resolve()
        if not local_path.is_dir():
            fail(f"XENOIDE_DEVKIT_PATH does not exist: {local_path}")
        if devkit.is_symlink() or devkit.exists():
            if devkit.is_symlink() and devkit.resolve() == local_path:
                info(f"==> .devkit already links to {local_path}")
                return
            if devkit.is_dir() and not devkit.is_symlink():
                shutil.rmtree(devkit)
            else:
                devkit.unlink()
        devkit.symlink_to(local_path, target_is_directory=True)
        info(f"==> Linked .devkit -> {local_path} (development mode)")
        return

    if (devkit / ".git").is_dir():
        info(f"==> Updating .devkit to {ref}")
        git(["fetch", "--tags", "--force", url, ref], cwd=devkit, check=False)
    else:
        if devkit.exists():
            shutil.rmtree(devkit)
        info(f"==> Cloning {url} -> .devkit")
        run(["git", "clone", "--quiet", url, str(devkit)])
    run(["git", "-c", "advice.detachedHead=false", "checkout", "--force", ref], cwd=devkit)


def setup(ctx, skip_doctor=False):
    ctx.require_devkit()
    conan = require("conan")

    info("==> Installing the devkit Conan configuration")
    run([conan, "config", "install", str(ctx.devkit / "conan")], cwd=ctx.root, check=False)

    info("==> Exporting xenoide-base (python_requires)")
    run([conan, "export", str(ctx.devkit / "conan" / "base")], cwd=ctx.root)

    recipes_ref = os.environ.get("RECIPES_REF", "v0.1.0")
    if recipes_ref:
        info(f"==> Checking out xenoide-recipes at {recipes_ref}")
        recipes = checkout(ctx, "xenoide-recipes", recipes_ref)
        run([conan, "remote", "remove", "xenoide-recipes"], cwd=ctx.root, check=False)
        run([conan, "remote", "add", "xenoide-recipes", str(recipes),
             "--type=local-recipes-index"], cwd=ctx.root, check=False)

    release = validate_config(Config(_host_toolchain(), "release"))
    packages = parse_packages(os.environ.get("XENOIDE_PACKAGES", ""))
    for name, ref in packages:
        if _editable_registered(name):
            info(f"==> Skipping {name} (an editable is registered)")
            continue
        info(f"==> Building in-house package {name} at {ref}")
        package_dir = checkout(ctx, name, ref)
        # A lockfile committed by the library pins the devkit/base revision of
        # the cache it was generated in. The .deps checkout is disposable, so
        # build the package from its pinned content without that lock.
        for lockfile in list(package_dir.glob("conan.lock")) + \
                list(package_dir.glob("*/conan.lock")):
            lockfile.unlink()
        run([conan, "create", str(package_dir),
             *_profile_args(ctx, release), "--build=missing"], cwd=ctx.root)
        if name == "glazer" and (package_dir / "glazed" / "conanfile.py").is_file():
            info("==> Building glazed (generated bindings, lockstep with glazer)")
            run([conan, "create", str(package_dir / "glazed"),
                 *_profile_args(ctx, release), "--build=missing"], cwd=ctx.root)

    info("==> Installing the devkit tools environment")
    tools_out = ctx.root / ".xenoide" / "tools"
    has_checker = any(name == "cmake-checker" for name, _ in packages)
    run([conan, "install", str(ctx.devkit / "conan" / "tools"),
         "-of", str(tools_out), *_profile_args(ctx, release),
         f"-o", f"&:with_cmake_checker={has_checker}", "--build=missing"],
        cwd=ctx.root, check=False)

    if not skip_doctor:
        doctor(ctx)


def _host_toolchain():
    from .config import host_toolchain
    return host_toolchain()


# ----------------------------------------------------------------------- doctor

def _version_of(command, args=("--version",)):
    try:
        return capture([command, *args], check=False).splitlines()[0]
    except Exception:
        return None


def _compiler_version(cc):
    try:
        text = capture([cc, "--version"], check=False)
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
        return match.group(1) if match else "unknown"
    except Exception:
        return None


def _devkit_base_version(ctx):
    conanfile = ctx.devkit / "conan" / "base" / "conanfile.py"
    if not conanfile.is_file():
        return None
    match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', conanfile.read_text())
    return match.group(1) if match else None


def doctor(ctx):
    ctx.require_devkit()
    failures = []
    warnings = []

    info("== doctor: portable orchestration tools ==")
    python_found = False
    for tool in ("cmake", "ninja", "conan", "git"):
        found = shutil.which(tool)
        if found:
            info(f"  ok    {tool:22} {found}")
        else:
            failures.append(f"{tool} not found")
    for tool in ("python", "python3"):
        found = shutil.which(tool)
        if found:
            python_found = True
            info(f"  ok    {tool:22} {found}")
    if not python_found:
        failures.append("python (or python3) not found")

    devkit_ref = os.environ.get("DEVKIT_REF", "v0.1.0")
    base_version = _devkit_base_version(ctx)
    expected = devkit_ref[1:] if devkit_ref.startswith("v") else devkit_ref
    if base_version == expected:
        info(f"  ok    xenoide-base version  {base_version} == DEVKIT_REF {devkit_ref}")
    else:
        failures.append(
            f"xenoide-base version {base_version} does not match DEVKIT_REF {devkit_ref}")

    info("== doctor: toolchains ==")
    cc = os.environ.get("XENOIDE_CC", "gcc" if is_linux() else "clang")
    compiler_version = _compiler_version(cc)
    if compiler_version:
        info(f"  ok    {cc:22} {compiler_version}")
    else:
        failures.append(f"compiler '{cc}' not found (set XENOIDE_CC)")

    llvm_major = None
    if "clang" in Path(cc).name:
        llvm_major = compiler_version.split(".")[0] if compiler_version else None

    for tool in ("clang-format", "clang-tidy", "gdb", "lldb", "valgrind"):
        found = shutil.which(tool)
        if found:
            info(f"  ok    {tool:22} {_version_of(found) or found}")
        else:
            warnings.append(f"{tool} not found (needed only by the matching task)")

    if llvm_major:
        for tool in (f"clang-tidy-{llvm_major}", f"mull-runner-{llvm_major}",
                     f"mull-reporter-{llvm_major}"):
            if shutil.which(tool):
                info(f"  ok    {tool:22} {shutil.which(tool)}")

    if is_linux():
        # Known kernel/runtime interaction: high mmap_rnd_bits breaks old
        # ASan/TSan runtimes. Detection is advisory, not fatal.
        try:
            bits = Path("/proc/sys/vm/mmap_rnd_bits").read_text().strip()
            if int(bits) > 28:
                warnings.append(
                    f"vm.mmap_rnd_bits={bits}; if ASan/TSan crashes, use a newer "
                    "LLVM/GCC or `sysctl vm.mmap_rnd_bits=28`")
        except Exception:
            pass

    for item in warnings:
        warn(item)
    if failures:
        for item in failures:
            print(f"  FAIL  {item}")
        fail("doctor found problems")
    info("doctor: all required tools are present")


# ------------------------------------------------------------------------ lock

def lock(ctx, config):
    """Regenerate ``conan.lock`` for the given config."""
    ctx.require_devkit()
    build = ctx.build_dir(config)
    build.mkdir(parents=True, exist_ok=True)
    lock_path = build / "conan.lock"
    args = ctx.conan_args(config)
    run(["conan", *args, f"--lockfile-out={lock_path}"], cwd=ctx.root)
    if lock_path.is_file():
        target = ctx.root / "conan.lock"
        shutil.copy2(lock_path, target)
        info(f"==> Wrote {target}")

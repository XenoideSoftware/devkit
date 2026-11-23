"""Shared helpers for the Xenoide devkit task implementation.

Only the Python standard library is used. The same implementation runs on
Linux, macOS and Windows; tasks that need a Unix-only tool check the OS and
exit early instead of failing with a confusing error.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


class DevkitError(RuntimeError):
    pass


def info(message):
    print(message, flush=True)


def warn(message):
    print(f"warning: {message}", file=sys.stderr, flush=True)


def fail(message):
    raise DevkitError(message)


def is_linux():
    return platform.system() == "Linux"


def is_darwin():
    return platform.system() == "Darwin"


def is_windows():
    return platform.system() == "Windows"


def platform_name():
    return platform.system()


def which(name):
    return shutil.which(name)


def require(name, hint=None):
    found = shutil.which(name)
    if not found:
        fail(f"required tool '{name}' not found in PATH" + (f" ({hint})" if hint else ""))
    return found


def run(cmd, cwd=None, env=None, check=True, capture=False):
    """Run a command, streaming output unless ``capture`` is requested."""
    display = " ".join(str(part) for part in cmd)
    info(f"+ {display}")
    merged = os.environ.copy()
    if env:
        merged.update({str(k): str(v) for k, v in env.items()})
    if capture:
        result = subprocess.run(
            [str(part) for part in cmd], cwd=cwd, env=merged,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if check and result.returncode != 0:
            raise DevkitError(
                f"command failed ({result.returncode}): {display}\n{result.stdout}")
        return result
    result = subprocess.run([str(part) for part in cmd], cwd=cwd, env=merged)
    if check and result.returncode != 0:
        raise DevkitError(f"command failed ({result.returncode}): {display}")
    return result


def capture(cmd, cwd=None, env=None, check=True):
    return run(cmd, cwd=cwd, env=env, check=check, capture=True).stdout.strip()


def git(args, cwd, check=True):
    return run(["git", *args], cwd=cwd, check=check, capture=True)


def repo_root(start=None):
    """The consumer repository root (where mise.toml lives)."""
    return Path(start or os.getcwd()).resolve()


def devkit_root(root):
    return root / ".devkit"


def source_files(root):
    """Every first-party C/C++ source file, excluding generated trees."""
    excluded_dirs = {".git", ".devkit", ".deps", ".conan2", ".xenoide",
                     "build", "CMakeFiles", "generated", "coverage", "mutation"}
    suffixes = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl"}
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in excluded_dirs and not d.startswith("build-")]
        for filename in filenames:
            if Path(filename).suffix.lower() in suffixes:
                yield Path(directory) / filename


def iter_executables(build_dir, name=None):
    """Find runnable targets in a build tree."""
    build_dir = Path(build_dir)
    if not build_dir.is_dir():
        return
    skip = {"CMakeFiles", "generators", "_deps", "cmake", "CMakeCache.txt"}
    for directory, dirnames, filenames in os.walk(build_dir):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for filename in filenames:
            if filename.endswith((".o", ".a", ".so", ".dylib", ".dll", ".lib",
                                 ".cmake", ".json", ".txt", ".log", ".gcda", ".gcno")):
                continue
            path = Path(directory) / filename
            if not path.is_file() or not os.access(path, os.X_OK):
                continue
            stem = path.stem
            if name and stem != name:
                continue
            yield path


def relative_to(root, path):
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)

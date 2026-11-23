#!/usr/bin/env python3
"""Devkit self-test: exercise the sample project end to end.

The sample is copied to a temporary directory so the checkout stays clean. The
devkit is linked in development mode, and the recipe/package pins are disabled
because the self-test must not depend on published repositories.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEVKIT = Path(__file__).resolve().parent.parent.parent
SAMPLE = DEVKIT / "tests" / "sample"
SCRIPT = DEVKIT / "mise" / "scripts" / "xenoide_dev.py"


def run(cmd, cwd, env):
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        raise SystemExit(f"self-test failed: {' '.join(str(p) for p in cmd)}")


def main():
    work = Path(tempfile.mkdtemp(prefix="xenoide-devkit-selftest-"))
    project = work / "sample"
    shutil.copytree(SAMPLE, project)
    print(f"==> Self-test project: {project}")

    env = os.environ.copy()
    env["XENOIDE_DEVKIT_PATH"] = str(DEVKIT)
    env["RECIPES_REF"] = ""
    env["XENOIDE_PACKAGES"] = ""
    env["CONAN_HOME"] = str(work / ".conan2")
    env["XENOIDE_BUILD_ROOT"] = "build"
    env.setdefault("XENOIDE_CC", "gcc")

    def devkit(*args):
        run([sys.executable, str(SCRIPT), *args], cwd=project, env=env)

    devkit("setup", "--skip-doctor")

    configs = ["gcc-debug"]
    if shutil.which("clang"):
        configs.append("clang-debug")
        configs.append("clang-asan")
        configs.append("clang-coverage")
    else:
        configs.append("gcc-asan")
        configs.append("gcc-coverage")

    for config in configs:
        print(f"==> self-test config {config}")
        devkit("deps", "--config", config)
        devkit("build", "--config", config)
        devkit("test", "--config", config)

    devkit("cppcheck", "--config", configs[0], "--full")
    devkit("format", "--check")

    print(f"==> Self-test passed ({', '.join(configs)})")
    print(f"    Artifacts kept in {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

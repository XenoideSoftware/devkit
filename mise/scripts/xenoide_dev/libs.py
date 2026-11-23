"""Library loop helpers: editables, new libraries and releases."""

import re
import shutil
from pathlib import Path

from .util import fail, git, info, run, warn


CONANFILE = '''from conan import ConanFile


class {class_name}(ConanFile):
    name = "{name}"
    version = "0.1.0"
    python_requires = "xenoide-base/0.1.0"
    python_requires_extend = "xenoide-base.XenoideCMake"
    package_type = "static-library"

    exports_sources = "CMakeLists.txt", "src/*", "include/*"
'''

CMAKE = '''cmake_minimum_required (VERSION 3.25)
project ({name} VERSION ${{XENOIDE_BUILD_VERSION}} LANGUAGES CXX)

include(XenoideConfig)

add_library ({name}_lib src/{name}.cpp)
add_library ({name}::{name} ALIAS {name}_lib)
target_include_directories ({name}_lib PUBLIC include)
target_link_libraries ({name}_lib PRIVATE xenoide::interface)

if (XENOIDE_ENABLE_TESTING)
    add_executable ({name}-test test/{name}-test.cpp)
    target_link_libraries ({name}-test PRIVATE {name}_lib Catch2::Catch2WithMain)
    xenoide_add_catch2_tests ({name}-test)
endif ()
'''


def editable_add(ctx, path):
    target = Path(path).expanduser().resolve()
    if not (target / "conanfile.py").is_file():
        fail(f"{target} does not contain a conanfile.py")
    run(["conan", "editable", "add", str(target)], cwd=ctx.root)
    info(f"==> Registered editable {target}")
    info("    Re-run `mise run deps` in the consumer; the editable builds into")
    info("    the consumer's build folder with the consumer's config.")


def editable_remove(ctx, path):
    target = Path(path).expanduser().resolve()
    result = run(["conan", "editable", "remove", str(target)], cwd=ctx.root, check=False)
    if result.returncode == 0:
        info(f"==> Removed editable {target}")


def create_library(ctx, name, directory=None):
    if not re.match(r"^[a-z][a-z0-9-]*$", name):
        fail("library name must be lower-case kebab-case (e.g. libfoo)")
    target = Path(directory or name).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        fail(f"{target} already exists and is not empty")
    (target / "src").mkdir(parents=True, exist_ok=True)
    (target / "include").mkdir(parents=True, exist_ok=True)
    (target / "test").mkdir(parents=True, exist_ok=True)

    class_name = "".join(part.capitalize() for part in name.split("-")) + "Conan"
    (target / "conanfile.py").write_text(CONANFILE.format(name=name, class_name=class_name),
                                        encoding="utf-8")
    (target / "CMakeLists.txt").write_text(CMAKE.format(name=name), encoding="utf-8")
    (target / "src" / f"{name}.cpp").write_text(
        f'#include "{name}/{name}.h"\n\nnamespace {{\nint placeholder() {{ return 0; }}\n}}\n',
        encoding="utf-8")
    (target / "include" / name).mkdir(exist_ok=True)
    (target / "include" / name / f"{name}.h").write_text(
        "#pragma once\n\nnamespace " + name.replace("-", "_") + " {\n"
        "int placeholder();\n}\n", encoding="utf-8")
    (target / "test" / f"{name}-test.cpp").write_text(
        '#include <catch2/catch_test_macros.hpp>\n\n'
        f'TEST_CASE("{name} placeholder") {{ REQUIRE(true); }}\n', encoding="utf-8")
    info(f"==> Created library skeleton at {target}")


def _read_version(conanfile):
    match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', conanfile.read_text())
    if not match:
        fail(f"no version literal found in {conanfile}")
    return match.group(1)


def release(ctx, name=None):
    conanfile = ctx.root / "conanfile.py"
    if not conanfile.is_file():
        fail("release must run at the repository root (conanfile.py)")
    version = _read_version(conanfile)
    tag = f"v{version}"
    if name is None:
        name = ctx.root.name
    run(["git", "tag", "-a", tag, "-m", f"{name} {version}"], cwd=ctx.root)
    info(f"==> Created tag {tag}")

"""``xenoide-base``: the shared Conan base class for every first-party recipe.

The class is consumed through a ``python_requires`` and ships the CMake modules
in the same package, so a recipe always has them, even when it is built inside
the Conan cache with no network and no ``.git`` directory.

Design notes
------------
* The repository's ``conanfile.py`` keeps only project options, requirements
  and a ``version`` literal. The standard options are added in ``init()``
  (this is the documented Conan hook for extending options from a
  ``python_requires``).
* The build folder is ``${XENOIDE_BUILD_ROOT}/<toolchain>-<flavor>`` so any
  number of toolchains and flavors can coexist in one checkout.
* Presets are renamed to ``conan-<toolchain>-<flavor>`` so VS Code, CLion and
  the CLI all see one stable name per config.
"""

import json
import os
import re

from conan import ConanFile
from conan.errors import ConanException
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import load, save


STANDARD_OPTIONS = {
    "with_tests": [True, False],
    "instrument": ["none", "asan", "tsan", "coverage", "mutation"],
    "werror": [True, False],
}

INSTRUMENTED_FLAVORS = ("asan", "tsan", "coverage", "mutation")

# toolchain -> set of supported flavors (the single source of truth for the
# matrix documented in devkit/docs/CONVENTIONS.md)
VALID_MATRIX = {
    "gcc": {"debug", "release", "profile", "asan", "tsan", "coverage"},
    "clang": {"debug", "release", "profile", "asan", "tsan", "coverage", "mutation"},
    "apple-clang": {"debug", "release", "profile", "asan", "coverage"},
    "msvc": {"debug", "release", "profile", "asan"},
    "clang-cl": {"debug", "release", "profile", "asan"},
    "mingw-gcc": {"debug", "release", "profile", "coverage"},
    "legacy-i686-gcc5": {"debug", "release"},
}

FLAVOR_BUILD_TYPE = {
    "debug": "Debug",
    "release": "Release",
    "profile": "RelWithDebInfo",
    "asan": "Debug",
    "tsan": "Debug",
    "coverage": "Debug",
    "mutation": "Debug",
}


def _find_mull_plugin(conanfile):
    """Locate mull-ir-frontend-<N> for the selected LLVM major version."""
    import shutil

    major = conanfile.conf.get("user.xenoide:llvm_major", default=None)
    candidates = []
    if major:
        candidates.append(f"mull-ir-frontend-{major}")
    else:
        for suffix in ("", ):
            candidates.append(f"mull-ir-frontend{suffix}")
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    search_dirs = ("/usr/lib", "/usr/local/lib", "/usr/lib64")
    if major:
        for directory in search_dirs:
            candidate = os.path.join(directory, f"mull-ir-frontend-{major}")
            if os.path.isfile(candidate):
                return candidate
    return ""



class XenoideCMake(ConanFile):
    """Base class inherited by every Xenoide recipe."""

    # The python_requires recipe's own identity. Consumer recipes override
    # name/version with their own version file.
    name = "xenoide-base"
    version = "0.1.1"

    package_type = "application"
    settings = "os", "compiler", "build_type", "arch"

    # Ship the CMake modules inside the python_requires package so every
    # consumer has them even inside the cache with no network access. `exports`
    # (not `exports_sources`) puts them in the recipe folder, which is what
    # `python_requires[...].path` resolves to.
    exports = "cmake/*"

    # Prefix for the generated build-info macros (XE_BUILD_VERSION, ...).
    build_info_prefix = "XE"

    # Applications embed their commit SHA. Libraries/tools may opt out so
    # their recipe revision stays content-stable across commits (needed for
    # portable lockfiles that reference them).
    capture_commit = True

    # ------------------------------------------------------------------ options

    def init(self):
        # Extend (do not replace) whatever project options the recipe declared.
        self.options.update(STANDARD_OPTIONS)
        self.options.with_tests = True
        self.options.instrument = "none"
        self.options.werror = True

    # ------------------------------------------------------------------- layout

    def _xenoide_config(self):
        toolchain = self.conf.get("user.xenoide:toolchain", default=None)
        flavor = self.conf.get("user.xenoide:flavor", default=None)
        if toolchain and flavor:
            return toolchain, flavor
        return None, None

    def _build_subfolder(self):
        toolchain, flavor = self._xenoide_config()
        if toolchain and flavor:
            return f"{toolchain}-{flavor}"
        compiler = self.settings.get_safe("compiler") or "unknown"
        version = self.settings.get_safe("compiler.version") or "0"
        build_type = self.settings.get_safe("build_type") or "Release"
        instrument = self.options.get_safe("instrument") or "none"
        folder = f"{compiler}-{version}-{build_type}"
        if instrument != "none":
            folder += f"-{instrument}"
        return folder

    def layout(self):
        build_root = os.getenv("XENOIDE_BUILD_ROOT", "build")
        folder = os.path.join(build_root, self._build_subfolder())
        cmake_layout(self, src_folder=".", build_folder=folder)
        # cmake_layout appends the build type for single-config generators;
        # the Xenoide config already encodes it, so pin the exact folder.
        self.folders.build = folder
        self.folders.generators = os.path.join(folder, "generators")

    # --------------------------------------------------------------- packaging

    def build_requirements(self):
        if self.options.get_safe("with_tests"):
            # Every recipe uses test_requires (never a plain requirement), so
            # Catch2 never becomes part of a consumer's runtime graph.
            self.test_requires("catch2/3.14.0")

    # ---------------------------------------------------------------- validation

    def validate(self):
        toolchain, flavor = self._xenoide_config()
        instrument = str(self.options.get_safe("instrument") or "none")

        try:
            from conan.internal.graph.graph import RECIPE_CONSUMER, RECIPE_EDITABLE
            is_consumer = self._conan_node.recipe in (RECIPE_CONSUMER, RECIPE_EDITABLE)
        except Exception:
            is_consumer = True

        # The flavor is a global conf, so dependencies see it too. Only the
        # consumer's own instrument option is meaningful; never reject a
        # dependency because it was built uninstrumented.
        if not is_consumer:
            return

        if toolchain and flavor:
            supported = VALID_MATRIX.get(toolchain)
            if supported is None:
                raise ConanException(
                    f"Unknown toolchain '{toolchain}'. Expected one of: "
                    + ", ".join(sorted(VALID_MATRIX))
                )
            if flavor not in supported:
                raise ConanException(
                    f"Config '{toolchain}-{flavor}' is not supported. "
                    f"Valid flavors for {toolchain}: {', '.join(sorted(supported))}"
                )
            if flavor in INSTRUMENTED_FLAVORS and instrument != flavor:
                raise ConanException(
                    f"Flavor '{flavor}' requires instrument={flavor} "
                    f"(got instrument={instrument})."
                )
            if flavor not in INSTRUMENTED_FLAVORS and instrument != "none":
                raise ConanException(
                    f"instrument={instrument} is only valid with an instrumented "
                    f"flavor; '{toolchain}-{flavor}' is a plain build."
                )

        if instrument == "mutation" and not (toolchain or "").startswith("clang"):
            raise ConanException("mutation requires the clang toolchain (Mull is Linux/LLVM only).")

    # ------------------------------------------------------------------ generate

    def xenoide_deps(self, deps):
        """Hook for subclasses to tweak CMakeDeps before it is generated."""

    def xenoide_toolchain(self, tc):
        """Hook for subclasses to add cache variables before ``tc.generate()``."""

    def _devkit_cmake_dir(self):
        return os.path.join(self.python_requires["xenoide-base"].path, "cmake")

    def _commit_id(self):
        candidates = []
        export_folder = getattr(self, "export_folder", None)
        if export_folder:
            candidates.append(os.path.join(export_folder, "xenoide_commit.txt"))
        candidates.append(os.path.join(self.recipe_folder, "xenoide_commit.txt"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return load(self, candidate).strip() or "unknown"
        # Live checkout (plain `conan install .`): ask git directly.
        try:
            from conan.tools.scm import Git

            git = Git(self, self.recipe_folder)
            return git.run("rev-parse HEAD").strip()
        except Exception:
            return "unknown"

    def export(self):
        # Capture the commit while the checkout (with .git) is still available;
        # `conan create` later runs from the cache, where .git does not exist.
        # The devkit base itself is a python_requires locked by consumers, so
        # it must NOT embed a commit: that would change its recipe revision on
        # every devkit commit and invalidate every lockfile.
        if str(self.name) == "xenoide-base" or not self.capture_commit:
            return
        try:
            from conan.tools.scm import Git

            git = Git(self, self.recipe_folder)
            # Build identity is version + commit SHA. A dirty marker would make
            # the recipe revision depend on untracked build state, which breaks
            # portable lockfiles, so it is deliberately omitted.
            value = git.run("rev-parse HEAD").strip()
        except Exception:
            value = "unknown"
        save(self, os.path.join(self.export_folder, "xenoide_commit.txt"), value + "\n")

    def _rename_presets(self, name):
        """Rename the generated presets to ``conan-<toolchain>-<flavor>``."""
        path = os.path.join(self.generators_folder, "CMakePresets.json")
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        for preset in data.get("configurePresets", []):
            preset["name"] = name
        for preset in data.get("buildPresets", []):
            preset["name"] = name
            preset["configurePreset"] = name
        for preset in data.get("testPresets", []):
            preset["name"] = name
            preset["configurePreset"] = name
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)

    def generate(self):
        deps = CMakeDeps(self)
        self.xenoide_deps(deps)
        deps.generate()

        toolchain, flavor = self._xenoide_config()
        commit = self._commit_id()
        prefix = self.build_info_prefix
        cmake_dir = self._devkit_cmake_dir().replace("\\", "/")

        tc = CMakeToolchain(self)
        tc.cache_variables["XENOIDE_INSTRUMENT"] = str(self.options.get_safe("instrument") or "none")
        tc.cache_variables["XENOIDE_WERROR"] = "ON" if self.options.get_safe("werror") else "OFF"
        tc.cache_variables["XENOIDE_ENABLE_TESTING"] = "ON" if self.options.get_safe("with_tests") else "OFF"
        tc.cache_variables["XENOIDE_BUILD_VERSION"] = str(self.version)
        tc.cache_variables["XENOIDE_BUILD_COMMIT"] = commit
        tc.cache_variables[f"{prefix}_BUILD_VERSION"] = str(self.version)
        tc.cache_variables[f"{prefix}_BUILD_COMMIT"] = commit
        tc.cache_variables["CMAKE_EXPORT_COMPILE_COMMANDS"] = "ON"

        # Inherited by instrumented test targets via xenoide_add_catch2_tests().
        tc.cache_variables["XENOIDE_ASAN_OPTIONS"] = (
            "detect_leaks=1:abort_on_error=1:strict_string_checks=1"
        )
        tc.cache_variables["XENOIDE_UBSAN_OPTIONS"] = "print_stacktrace=1:halt_on_error=1"
        tc.cache_variables["XENOIDE_TSAN_OPTIONS"] = "halt_on_error=1"

        if str(self.options.get_safe("instrument") or "none") == "mutation":
            tc.cache_variables["XENOIDE_MULL_PLUGIN"] = _find_mull_plugin(self)
            mull_config = os.environ.get("MULL_CONFIG")
            if mull_config and os.path.isfile(mull_config):
                import hashlib

                with open(mull_config, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()[:16]
                # Part of the compile command, so changing the mutation
                # configuration forces a rebuild instead of silently reusing
                # mutants discovered with the old settings (M1).
                tc.cache_variables["XENOIDE_MULL_CONFIG_HASH"] = digest

        self.xenoide_toolchain(tc)
        # Normal `code()` variables are `set(... CACHE)` entries in the
        # toolchain file and therefore never override an existing cache. Move
        # everything to cache_variables so Conan writes them into
        # CMakePresets.json (`-D...`); `cmake --preset` then updates a stale
        # build tree whenever an option changes (C1).
        for key, value in list(tc.variables.items()):
            tc.cache_variables.setdefault(key, value)
        tc.variables.clear()
        tc.generate()

        # Toolchain variables are cache variables, so a project() argument
        # cannot see them (arguments are expanded before CMake processes the
        # toolchain). Append a normal variable/list update instead: it runs
        # before project(), so `include(XenoideConfig)` finds the modules.
        toolchain_file = os.path.join(self.generators_folder, "conan_toolchain.cmake")
        if os.path.isfile(toolchain_file):
            with open(toolchain_file, "a", encoding="utf-8") as handle:
                handle.write(
                    "\n# Xenoide devkit CMake modules\n"
                    f'list(PREPEND CMAKE_MODULE_PATH "{cmake_dir}")\n')

        if toolchain and flavor:
            self._rename_presets(f"conan-{toolchain}-{flavor}")

    # --------------------------------------------------------------------- build

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        cmake = CMake(self)
        cmake.install()

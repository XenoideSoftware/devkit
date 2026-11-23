"""Build-configuration model: a config is ``<toolchain>-<flavor>``."""

import os
import platform
from dataclasses import dataclass
from pathlib import Path

from .util import DevkitError, fail, info, is_darwin, is_linux, is_windows


VALID_MATRIX = {
    "gcc": {"debug", "release", "profile", "asan", "tsan", "coverage"},
    "clang": {"debug", "release", "profile", "asan", "tsan", "coverage", "mutation"},
    "apple-clang": {"debug", "release", "profile", "asan", "coverage"},
    "msvc": {"debug", "release", "profile", "asan"},
    "clang-cl": {"debug", "release", "profile", "asan"},
    "mingw-gcc": {"debug", "release", "profile", "coverage"},
    "legacy-i686-gcc5": {"debug", "release"},
}

FLAVORS = ("debug", "release", "profile", "asan", "tsan", "coverage", "mutation")

TOOLCHAIN_FOR_HOST = {
    "Linux": "gcc",
    "Darwin": "apple-clang",
    "Windows": "msvc",
}


@dataclass(frozen=True)
class Config:
    toolchain: str
    flavor: str

    @property
    def name(self):
        return f"{self.toolchain}-{self.flavor}"

    @property
    def instrument(self):
        return self.flavor if self.flavor in ("asan", "tsan", "coverage", "mutation") else "none"

    def __str__(self):
        return self.name


def host_toolchain():
    return TOOLCHAIN_FOR_HOST.get(platform.system(), "gcc")


def default_config():
    return Config(host_toolchain(), "debug")


def parse_config(value):
    if not value:
        fail("empty config; expected <toolchain>-<flavor>, e.g. clang-asan")
    value = value.strip()
    for toolchain in sorted(VALID_MATRIX, key=len, reverse=True):
        prefix = toolchain + "-"
        if value.startswith(prefix):
            flavor = value[len(prefix):]
            break
    else:
        parts = value.rsplit("-", 1)
        if len(parts) != 2:
            fail(f"invalid config '{value}'; expected <toolchain>-<flavor>")
        toolchain, flavor = parts
    return Config(toolchain, flavor)


def validate_config(config):
    supported = VALID_MATRIX.get(config.toolchain)
    if supported is None:
        fail(f"unknown toolchain '{config.toolchain}'. Known: {', '.join(sorted(VALID_MATRIX))}")
    if config.flavor not in supported:
        fail(f"config '{config.name}' is not supported. "
             f"Valid flavors for {config.toolchain}: {', '.join(sorted(supported))}")
    return config


def resolve_config(root, explicit=None):
    value = explicit or os.environ.get("XENOIDE_CONFIG")
    if not value:
        active = Path(root) / ".xenoide" / "active"
        if active.is_file():
            value = active.read_text(encoding="utf-8").strip()
    if not value:
        return default_config()
    return validate_config(parse_config(value))


def valid_configs_for_host():
    toolchain = host_toolchain()
    return [Config(toolchain, flavor) for flavor in FLAVORS if flavor in VALID_MATRIX[toolchain]]


class Context:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.devkit = self.root / ".devkit"
        build_root = os.environ.get("XENOIDE_BUILD_ROOT", "build")
        self.build_root = Path(build_root)
        if not self.build_root.is_absolute():
            self.build_root = self.root / self.build_root

    # ------------------------------------------------------------------ config

    def config(self, explicit=None):
        return resolve_config(self.root, explicit)

    def build_dir(self, config):
        return self.build_root / config.name

    # ----------------------------------------------------------------- devkit

    def profiles(self, config):
        return (
            self.devkit / "conan" / "profiles" / "toolchain" / config.toolchain,
            self.devkit / "conan" / "profiles" / "flavor" / config.flavor,
        )

    def require_devkit(self):
        if not self.devkit.is_dir():
            fail(".devkit/ is missing; run 'mise run devkit:sync' first")
        if not (self.devkit / "conan" / "base" / "conanfile.py").is_file():
            fail(".devkit/ is incomplete (conan/base missing); re-run 'mise run devkit:sync'")

    # -------------------------------------------------------------------- conan

    def conan_args(self, config):
        host_toolchain, host_flavor = self.profiles(config)
        build_toolchain, _ = self.profiles(config)
        args = [
            "install", ".",
            "-pr:h", str(host_toolchain),
            "-pr:h", str(host_flavor),
            "-pr:b", str(build_toolchain),
            "-s:b", "build_type=Release",
            "--build=missing",
        ]
        # Escape hatch for a one-off consumer option override, e.g.
        # XENOIDE_CONAN_OPTIONS="with_demos=False,with_engine_tool_gltfc=False"
        extra = os.environ.get("XENOIDE_CONAN_OPTIONS", "")
        for item in extra.split(","):
            item = item.strip()
            if item:
                args += ["-o", f"&:{item}" if "=" in item and not item.startswith("&") else item]
        lockfile = self.root / "conan.lock"
        if lockfile.is_file() and not os.environ.get("XENOIDE_IGNORE_LOCK"):
            args.append(f"--lockfile={lockfile}")
        return args

    def preset(self, config):
        return f"conan-{config.name}"

    def compile_commands(self, config):
        return self.build_dir(config) / "compile_commands.json"

    # --------------------------------------------------------------------- env

    def mise_env(self):
        keys = ("DEVKIT_URL", "DEVKIT_REF", "RECIPES_REF", "XENOIDE_PACKAGES",
                "CONAN_HOME", "XENOIDE_CONAN_HOME", "XENOIDE_BUILD_ROOT",
                "XENOIDE_DEVKIT_PATH", "XENOIDE_CONFIG")
        return {key: os.environ[key] for key in keys if key in os.environ}


def print_configs():
    toolchain = host_toolchain()
    info(f"Host: {platform.system()} {platform.machine()}")
    info(f"Toolchain: {toolchain}")
    for config in valid_configs_for_host():
        info(f"  {config.name}")

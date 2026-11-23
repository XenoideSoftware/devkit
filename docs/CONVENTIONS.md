# Xenoide shared conventions

This file is the index for every repository in the Xenoide component family.
`AGENTS.md` in each repository links here instead of duplicating the rules.

## Repositories

| Repository | Purpose |
|---|---|
| `devkit` | Conan config, `xenoide-base` python_requires, CMake modules, mise tasks, Docker image, shared suppressions, docs |
| `xenoide` | The IDE (Qt6 is the supported UI) |
| `xengine` | The engine, its tools and demos |
| `cmake-checker` | The CMake style checker tool |
| `glazer` | The Glaze generator; exports `glazer` and `glazed` in lockstep |
| `xenoide-pocs` | Versioned experiments |
| `xenoide-recipes` | Third-party and fork Conan recipes (local-recipes-index) |

## Naming

- CMake functions and targets use the `xenoide_` prefix (`xenoide::interface`,
  `xenoide_add_catch2_tests`).
- Shared cache variables use `XENOIDE_*`. Engine/IDE-local options keep `XE_*`.
- In-house Conan packages are bare `name/version`; never `@user/channel`.
- Application packages: `xe`, `xenoide`, `xepocs`. Tool packages: `glazer`,
  `cmake-checker`. Generated bindings: `glazed`.

## Distribution

Everything is pinned to an immutable reference; nothing tracks `main`.

| Pin | Lives in |
|---|---|
| devkit | `DEVKIT_REF` in each consumer's `mise.toml` |
| recipes | `RECIPES_REF` in each consumer's `mise.toml` |
| in-house packages | `XENOIDE_PACKAGES` in each consumer's `mise.toml` |
| `xenoide-base` | `python_requires = "xenoide-base/<DEVKIT_REF without v>"` |

`mise run setup` checks the devkit out into `.devkit/`, the recipes into
`.deps/xenoide-recipes`, and every `XENOIDE_PACKAGES` entry into `.deps/<repo>`,
then exports/builds them.

An **editable** registered in the consumer's Conan cache always wins over the
`.deps/` copy. Host and devcontainer caches are separate; register editables in
each.

## Build configurations

A config is `<toolchain>-<flavor>`. It is assembled from profile fragments:

```
conan install . -pr:h toolchain/<tc> -pr:h flavor/<fl> -pr:b toolchain/<tc>
```

Valid matrix (enforced in exactly one place: `XenoideCMake.validate()`):

| | debug | release | profile | asan | tsan | coverage | mutation |
|---|---|---|---|---|---|---|---|
| gcc | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ gcov | — |
| clang (Linux) | ✓ | ✓ | ✓ | ✓ canonical | ✓ canonical | ✓ llvm-cov canonical | ✓ only |
| apple-clang | ✓ | ✓ | ✓ | ✓ (+UBSan) | — | ✓ llvm-cov | — |
| msvc | ✓ | ✓ | ✓ | ✓ | — | — | — |
| clang-cl | ✓ | ✓ | ✓ | ✓ | — | — | — |
| mingw-gcc | ✓ | ✓ | ✓ | — | — | ✓ gcov | — |
| legacy-i686-gcc5 | ✓ | ✓ | — | — | — | — | — |

- Build folders are `${XENOIDE_BUILD_ROOT}/<toolchain>-<flavor>` (default
  `build/`). Several configs coexist; switching with `mise run use` never
  requires a clean.
- Active config precedence: `--config` > `XENOIDE_CONFIG` > `.xenoide/active`
  (written by `mise run use`) > host default.
- Instrumentation applies to first-party code only (`instrument` option), so
  `debug` → `asan` → `coverage` reuse the same Debug dependency binaries.

## Language

Strict C++17, no GNU extensions. See [CPP.md](CPP.md).

## Repository hygiene

Add these to every consumer's `.gitignore`:

```
.devkit/
.deps/
.conan2/
.xenoide/
```

`CONAN_HOME` is repo-local by default (`<repo>/.conan2`). The devcontainer uses
a separate `XENOIDE_CONAN_HOME=/conan` and `XENOIDE_BUILD_ROOT=build/devcontainer`
so host and container builds never share a cache or build tree.

## Task rules

- Shared logic lives once in Python (`devkit/mise/scripts`). No `.sh`/`.ps1`
  twins.
- Tasks take `--config`; there is never one task per config.
- Project-specific values come from `[env]` or per-repo files (`mull.yml`,
  `valgrind.supp`, `.cppcheck-suppressions`), never from hard-coded names in a
  shared task.

## Versions

Pre-1.0 SemVer (`v0.x.y`, starting at `v0.1.0`). Each repository owns a
`version` literal in its `conanfile.py` (the version file). Tags are release
markers only; there is no `set_version()`. Binaries embed version + commit SHA
(no timestamp). `glazer` and `glazed` share one version.

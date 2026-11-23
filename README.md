# Xenoide devkit

Shared infrastructure for every Xenoide repository:

- `conan/profiles` — `base` + `toolchain/*` + `flavor/*` fragments
- `conan/base` — the `xenoide-base` python_requires (base recipe class + CMake modules)
- `conan/tools` — the pinned analysis tools environment (cppcheck, cmake-checker)
- `mise/tasks` — the shared task catalogue
- `mise/scripts` — the one Python implementation behind those tasks
- `docker/` — the reference Linux dev/CI image and devcontainer template
- `docs/` — [CONVENTIONS.md](docs/CONVENTIONS.md) and the language guides
- `valgrind/`, `cppcheck/`, `debug/` — base suppressions and debugger init files

## Using the devkit from a repository

A consumer's `mise.toml` is the single configuration surface:

```toml
[env]
DEVKIT_URL = "https://github.com/XenoideSoftware/devkit.git"
DEVKIT_REF = "v0.1.0"
RECIPES_REF = "v0.1.0"
XENOIDE_PACKAGES = "glazer@v0.1.0,cmake-checker@v0.1.0"

[tools]
cmake = "3.31.6"
ninja = "1.12.1"
python = "3.12.8"
"pipx:conan" = "2.27.0"

[task_config]
includes = [".devkit/mise/tasks"]

[tasks."devkit:sync"]
run = "python mise/bootstrap.py sync"

[tasks.setup]
depends = ["devkit:sync"]
run = "python mise/bootstrap.py setup"
```

On a clean machine:

```
mise install
mise run setup
mise run build
mise run test
```

## Developing the devkit itself

Point a consumer at this checkout instead of the remote:

```
XENOIDE_DEVKIT_PATH=/path/to/devkit mise run devkit:sync
```

`mise run self-test` exercises the sample project under `tests/sample`.

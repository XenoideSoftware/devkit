# Conan guidelines

## The base class

Every first-party recipe extends `xenoide-base`:

```python
from conan import ConanFile


class MyRecipe(ConanFile):
    name = "mylib"
    version = "0.1.0"                     # the version file (source of truth)
    python_requires = "xenoide-base/0.1.0"
    python_requires_extend = "xenoide-base.XenoideCMake"
    package_type = "static-library"

    exports_sources = "CMakeLists.txt", "src/*"

    def requirements(self):
        self.requires("fmt/11.0.2")
```

Do not declare `settings`, `layout`, `generate`, `build`, `package` or the
standard options (`with_tests`, `instrument`, `werror`); the base class owns
them. Add project options with a plain `options` dictionary — the base merges
the standard ones in `init()`.

## Test dependencies

Use `test_requires`, never `requires`, for Catch2. The base class adds
`catch2/3.14.0` when `with_tests` is enabled.

## Profiles

`conan install` is always driven through profiles:

```
-pr:h conan/profiles/toolchain/<tc> -pr:h conan/profiles/flavor/<fl> -pr:b ...
```

Consumers never edit profiles to change a project option; they use
`default_options` or a named consumer profile.

## Channels

In-house packages are bare `name/version`. The `@xenoide/xenoide` channel is
retired, and the devkit hook fails an export that still uses it.

## Exporting recipes

There is no `export-recipes` script. Third-party/fork recipes are consumed from
`xenoide-recipes` as a Conan **local-recipes-index** remote, pinned by
`RECIPES_REF`:

```
conan remote add xenoide-recipes .deps/xenoide-recipes --type=local-recipes-index
```

`glazer` and `glazed` live in the `glazer` repository and are built by
`mise run setup` (or fetched as editables during development).

# Legacy Win9x / i686 toolchain (experimental)

Extracted unchanged from the monorepo:

- `bootstrap-clang/` — the bootstrap compiler used by the old Win9x i686
  toolchain.
- `windows-x86-gcc` — the original Conan profile, now a devkit toolchain
  fragment at `conan/profiles/toolchain/legacy-i686-gcc5`.

Enable it only with `XENOIDE_EXPERIMENTAL=1`; it is not part of the default
matrix and is hidden from `mise run configs`.

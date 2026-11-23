# CPP guidelines

## Standard

- **Strict C++17**: no C++20 features (concepts, ranges, `std::span` unless
  provided by `ms-gsl`/`gsl-lite` or `cpp-backport`).
- **Vendor extensions disabled**: no compiler-specific extensions. The Conan
  base profile sets `cppstd=17`/`cstd=17`.
- Use `auto` only when it infers a complex template type. Spell out simple types.

## Warnings

All code compiles with warnings enabled and warnings as errors (`werror`
defaults to True). Fix warnings; do not suppress them.

## Design

- RAII and memory safety. `std::unique_ptr` for exclusive ownership,
  `std::shared_ptr` only for genuine sharing.
- Prefer `std::string_view` for read-only string parameters; pass sinks by value
  and complex types by const reference.
- Engine code avoids exceptions in hot paths; prefer `tl::expected` or
  `std::optional`. Use assertions for invariants in debug builds.
- Namespaces: `xe` (engine), `xenoide` (IDE).
- Include order: own header, subsystem headers, third-party, standard library.
- Inject external-resource collaborators so they can be tested.

## Testing

See [TESTING.md](TESTING.md).

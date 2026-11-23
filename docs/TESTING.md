# Automated testing guidelines

## Glossary

- **SUT**: subject under test.
- **TU**: translation unit.
- **UT**: unit test.

## Principles

0. **Respect**: test code gets the same formatting, linting and review as
   feature code.
1. **Test public interfaces.** They are more stable than private helpers.
2. **High-performance tests.** Generate data in memory; avoid filesystems,
   databases, APIs and other external resources.
3. **Prefer property-based tests** over example-based tests. Use builders
   (`generate(EntityBuilder().param1().param2().build())`) and property
   assertions (`requireEntityProperty`).
4. **Determinism and independence.** Use Catch2's current seed, no shared
   mutable state, no leaked files or handles. Existing tests must keep passing.
5. **Do not reinvent the wheel.** Put generators and property assertions in a
   shared test library.

## Catch2

- A test for `TranslationUnit.cpp` lives in `TranslationUnitTest.cpp`.
- Name test targets `<library-name>-test` and place them as a sibling of the
  library code.
- Test one class property per `TEST_CASE`; use `SECTION`s for state changes.
- Check preconditions as well as postconditions.

## Running

```
mise run test --config clang-debug
mise run sanitize --kind asan
mise run coverage --export html --check 90
mise run mutation
mise run valgrind --tool memcheck
```

`xenoide_add_catch2_tests` attaches the sanitizer environment, so a plain
`ctest` behaves the same as the task.

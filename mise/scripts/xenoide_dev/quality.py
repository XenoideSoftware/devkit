"""Quality, diagnostics and profiling tasks.

Every function is a thin orchestration layer: the real work is done by the
host/devcontainer tools (clang-format, clang-tidy, cppcheck, cmake-checker,
Valgrind, Mull). Missing tools fail with an actionable message instead of a
raw "command not found".
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import build as build_mod
from . import coverage_reporter
from .config import Config, host_toolchain
from .util import (DevkitError, capture, fail, info, is_darwin, is_linux,
                   is_windows, require, run, source_files, warn)


# --------------------------------------------------------------------- helpers

def _llvm_major():
    cc = os.environ.get("XENOIDE_CC", "clang")
    try:
        text = capture([cc, "--version"], check=False)
    except Exception:
        return None
    match = re.search(r"(\d+)\.\d+", text)
    return match.group(1) if match else None


def _find_versioned(base, major=None):
    major = major or _llvm_major()
    if major:
        for candidate in (f"{base}-{major}", f"{base}{major}"):
            found = shutil.which(candidate)
            if found:
                return found
    return shutil.which(base)


def _llvm_companion(name, clang_version):
    """Resolve llvm-profdata/llvm-cov next to the detected clang."""
    if clang_version:
        found = shutil.which(f"{name}-{clang_version}")
        if found:
            return found
    return shutil.which(name)


def _tools_command(ctx):
    """Return a function that wraps a command with the tools environment."""
    base = ctx.root / ".xenoide" / "tools"
    bat = base / "conanbuild.bat"
    sh = base / "conanbuild.sh"
    if is_windows() and bat.is_file():
        def wrap(args):
            joined = " ".join(f'"{a}"' if " " in str(a) else str(a) for a in args)
            return ["cmd", "/c", f'call "{bat}" && {joined}']
        return wrap
    if sh.is_file():
        def wrap(args):
            return ["bash", "-c", f'source "{sh}" && exec "$@"', "bash", *args]
        return wrap
    return lambda args: list(args)


def _ensure_compile_commands(ctx, config):
    path = ctx.compile_commands(config)
    if not path.is_file():
        info(f"==> {path} missing; installing dependencies")
        build_mod.deps(ctx, config)
    if not path.is_file():
        fail(f"compile_commands.json not found in {ctx.build_dir(config)}")
    return path


def _compile_db_files(path, root):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    files = []
    seen = set()
    for entry in data:
        filename = entry.get("file")
        if not filename:
            continue
        candidate = Path(filename)
        if not candidate.is_absolute():
            candidate = Path(entry.get("directory", root)) / candidate
        candidate = candidate.resolve()
        if not str(candidate).startswith(str(Path(root).resolve())):
            continue
        if candidate not in seen and candidate.is_file():
            seen.add(candidate)
            files.append(candidate)
    return files


def _modified_files(ctx):
    result = run(["git", "status", "--porcelain"], cwd=ctx.root, capture=True, check=False)
    files = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        candidate = ctx.root / path
        if candidate.is_file() and candidate.suffix.lower() in (
                ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"):
            files.append(candidate)
    return files


def _batch(items, size=50):
    for index in range(0, len(items), size):
        yield items[index:index + size]


# ---------------------------------------------------------------------- format

def format_sources(ctx, check=False, files=None):
    tool = require("clang-format", "install clang-format or use the devcontainer")
    targets = [Path(path).resolve() for path in files] if files else list(source_files(ctx.root))
    if not targets:
        info("No C/C++ sources found.")
        return
    args_common = []
    devkit_style = ctx.devkit / ".clang-format"
    if devkit_style.is_file() and not (ctx.root / ".clang-format").is_file():
        args_common.append(f"--style=file:{devkit_style}")
    info(f"==> clang-format {'--check' if check else ''} on {len(targets)} file(s)")
    for batch in _batch(targets):
        args = [tool, *args_common]
        if check:
            args += ["--dry-run", "--Werror"]
        else:
            args += ["-i"]
        args += [str(path) for path in batch]
        result = run(args, cwd=ctx.root, check=False, capture=check)
        if result.returncode != 0:
            if check:
                print(result.stdout or "")
                fail("clang-format found files that need formatting")
            raise DevkitError("clang-format failed")


# ------------------------------------------------------------------------ tidy

def tidy(ctx, config, fix=False, full=False, file=None):
    _ensure_compile_commands(ctx, config)
    tool = _find_versioned("clang-tidy")
    if not tool:
        fail("clang-tidy not found (host or devcontainer provides it; `doctor` reports the version)")
    if file:
        targets = [Path(file).resolve()]
    elif full:
        targets = _compile_db_files(ctx.compile_commands(config), ctx.root)
    else:
        targets = _modified_files(ctx)
        if not targets:
            info("No modified C/C++ files. Nothing to tidy (use --full to check everything).")
            return
    info(f"==> clang-tidy on {len(targets)} file(s) [{config.name}]")
    devkit_config = ctx.devkit / ".clang-tidy"
    local_config = ctx.root / ".clang-tidy"
    header_filter = f"^({ctx.root.name})/src/"
    findings = 0
    for target in targets:
        args = [tool, "-p", str(ctx.build_dir(config)),
                f"--header-filter={header_filter}"]
        if devkit_config.is_file() and not local_config.is_file():
            args.append(f"--config-file={devkit_config}")
        args.append(str(target))
        if fix:
            args.append("--fix")
        result = run(args, cwd=ctx.root, check=False, capture=True)
        output = result.stdout or ""
        if output:
            print(output)
        findings += len(re.findall(r"(?m):\s*(?:warning|error):", output))
        if result.returncode != 0 and not findings:
            raise DevkitError(f"clang-tidy failed on {target}")
    if findings:
        fail(f"clang-tidy reported {findings} finding(s)")


# -------------------------------------------------------------------- cppcheck

def cppcheck(ctx, config, full=False, file=None):
    _ensure_compile_commands(ctx, config)
    wrap = _tools_command(ctx)
    build_dir = ctx.build_dir(config)
    cache_dir = build_dir / "cppcheck"
    cache_dir.mkdir(parents=True, exist_ok=True)

    suppressions = [ctx.devkit / "cppcheck" / "suppressions.txt"]
    local = ctx.root / ".cppcheck-suppressions"
    if local.is_file():
        suppressions.append(local)

    args = ["cppcheck",
            f"--project={ctx.compile_commands(config)}",
            f"--cppcheck-build-dir={cache_dir}",
            "--enable=warning,style,performance,portability",
            "--inline-suppr",
            "--error-exitcode=0",
            "--template={file}:{line}: {severity}: {message} [{id}]"]
    for suppression in suppressions:
        if suppression.is_file():
            args.append(f"--suppressions-list={suppression}")

    if file:
        args.append(f"--file-filter={file}")
    elif not full:
        modified = _modified_files(ctx)
        if not modified:
            info("No modified C/C++ files. Nothing to cppcheck (use --full).")
            return
        args += [f"--file-filter={ctx.root / path}" for path in modified]

    info(f"==> cppcheck [{config.name}]")
    timeouts = os.environ.get("XENOIDE_CPPCHECK_TIMEOUT")
    if timeouts:
        args.append(f"--check-level={timeouts}")
    result = run(wrap(args), cwd=ctx.root, check=False, capture=True)
    output = result.stdout or ""
    if output:
        print(output)
    # Style findings are reported but do not fail the task; only real defects
    # (warning/error) gate the exit code (Q2).
    fatal = re.findall(r"(?m):\s*(?:error|warning):", output)
    if result.returncode != 0:
        raise DevkitError(f"cppcheck failed ({result.returncode})")
    if fatal:
        fail(f"cppcheck reported {len(fatal)} warning/error finding(s)")


# ----------------------------------------------------------------- cmake-check

def cmake_check(ctx, config):
    ctx.require_devkit()
    build_dir = ctx.build_dir(config)
    build_mod.deps(ctx, config)

    query_dir = build_dir / ".cmake" / "api" / "v1" / "query" / "client-xenoide-cmake-check"
    query_dir.mkdir(parents=True, exist_ok=True)
    (query_dir / "query.json").write_text(
        '{"requests": [{"kind": "codemodel", "version": 2}, {"kind": "cmakeFiles", "version": 1}]}\n',
        encoding="utf-8")
    trace = build_dir / "trace.json"
    if trace.exists():
        trace.unlink()

    run(["cmake", "--preset", ctx.preset(config),
         "--trace-format=json-v1", f"--trace-redirect={trace}"], cwd=ctx.root)

    wrap = _tools_command(ctx)
    info(f"==> cmake-checker [{config.name}]")
    run(wrap(["xe-cmake-checker", "--project", str(ctx.root),
              "--project-build-dir", str(build_dir)]), cwd=ctx.root)


# ------------------------------------------------------------------- sanitizers

def sanitize(ctx, kind="asan", config=None):
    if kind not in ("asan", "tsan"):
        fail("--kind must be asan or tsan")
    toolchain = "clang" if shutil.which("clang") else host_toolchain()
    cfg = cfg_or(config, toolchain, kind)
    info(f"==> sanitize: {cfg.name}")
    build_mod.test(ctx, cfg)


def cfg_or(config, toolchain, flavor):
    return config if config is not None else Config(toolchain, flavor)


# -------------------------------------------------------------------- coverage

def _ctest_json(build_dir):
    result = run(["ctest", "--test-dir", str(build_dir), "--show-only=json-v1"],
                 capture=True, check=False)
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {"tests": []}


def _test_executables(build_dir):
    executables = []
    seen = set()
    for test in _ctest_json(build_dir).get("tests", []):
        command = test.get("command")
        if not command:
            continue
        exe = None
        for candidate in command:
            if not isinstance(candidate, str):
                continue
            if candidate in ("cmd", "/c"):
                continue
            path = Path(candidate)
            # Skip the generated environment launchers; the real binary is
            # the next executable in the command line.
            if path.suffix.lower() in (".sh", ".bat", ".cmd"):
                continue
            if "_NOT_BUILT" in candidate:
                break
            if path.is_file() and os.access(path, os.X_OK):
                exe = candidate
                break
        if exe is None or exe in seen:
            continue
        seen.add(exe)
        executables.append(exe)
    return executables


def _run_gcov(build_dir, report_dir):
    gcov = require("gcov")
    output = report_dir / ".gcov-json"
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    exclude = re.compile(r"(-test/|/\.conan2/|/\.deps/)")
    for gcno in build_dir.rglob("*.gcno"):
        if exclude.search(str(gcno)):
            continue
        gcda = gcno.with_suffix(".gcda")
        if not gcda.is_file():
            continue
        work = output / gcno.parent.name
        work.mkdir(parents=True, exist_ok=True)
        run([gcov, "-j", f"-o", str(gcno.parent), str(gcno)], cwd=work, check=False)
        count += 1
    if count == 0:
        fail("no .gcda files found; run the coverage tests first")
    info(f"==> gcov processed {count} translation unit(s)")
    return output


def _run_llvm_cov(ctx, config, report_dir, major):
    profdata = _llvm_companion("llvm-profdata", major)
    llvm_cov = _llvm_companion("llvm-cov", major)
    if not profdata or not llvm_cov:
        fail("llvm-profdata/llvm-cov not found next to the detected clang")
    build_dir = ctx.build_dir(config)
    # Only test-run profiles count. Catch2's build-time `--list-tests` writes a
    # default.profraw into the build root; including it produced reports that
    # claimed ~12% coverage while never seeing the tests themselves (C3).
    profiles_dir = build_dir / "profiles"
    profiles = sorted(profiles_dir.rglob("*.profraw")) if profiles_dir.is_dir() else []
    profiles = [p for p in profiles if p.name != "default.profraw"]
    if not profiles:
        fail("no test-run .profraw profiles found in "
             f"{profiles_dir}; the coverage tests did not inherit LLVM_PROFILE_FILE")
    merged = report_dir / "merged.profdata"
    run([profdata, "merge", "-o", str(merged), *[str(p) for p in profiles]])
    executables = _test_executables(build_dir)
    if not executables:
        fail("no instrumented test executables discovered")

    output = report_dir / "coverage.json"
    args = [llvm_cov, "export", f"-instr-profile={merged}",
            "-ignore-filename-regex=(-test/|/\\.conan2/|/\\.deps/)"]
    # All test executables share the merged profile; passing them as objects
    # to a single export yields one consistent report instead of one partial
    # report per executable.
    for exe in executables:
        args.append(f"-object={exe}")
    result = run(args, capture=True, check=False)
    # llvm-cov writes diagnostics ("warning: N functions have mismatched
    # data") to stderr; capture() merges streams, so slice out the JSON body.
    text = result.stdout or ""
    start = text.find("{")
    end = text.rfind("}")
    if result.returncode != 0 or start < 0 or end < start:
        fail(f"llvm-cov export failed:\n{text}")
    output.write_text(text[start:end + 1], encoding="utf-8")
    return [output]


def coverage(ctx, config=None, export="text", check=None, output_dir=None, clean=False):
    if config:
        cfg = config
    else:
        toolchain = "clang" if shutil.which("clang") else host_toolchain()
        cfg = Config(toolchain, "coverage")
    if cfg.flavor != "coverage":
        fail(f"coverage requires a coverage flavor (got {cfg.name})")

    report_dir = Path(output_dir) if output_dir else ctx.build_dir(cfg) / "coverage"
    report_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        build_mod.clean(ctx, cfg)
        if report_dir.is_dir():
            shutil.rmtree(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

    build_mod.test(ctx, cfg)
    major = _llvm_major() if cfg.toolchain in ("clang", "apple-clang") else None
    tool = "llvm-cov" if cfg.toolchain in ("clang", "apple-clang") else "gcov"

    if tool == "gcov":
        gcov_dir = _run_gcov(ctx.build_dir(cfg), report_dir)
        coverage_reporter.report(ctx.root, "gcov", export, report_dir,
                                 gcov_dir=gcov_dir, check=check)
    else:
        json_files = _run_llvm_cov(ctx, cfg, report_dir, major)
        coverage_reporter.report(ctx.root, "llvm-cov", export, report_dir,
                                 json_files=json_files, check=check)


# -------------------------------------------------------------------- mutation

def _mull(major, name):
    if not major:
        fail("Clang version could not be detected for Mull")
    for candidate in (f"{name}-{major}", name):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _clang_major(cc):
    try:
        text = capture([cc, "--version"], check=False)
    except Exception:
        return None
    match = re.search(r"(\d+)\.\d+", text)
    return match.group(1) if match else None


def _mull_plugin(major):
    for candidate in (f"mull-ir-frontend-{major}",
                      "/usr/lib/mull-ir-frontend-" + str(major),
                      "/usr/local/lib/mull-ir-frontend-" + str(major)):
        if candidate and (shutil.which(candidate) or Path(candidate).is_file()):
            return candidate
    return None


def _mutation_compiler():
    """Pick a clang whose LLVM major has a matching Mull installation (M4)."""
    explicit = os.environ.get("XENOIDE_CC")
    if explicit:
        major = _clang_major(explicit)
        return explicit, major
    candidates = []
    default = shutil.which("clang")
    if default:
        candidates.append(default)
    for version in (19, 18, 17, 20):
        found = shutil.which(f"clang-{version}")
        if found and found not in candidates:
            candidates.append(found)
    for candidate in candidates:
        major = _clang_major(candidate)
        if major and shutil.which(f"mull-runner-{major}") and _mull_plugin(major):
            return candidate, major
    return (default, _clang_major(default)) if default else (None, None)


# ------------------------------------------------------------------- Mull config

def _yaml_lines(text):
    lines = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        body = raw.split(" #", 1)[0].rstrip()
        if not body.strip():
            continue
        lines.append((len(body) - len(body.lstrip()), body.strip()))
    return lines


def _yaml_scalar(text):
    text = text.strip()
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    if text.startswith(("'", '"')) and text.endswith(("'", '"')):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        return text


def _parse_simple_yaml(text):
    """Parse the small YAML subset used by mull.yml (no external dependency)."""
    lines = _yaml_lines(text)

    def parse(index, indent):
        if index >= len(lines):
            return {}, index
        if lines[index][1].startswith("- "):
            values = []
            while (index < len(lines) and lines[index][0] == indent
                   and lines[index][1].startswith("- ")):
                values.append(_yaml_scalar(lines[index][1][2:]))
                index += 1
            return values, index
        result = {}
        while index < len(lines) and lines[index][0] == indent:
            content = lines[index][1]
            if content.startswith("- "):
                break
            key, _, value = content.partition(":")
            key = key.strip()
            value = value.strip()
            index += 1
            if value:
                result[key] = _yaml_scalar(value)
            elif index < len(lines) and lines[index][0] > indent:
                child, index = parse(index, lines[index][0])
                result[key] = child
            elif index < len(lines) and lines[index][0] == indent \
                    and lines[index][1].startswith("- "):
                child, index = parse(index, indent)
                result[key] = child
            else:
                result[key] = None
        return result, index

    if not lines:
        return {}
    value, _ = parse(0, lines[0][0])
    return value if isinstance(value, dict) else {}


def _merge_dict(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_dict(base[key], value)
        elif isinstance(value, list) and isinstance(base.get(key), list):
            base[key] = base[key] + [item for item in value if item not in base[key]]
        else:
            base[key] = value
    return base


def _mull_config(ctx, build_dir, mutators=None, include=None, workers=None, timeout=None):
    base_file = ctx.devkit / "mull.yml"
    config = _parse_simple_yaml(base_file.read_text(encoding="utf-8")) \
        if base_file.is_file() else {}
    local_file = ctx.root / "mull.yml"
    if local_file.is_file():
        _merge_dict(config, _parse_simple_yaml(local_file.read_text(encoding="utf-8")))
    if mutators:
        config["mutators"] = [item.strip() for item in mutators.split(",") if item.strip()]
    if include:
        config["includePaths"] = [include]
    parallel = config.setdefault("parallelization", {})
    if workers is not None:
        parallel["workers"] = int(workers)
        parallel["executionWorkers"] = int(workers)
    if timeout is not None:
        parallel["timeout"] = int(timeout)
    path = build_dir / "mull.yml"
    # JSON is a subset of YAML, so Mull parses it as a normal mull.yml.
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def _merge_mull_databases(databases, target):
    import sqlite3

    target.unlink(missing_ok=True)
    destination = sqlite3.connect(target)
    try:
        tables = None
        for source_path in databases:
            source = sqlite3.connect(source_path)
            try:
                if tables is None:
                    tables = [row[0] for row in source.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")]
                    for (ddl,) in source.execute(
                            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"):
                        destination.execute(ddl)
                for table in tables:
                    columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
                    placeholders = ",".join("?" for _ in columns)
                    rows = source.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                    destination.executemany(
                        f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) "
                        f"VALUES ({placeholders})", rows)
            finally:
                source.close()
        destination.commit()
    finally:
        destination.close()


def mutation(ctx, config=None, target=None, threshold=None, dry_run=False, clean=False,
             mutators=None, include=None, workers=None, timeout=None):
    if not is_linux():
        fail("mutation testing is Linux-only (Mull)")
    cc, major = _mutation_compiler()
    if not major:
        fail("Clang version could not be detected for Mull")
    if not os.environ.get("XENOIDE_CC"):
        cxx = cc.replace("clang", "clang++", 1) if "clang" in cc else "clang++"
        os.environ["XENOIDE_CC"] = cc
        os.environ["XENOIDE_CXX"] = cxx
        info(f"==> Using {cc} for mutation (matches Mull {major})")
    runner = _mull(major, "mull-runner")
    reporter = _mull(major, "mull-reporter")
    plugin = _mull_plugin(major)
    if not runner or not reporter or not plugin:
        fail(f"Mull not found for LLVM {major}; install mull-runner-{major}, "
             f"mull-reporter-{major} and mull-ir-frontend-{major}, or set "
             f"XENOIDE_CC=clang-<major-matching-mull> XENOIDE_CXX=clang++-<...>")

    cfg = config or Config("clang", "mutation")
    if cfg.flavor != "mutation":
        fail(f"mutation requires the mutation flavor (got {cfg.name})")
    build_dir = ctx.build_dir(cfg)
    build_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        build_mod.clean(ctx, cfg)
        build_dir.mkdir(parents=True, exist_ok=True)

    config_path = _mull_config(ctx, build_dir, mutators=mutators,
                               include=include, workers=workers, timeout=timeout)
    os.environ["MULL_CONFIG"] = str(config_path)
    info(f"==> Using config {config_path}")
    build_mod.build(ctx, cfg)

    report_dir = build_dir / "mutation"
    report_dir.mkdir(parents=True, exist_ok=True)
    for stale in report_dir.glob("*.sqlite"):
        stale.unlink()

    executables = _test_executables(build_dir)
    if target:
        executables = [exe for exe in executables if Path(exe).stem == target]
    if not executables:
        fail("no test executables discovered for mutation")

    databases = []
    info(f"==> mull-runner on {len(executables)} executable(s)")
    for exe in executables:
        stem = Path(exe).stem
        runner_args = ["--reporters", "SQLite", "--report-dir", str(report_dir),
                       "--report-name", stem, "--allow-surviving"]
        if dry_run:
            runner_args.append("--dry-run")
        if workers is not None:
            runner_args += ["--workers", str(workers)]
        if timeout is not None:
            runner_args += ["--timeout", str(timeout)]
        run([runner, *runner_args, exe], cwd=ctx.root)
        database = report_dir / f"{stem}.sqlite"
        if database.is_file():
            databases.append(database)
            # One IDE-style report per executable (M2: never overwrite).
            run([reporter, "--report-dir", str(report_dir), "--report-name", stem,
                 "--allow-surviving", "--reporters", "IDE", str(database)],
                cwd=ctx.root, check=False)

    if not databases:
        fail(f"expected Mull reports in {report_dir}")

    combined = report_dir / "xenoide.sqlite"
    _merge_mull_databases(databases, combined)
    reporter_args = ["--report-dir", str(report_dir), "--report-name", "xenoide"]
    if threshold is not None:
        reporter_args += ["--mutation-score-threshold", str(threshold)]
    else:
        reporter_args += ["--allow-surviving"]
    run([reporter, *reporter_args, "--reporters", "IDE", str(combined)], cwd=ctx.root)
    info(f"==> Mutation reports: {', '.join(db.name for db in databases)} "
         f"({len(databases)} executable(s), combined: {combined.name})")


# -------------------------------------------------------------------- valgrind

def _suppression_file(ctx):
    parts = []
    base = ctx.devkit / "valgrind" / "xenoide.supp"
    if base.is_file():
        parts.append(base.read_text(encoding="utf-8"))
    local = ctx.root / "valgrind.supp"
    if local.is_file():
        parts.append(local.read_text(encoding="utf-8"))
    if not parts:
        return None
    merged_text = "\n".join(parts)
    # Valgrind rejects a file whose only block has no concrete obj:/fun: line.
    # Treat a comments-only file as "no suppressions" (V3).
    if not re.search(r"(?m)^\s*\{", merged_text):
        return None
    merged = ctx.root / ".xenoide" / "valgrind.supp"
    merged.parent.mkdir(parents=True, exist_ok=True)
    merged.write_text(merged_text, encoding="utf-8")
    return merged


def _valgrind_defects(build_dir):
    """Return (logs, defect_count) from ctest -T memcheck logs."""
    logs = sorted(build_dir.rglob("MemoryChecker.*.log"))
    defects = 0
    for log in logs:
        text = log.read_text(encoding="utf-8", errors="replace")
        for match in re.findall(r"ERROR SUMMARY:\s*(\d+) errors", text):
            defects += int(match)
    return logs, defects


def valgrind(ctx, tool="memcheck", config=None, target=None, args=None):
    if not is_linux():
        fail("Valgrind is Linux-only")
    valgrind_bin = require("valgrind")
    version = capture([valgrind_bin, "--version"], check=False)
    info(f"==> {version}")

    profiling = tool in ("callgrind", "cachegrind", "massif")
    if config:
        cfg = config
    else:
        toolchain = host_toolchain()
        cfg = Config(toolchain, "profile" if profiling else "debug")
    build_mod.build(ctx, cfg)

    if tool in ("memcheck", "helgrind", "drd"):
        if cfg.flavor in ("asan", "tsan", "coverage", "mutation"):
            fail("Valgrind cannot run an instrumented config; use a plain debug build")
        build_dir = ctx.build_dir(cfg)
        out_dir = build_dir / "valgrind"
        out_dir.mkdir(parents=True, exist_ok=True)
        suppression = _suppression_file(ctx)
        if tool == "memcheck":
            options = "--leak-check=full --track-origins=yes --error-exitcode=1"
        else:
            options = f"--tool={tool} --error-exitcode=1"
        # ctest -T memcheck locates DartConfiguration.tcl through --test-dir;
        # the CTEST_MEMORYCHECK_* environment variables are ignored (V1/V2).
        cmd = [
            "ctest", "--test-dir", str(build_dir), "-T", "memcheck",
            "--output-on-failure",
            "--overwrite", f"MemoryCheckCommand={valgrind_bin}",
            "--overwrite", f"MemoryCheckCommandOptions={options}",
        ]
        if suppression:
            cmd += ["--overwrite", f"MemoryCheckSuppressionFile={suppression}"]
        info(f"==> ctest -T memcheck ({tool}) [{cfg.name}]")
        result = run(cmd, cwd=build_dir, check=False)
        logs, defects = _valgrind_defects(build_dir)
        if not logs:
            fail("ctest -T memcheck produced no MemoryChecker logs; "
                 "is DartConfiguration.tcl present in the build directory?")
        for log in logs:
            shutil.copy2(log, out_dir / f"{tool}-{log.name}")
        info(f"==> {len(logs)} Valgrind log(s) copied to {out_dir}")
        if result.returncode != 0:
            fail(f"ctest -T memcheck failed ({result.returncode})")
        if defects:
            fail(f"{tool} reported {defects} error(s); see {out_dir}")
        info(f"==> {tool}: 0 errors")
        return

    # Profiling tools need an explicit target executable.
    if not target:
        fail(f"--tool {tool} requires --target <executable>")
    candidate = None
    for exe in _test_executables(ctx.build_dir(cfg)):
        if Path(exe).stem == target:
            candidate = exe
            break
    if not candidate:
        matches = [p for p in ctx.build_dir(cfg).rglob(target + "*")
                   if p.is_file() and os.access(p, os.X_OK)]
        candidate = str(matches[0]) if matches else None
    if not candidate:
        fail(f"executable target '{target}' not found in {ctx.build_dir(cfg)}")

    out_dir = ctx.build_dir(cfg) / "valgrind"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{tool}.out"
    cmd = [valgrind_bin, f"--tool={tool}", f"--{tool}-out-file={out_file}"]
    cmd += [str(candidate), *(args or [])]
    run(cmd, cwd=ctx.root, check=False)
    info(f"==> {tool} output: {out_file}")

    # Print a short human-readable summary (V4).
    annotator = {"callgrind": "callgrind_annotate",
                 "cachegrind": "cg_annotate",
                 "massif": "ms_print"}.get(tool)
    if annotator and shutil.which(annotator) and out_file.is_file():
        result = run([annotator, str(out_file)], cwd=ctx.root,
                     capture=True, check=False)
        if result.returncode == 0 and result.stdout:
            print("\n".join(result.stdout.splitlines()[:40]))


# --------------------------------------------------------------------- debug

def _find_executable(ctx, config, target):
    for exe in _test_executables(ctx.build_dir(config)):
        if Path(exe).stem == target:
            return exe
    root = ctx.build_dir(config)
    if root.is_dir():
        for path in root.rglob(target + "*"):
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def debug(ctx, config, target, debugger=None, args=None, test_name=None):
    exe = _find_executable(ctx, config, target)
    if not exe:
        fail(f"executable '{target}' not found in {ctx.build_dir(config)}; build it first")
    if debugger is None:
        debugger = "gdb" if config.toolchain in ("gcc", "mingw-gcc") else "lldb"
    if config.toolchain == "msvc":
        info("MSVC: open the target in Visual Studio with:")
        info(f'  devenv /debugexe "{exe}"')
        info("  (or install cdb and use `cdb -o -c \"g; q\" exe`)")
        return

    extra = list(args or [])
    if test_name:
        extra = [test_name, *extra]

    if debugger == "gdb":
        cmd = ["gdb", "--args", exe, *extra]
    else:
        cmd = ["lldb", exe, "--", *extra]
    info(f"==> {debugger}: {exe}")
    run(cmd, cwd=ctx.root, check=False)


def debug_core(ctx, config, core=None, debugger=None):
    exe = None
    if core:
        core_path = Path(core)
    else:
        candidates = sorted(ctx.root.glob("core*"), key=lambda p: p.stat().st_mtime, reverse=True)
        core_path = candidates[0] if candidates else None
    if not core_path or not core_path.is_file():
        fail("no core dump found in the repository root; pass one explicitly")
    info(f"==> core: {core_path}")
    info("    Pick the matching binary and run: gdb <binary> " + str(core_path))
    info("    (use `mise run debug <target>` to locate a binary)")


def launch_json(ctx, config):
    vscode = ctx.root / ".vscode"
    vscode.mkdir(parents=True, exist_ok=True)
    path = vscode / "launch.json"
    configurations = []
    for exe in _test_executables(ctx.build_dir(config)):
        name = Path(exe).stem
        configurations.append({
            "name": f"gdb: {name}",
            "type": "cppdbg",
            "request": "launch",
            "program": exe,
            "cwd": str(ctx.root),
            "MIMode": "gdb",
            "setupCommands": [{"text": "-enable-pretty-printing"}],
        })
        configurations.append({
            "name": f"lldb: {name}",
            "type": "lldb",
            "request": "launch",
            "program": exe,
            "cwd": str(ctx.root),
        })
    if not configurations:
        configurations.append({
            "name": "debug: no targets",
            "type": "cppdbg",
            "request": "launch",
            "program": "",
        })
    path.write_text(json.dumps({"version": "0.2.0", "configurations": configurations},
                               indent=4) + "\n", encoding="utf-8")
    info(f"==> Wrote {path}")

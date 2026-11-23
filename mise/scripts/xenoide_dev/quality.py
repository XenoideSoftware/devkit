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
    for target in targets:
        args = [tool, "-p", str(ctx.build_dir(config)), str(target)]
        if fix:
            args.append("--fix")
        run(args, cwd=ctx.root, check=False)


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
            "--error-exitcode=1",
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
    run(wrap(args), cwd=ctx.root)


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
        exe = command[0]
        if "_NOT_BUILT" in exe or not Path(exe).is_file():
            continue
        if exe not in seen:
            seen.add(exe)
            executables.append(exe)
    return executables


def _run_gcov(build_dir, report_dir):
    gcov = require("gcov")
    output = report_dir / ".gcov-json"
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    for gcno in build_dir.rglob("*.gcno"):
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
    profiles = list(build_dir.rglob("*.profraw"))
    if not profiles:
        fail("no .profraw profiles found; LLVM_PROFILE_FILE is set for the coverage tests")
    merged = report_dir / "merged.profdata"
    run([profdata, "merge", "-o", str(merged), *[str(p) for p in profiles]])
    executables = _test_executables(build_dir)
    if not executables:
        fail("no instrumented test executables discovered")
    exports = report_dir / ".llvm-exports"
    exports.mkdir(parents=True, exist_ok=True)
    generated = []
    for index, exe in enumerate(executables):
        out = exports / f"report-{index}.json"
        result = run([llvm_cov, "export", f"-instr-profile={merged}", exe],
                     capture=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            out.write_text(result.stdout, encoding="utf-8")
            generated.append(out)
    if not generated:
        fail("llvm-cov export produced no reports")
    return generated


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


def mutation(ctx, config=None, target=None, threshold=None, dry_run=False, clean=False):
    if not is_linux():
        fail("mutation testing is Linux-only (Mull)")
    major = _llvm_major()
    runner = _mull(major, "mull-runner")
    reporter = _mull(major, "mull-reporter")
    plugin = None
    for candidate in (f"mull-ir-frontend-{major}",
                      "/usr/lib/mull-ir-frontend-" + str(major),
                      "/usr/local/lib/mull-ir-frontend-" + str(major)):
        if candidate and (shutil.which(candidate) or Path(candidate).is_file()):
            plugin = candidate
            break
    if not runner or not reporter or not plugin:
        fail(f"Mull not found for LLVM {major}; install mull-runner-{major}, "
             f"mull-reporter-{major} and mull-ir-frontend-{major}")

    cfg = config or Config("clang", "mutation")
    if cfg.flavor != "mutation":
        fail(f"mutation requires the mutation flavor (got {cfg.name})")
    if clean:
        build_mod.clean(ctx, cfg)
    build_mod.build(ctx, cfg)

    report_dir = ctx.build_dir(cfg) / "mutation"
    report_dir.mkdir(parents=True, exist_ok=True)
    db = report_dir / "xenoide.sqlite"
    if db.exists():
        db.unlink()

    executables = _test_executables(ctx.build_dir(cfg))
    if target:
        executables = [exe for exe in executables if Path(exe).stem == target]
    if not executables:
        fail("no test executables discovered for mutation")

    runner_args = ["--reporters", "SQLite", "--report-dir", str(report_dir),
                   "--report-name", "xenoide", "--allow-surviving"]
    if dry_run:
        runner_args.append("--dry-run")
    info(f"==> mull-runner on {len(executables)} executable(s)")
    for exe in executables:
        run([runner, *runner_args, exe], cwd=ctx.root)

    if not db.is_file():
        fail(f"expected Mull report at {db}")
    reporter_args = ["--report-dir", str(report_dir), "--report-name", "xenoide"]
    if threshold is not None:
        reporter_args += ["--mutation-score-threshold", str(threshold)]
    else:
        reporter_args += ["--allow-surviving"]
    run([reporter, *reporter_args, "--reporters", "IDE", str(db)], cwd=ctx.root)


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
    merged = ctx.root / ".xenoide" / "valgrind.supp"
    merged.parent.mkdir(parents=True, exist_ok=True)
    merged.write_text("\n".join(parts), encoding="utf-8")
    return merged


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
        out_dir = ctx.build_dir(cfg) / "valgrind"
        out_dir.mkdir(parents=True, exist_ok=True)
        suppression = _suppression_file(ctx)
        options = "--leak-check=full --track-origins=yes --error-exitcode=1"
        if tool != "memcheck":
            options = "--error-exitcode=1"
        env = {
            "CTEST_MEMORYCHECK_COMMAND": valgrind_bin,
            "CTEST_MEMORYCHECK_COMMAND_OPTIONS": options,
        }
        if suppression:
            env["CTEST_MEMORYCHECK_SUPPRESSIONS_FILE"] = str(suppression)
            options += f" --suppressions={suppression}"
            env["CTEST_MEMORYCHECK_COMMAND_OPTIONS"] = options
        info(f"==> ctest -T memcheck ({tool}) [{cfg.name}]")
        run(["ctest", "--preset", ctx.preset(cfg), "-T", "memcheck",
             "--output-on-failure"], cwd=ctx.root, env=env, check=False)
        logs = list((ctx.build_dir(cfg) / "Testing").rglob("MemoryChecker.*.log"))
        for log in logs:
            shutil.copy2(log, out_dir / f"{tool}-{log.name}")
        info(f"==> Valgrind logs copied to {out_dir}")
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
    if tool == "massif":
        cmd.append(f"--massif-out-file={out_file}")
    cmd += [str(candidate), *(args or [])]
    run(cmd, cwd=ctx.root, check=False)
    info(f"==> {tool} output: {out_file}")


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

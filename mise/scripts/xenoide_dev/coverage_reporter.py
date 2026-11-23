#!/usr/bin/env python3
"""Aggregate coverage data and emit text / CSV / HTML / Cobertura reports.

Zero dependency (standard library only). Adapted from the monorepo's
``mise/coverage_reporter.py`` so it works per repository instead of per
monorepo, and so the same code handles gcov and llvm-cov.
"""

import argparse
import csv
import gzip
import html
import json
import os
import pathlib
import sys


EXCLUDED_PARTS = ("build", "build-", "coverage", "mutation", ".conan2", ".deps",
                  ".devkit", ".git", "generated", "CMakeFiles")


def _norm(path):
    return os.path.normpath(os.path.abspath(path))


class Reporter:
    def __init__(self, source_dir):
        self.source_dir = _norm(source_dir)

    def source_under_project(self, path):
        path = _norm(path)
        if not (path == self.source_dir or path.startswith(self.source_dir + os.sep)):
            return False
        rel = os.path.relpath(path, self.source_dir)
        for part in rel.split(os.sep):
            if part in EXCLUDED_PARTS or part.startswith("build-"):
                return False
        return True

    def relative_source(self, path):
        return os.path.relpath(_norm(path), self.source_dir)

    def merge(self, aggregate, path, total, covered):
        entry = aggregate.setdefault(self.relative_source(path), [set(), set()])
        entry[0].update(total)
        entry[1].update(covered)

    def parse_llvm_json(self, json_path):
        with open(json_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        result = {}
        for data in payload.get("data", []):
            for file_info in data.get("files", []):
                path = file_info.get("filename", "")
                if not path or not self.source_under_project(path):
                    continue
                total, covered = set(), set()
                for segment in file_info.get("segments", []):
                    if len(segment) < 4:
                        continue
                    line, count, has_count = segment[0], segment[2], segment[3]
                    if not has_count:
                        continue
                    total.add(line)
                    if count > 0:
                        covered.add(line)
                self.merge(result, path, total, covered)
        return result

    def parse_gcov_json(self, json_gz_path):
        with gzip.open(json_gz_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        result = {}
        for file_info in payload.get("files", []):
            path = file_info.get("file", "")
            if not path or not self.source_under_project(path):
                continue
            total, covered = set(), set()
            for line_info in file_info.get("lines", []):
                line = line_info.get("line_number")
                if line is None:
                    continue
                total.add(line)
                if line_info.get("count", 0) > 0:
                    covered.add(line)
            self.merge(result, path, total, covered)
        return result

    def collect_llvm(self, files):
        aggregate = {}
        for path in files:
            for rel, (total, covered) in self.parse_llvm_json(path).items():
                entry = aggregate.setdefault(rel, [set(), set()])
                entry[0].update(total)
                entry[1].update(covered)
        return aggregate

    def collect_gcov(self, directory):
        aggregate = {}
        directory = pathlib.Path(directory)
        json_files = sorted(directory.rglob("*.gcov.json.gz"))
        if not json_files:
            raise RuntimeError(f"no .gcov.json.gz files found under {directory}")
        for path in json_files:
            for rel, (total, covered) in self.parse_gcov_json(path).items():
                entry = aggregate.setdefault(rel, [set(), set()])
                entry[0].update(total)
                entry[1].update(covered)
        return aggregate


def build_stats(aggregate):
    stats = []
    for rel, (total_lines, covered_lines) in aggregate.items():
        total = len(total_lines)
        covered = len(covered_lines)
        percent = (covered / total * 100.0) if total else 0.0
        stats.append({"file": rel, "lines": total, "covered": covered, "percent": percent})
    stats.sort(key=lambda item: item["percent"])
    totals = {"lines": sum(s["lines"] for s in stats),
              "covered": sum(s["covered"] for s in stats)}
    totals["percent"] = (totals["covered"] / totals["lines"] * 100.0) if totals["lines"] else 0.0
    return stats, totals


def emit_text(stats, totals):
    header = "{:<56} {:>8} {:>8} {:>10}".format("File", "Lines", "Covered", "Coverage%")
    print(header)
    print("-" * len(header))
    for item in stats:
        print("{:<56} {:>8} {:>8} {:>9.2f}%".format(
            item["file"][:56], item["lines"], item["covered"], item["percent"]))
    print("-" * len(header))
    print("{:<56} {:>8} {:>8} {:>9.2f}%".format(
        "TOTAL", totals["lines"], totals["covered"], totals["percent"]))


def emit_csv(output_dir, stats, totals):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "coverage.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "lines", "covered", "coverage_percent"])
        for item in stats:
            writer.writerow([item["file"], item["lines"], item["covered"],
                             round(item["percent"], 2)])
        writer.writerow(["TOTAL", totals["lines"], totals["covered"],
                         round(totals["percent"], 2)])
    print(f"CSV report written to {path}")


def emit_html(output_dir, stats, totals):
    html_dir = output_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    index_path = html_dir / "index.html"
    rows = []
    for item in stats:
        width = min(item["percent"], 100.0)
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{:.2f}%</td>"
            "<td><div class=\"bar\"><div class=\"fill\" style=\"width:{:.2f}%\"></div></div></td></tr>"
            .format(html.escape(item["file"]), item["lines"], item["covered"],
                    item["percent"], width))
    total_width = min(totals["percent"], 100.0)
    document = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Xenoide Coverage Report</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; color: #222; }}
h1 {{ font-size: 1.4rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ padding: 0.4rem 0.8rem; border-bottom: 1px solid #ddd; text-align: left; }}
th {{ background: #f4f4f4; }}
.bar {{ background: #eee; border-radius: 4px; width: 160px; }}
.fill {{ background: #3a7; height: 14px; border-radius: 4px; }}
tr.total td {{ font-weight: bold; background: #fafafa; }}
</style></head><body>
<h1>Xenoide Coverage Report</h1>
<p>TOTAL: {total_lines} lines, {total_covered} covered ({total_percent:.2f}%)</p>
<table><thead><tr><th>File</th><th>Lines</th><th>Covered</th><th>Coverage</th><th></th></tr></thead>
<tbody>{rows}
<tr class="total"><td>TOTAL</td><td>{total_lines}</td><td>{total_covered}</td>
<td>{total_percent:.2f}%</td><td><div class="bar"><div class="fill" style="width:{total_width:.2f}%"></div></div></td></tr>
</tbody></table></body></html>
""".format(rows="\n".join(rows), total_lines=totals["lines"],
           total_covered=totals["covered"], total_percent=totals["percent"],
           total_width=total_width)
    index_path.write_text(document, encoding="utf-8")
    print(f"HTML report written to {index_path}")


def emit_cobertura(output_dir, stats, totals):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "coverage.cobertura.xml"
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<coverage line-rate="{totals["percent"] / 100.0:.4f}" '
             f'lines-valid="{totals["lines"]}" lines-covered="{totals["covered"]}">',
             "  <packages><package name=\"xenoide\"><classes>"]
    for item in stats:
        lines.append(f'    <class name="{html.escape(item["file"])}" '
                     f'filename="{html.escape(item["file"])}" '
                     f'line-rate="{item["percent"] / 100.0:.4f}"/>')
    lines += ["  </classes></package></packages>", "</coverage>"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Cobertura report written to {path}")


def report(source_dir, tool, export, output_dir, json_files=None, gcov_dir=None,
           check=None):
    reporter = Reporter(source_dir)
    aggregate = (reporter.collect_llvm(json_files or []) if tool == "llvm-cov"
                 else reporter.collect_gcov(gcov_dir))
    if not aggregate:
        raise RuntimeError("no project sources found in the coverage data")

    stats, totals = build_stats(aggregate)
    output_dir = pathlib.Path(output_dir)
    if export == "text":
        emit_text(stats, totals)
    elif export == "csv":
        emit_csv(output_dir, stats, totals)
    else:
        emit_html(output_dir, stats, totals)
    emit_cobertura(output_dir, stats, totals)

    if check is not None:
        if totals["percent"] < check:
            raise RuntimeError(
                f"coverage check FAILED: {totals['percent']:.2f}% < required {check:.2f}%")
        print(f"Coverage check PASSED: {totals['percent']:.2f}% >= required {check:.2f}%")
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate and report code coverage")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--tool", required=True, choices=["llvm-cov", "gcov"])
    parser.add_argument("--export", default="text", choices=["text", "html", "csv"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--check", type=float, default=None)
    parser.add_argument("--gcov-dir", default=None)
    parser.add_argument("json_files", nargs="*")
    args = parser.parse_args(argv)
    try:
        report(args.source_dir, args.tool, args.export, args.output_dir,
               json_files=args.json_files, gcov_dir=args.gcov_dir, check=args.check)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

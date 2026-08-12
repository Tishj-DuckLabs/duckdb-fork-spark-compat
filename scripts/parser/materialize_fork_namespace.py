#!/usr/bin/env python3

import argparse
import os
import re
from pathlib import Path


FORK_NAMESPACE = "duckdb_fork"
HOST_NAMESPACE = "duckdb"

# TokenType is shared with the host parser and must retain its host namespace.
HOST_NAMESPACE_HEADERS = {Path("peg/token_type.hpp")}


def rewrite_outer_namespace(source, path):
    if f"namespace {FORK_NAMESPACE}" in source:
        raise ValueError(f"{path} already contains namespace {FORK_NAMESPACE}")

    opening_matches = list(re.finditer(rf"^namespace {HOST_NAMESPACE} \{{$", source, re.MULTILINE))
    if not opening_matches:
        raise ValueError(f"{path} has no outer namespace {HOST_NAMESPACE}")

    opening = opening_matches[-1]
    closing_matches = list(
        re.finditer(
            rf"^}} // namespace {HOST_NAMESPACE}$",
            source[opening.end() :],
            re.MULTILINE,
        )
    )
    if not closing_matches:
        raise ValueError(f"{path} has no closing namespace comment for {HOST_NAMESPACE}")

    closing = closing_matches[-1]
    closing_start = opening.end() + closing.start()
    closing_end = opening.end() + closing.end()
    fork_opening = f"namespace {FORK_NAMESPACE} {{\nusing namespace {HOST_NAMESPACE};"
    fork_closing = f"}} // namespace {FORK_NAMESPACE}"
    return (
        source[: opening.start()]
        + fork_opening
        + source[opening.end() : closing_start]
        + fork_closing
        + source[closing_end:]
    )


def write_if_different(path, contents, mode):
    if path.is_file() and path.read_bytes() == contents:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary_path.write_bytes(contents)
    os.chmod(temporary_path, mode)
    os.replace(temporary_path, path)
    return True


def add_file(files, source_path, destination_path, transform=False):
    contents = source_path.read_bytes()
    if transform:
        contents = rewrite_outer_namespace(contents.decode("utf-8"), source_path).encode("utf-8")
    files[destination_path] = (contents, source_path.stat().st_mode)


def collect_files(source_root, output_root):
    files = {}
    parser_include_root = source_root / "src" / "include" / "duckdb" / "parser"
    parser_source_root = source_root / "src" / "parser"

    if not parser_include_root.is_dir() or not parser_source_root.is_dir():
        raise ValueError(f"{source_root} is not a DuckDB source tree")

    parser_headers = [parser_include_root / "parser.hpp"]
    parser_headers.extend((parser_include_root / "peg").rglob("*.hpp"))
    for source_path in parser_headers:
        relative_path = source_path.relative_to(parser_include_root)
        transform = relative_path not in HOST_NAMESPACE_HEADERS
        add_file(
            files,
            source_path,
            output_root / "include" / "duckdb" / "parser" / relative_path,
            transform,
        )

    parser_cpp = parser_source_root / "parser.cpp"
    add_file(files, parser_cpp, output_root / "src" / "parser" / "parser.cpp", True)
    for source_path in (parser_source_root / "peg").rglob("*.cpp"):
        relative_path = source_path.relative_to(parser_source_root)
        add_file(files, source_path, output_root / "src" / "parser" / relative_path, True)

    return files


def remove_stale_files(output_root, expected_paths):
    if not output_root.exists():
        return 0

    removed = 0
    for path in output_root.rglob("*"):
        if path.is_file() and path not in expected_paths:
            path.unlink()
            removed += 1
    for path in sorted(output_root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return removed


def materialize(source_root, output_root):
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root == source_root or output_root in source_root.parents:
        raise ValueError("output directory cannot be the source tree or one of its parents")

    files = collect_files(source_root, output_root)
    changed = 0
    for path, (contents, mode) in files.items():
        changed += write_if_different(path, contents, mode)
    removed = remove_stale_files(output_root, set(files))
    return len(files), changed, removed


def main():
    parser = argparse.ArgumentParser(description="Materialize the DuckDB fork parser in namespace duckdb_fork")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()

    try:
        total, changed, removed = materialize(args.source_root, args.output_root)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(f"Materialized {total} parser files ({changed} updated, {removed} removed)")


if __name__ == "__main__":
    main()

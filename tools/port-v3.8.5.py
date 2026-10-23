#!/usr/bin/env python3
"""Create a reviewable three-way port from official v3.6.0 to v3.8.5.

The current admin fork and upstream repository do not share Git ancestry.
This helper therefore merges files using v3.6.0 as the common file baseline.
Non-overlapping text changes are combined; conflicting text hunks keep the
current admin-fork side and are written to PORTING_REPORT_v3.8.5.md for review.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_REF = "refs/tags/port-base-v3.6.0"
TARGET_REF = "refs/tags/port-target-v3.8.5"
MISSING = object()
DEPENDENCY_FILES = {"go.mod", "go.sum", ".nvmrc", "frontend/package-lock.json"}
REPO_URL_FILES = {
    "install.sh", "update.sh", "x-ui.sh", "install_offline.sh",
    "internal/web/service/panel/panel.go", "README.md", "README.fa_IR.md",
}
CUSTOM_REPO = "Azizpouryan/3x-ui-advanced"


def run(args: list[str], *, cwd: Path = ROOT, stdout: Any = None) -> None:
    subprocess.run(args, cwd=cwd, stdout=stdout, check=True)


def archive_ref(ref: str, destination: Path) -> None:
    archive_path = destination.parent / (destination.name + ".tar")
    with archive_path.open("wb") as handle:
        run(["git", "archive", ref], stdout=handle)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:") as archive:
        archive.extractall(destination, filter="data")
    archive_path.unlink(missing_ok=True)


def files_under(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            result[path.relative_to(root).as_posix()] = path
    return result


def read_payload(path: Path) -> bytes:
    if path.is_symlink():
        return b"\x00SYMLINK\x00" + os.readlink(path).encode("utf-8", "surrogateescape")
    return path.read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_path(source: Path, relative: str, destination_root: Path) -> None:
    destination = destination_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
    else:
        shutil.copy2(source, destination)


def write_bytes(relative: str, data: bytes, destination_root: Path, mode_source: Path | None = None) -> None:
    destination = destination_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.write_bytes(data)
    if mode_source is not None:
        try:
            destination.chmod(mode_source.stat().st_mode)
        except OSError:
            pass


def merge_json_value(base: Any, current: Any, target: Any) -> Any:
    if current == base:
        return copy.deepcopy(target)
    if target == base or current == target:
        return copy.deepcopy(current)
    if isinstance(base, dict) and isinstance(current, dict) and isinstance(target, dict):
        merged: dict[str, Any] = {}
        for key in sorted(set(base) | set(current) | set(target)):
            b = base.get(key, MISSING)
            c = current.get(key, MISSING)
            t = target.get(key, MISSING)
            if c is MISSING and t is MISSING:
                continue
            if b is MISSING:
                if c is MISSING:
                    merged[key] = copy.deepcopy(t)
                elif t is MISSING:
                    merged[key] = copy.deepcopy(c)
                else:
                    merged[key] = merge_json_value(MISSING, c, t)
                continue
            if c is MISSING:
                if t == b:
                    continue
                merged[key] = copy.deepcopy(t)
                continue
            if t is MISSING:
                if c == b:
                    continue
                merged[key] = copy.deepcopy(c)
                continue
            merged[key] = merge_json_value(b, c, t)
        return merged
    # On a conflicting primitive or list, prefer upstream's value for security
    # fixes and compatibility; dictionary keys above retain fork-only settings.
    return copy.deepcopy(target)


def merge_package_json(base: bytes, current: bytes, target: bytes) -> bytes:
    b = json.loads(base.decode("utf-8"))
    c = json.loads(current.decode("utf-8"))
    t = json.loads(target.decode("utf-8"))
    merged = merge_json_value(b, c, t)
    return (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def retain_current_conflict_hunks(data: bytes) -> tuple[bytes, int]:
    lines = data.splitlines(keepends=True)
    result: list[bytes] = []
    i = 0
    conflicts = 0
    while i < len(lines):
        if not lines[i].startswith(b"<<<<<<< current"):
            result.append(lines[i])
            i += 1
            continue
        conflicts += 1
        i += 1
        current_block: list[bytes] = []
        while i < len(lines) and not lines[i].startswith(b"======="):
            current_block.append(lines[i])
            i += 1
        if i >= len(lines):
            raise RuntimeError("Unclosed merge hunk: missing separator")
        i += 1
        while i < len(lines) and not lines[i].startswith(b">>>>>>> upstream"):
            i += 1
        if i >= len(lines):
            raise RuntimeError("Unclosed merge hunk: missing end marker")
        i += 1
        result.extend(current_block)
    return b"".join(result), conflicts


def merge_text(relative: str, current: bytes, base: bytes, target: bytes,
               temporary_root: Path) -> tuple[bytes, int]:
    with tempfile.TemporaryDirectory(prefix="merge3-", dir=temporary_root) as name:
        folder = Path(name)
        current_file = folder / "current"
        base_file = folder / "base"
        target_file = folder / "target"
        current_file.write_bytes(current)
        base_file.write_bytes(base)
        target_file.write_bytes(target)
        completed = subprocess.run(
            ["git", "merge-file", "-p", "-L", "current", "-L", "base", "-L", "upstream",
             str(current_file), str(base_file), str(target_file)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if completed.returncode not in (0, 1):
            detail = completed.stderr.decode("utf-8", "replace")
            raise RuntimeError("git merge-file failed for " + relative + ": " + detail)
        return retain_current_conflict_hunks(completed.stdout)


def redirect_fork_release_urls(output_root: Path) -> int:
    replacements = (
        ("https://api.github.com/repos/admin6501/3x-ui",
         "https://api.github.com/repos/" + CUSTOM_REPO),
        ("https://api.github.com/repos/MHSanaei/3x-ui",
         "https://api.github.com/repos/" + CUSTOM_REPO),
        ("https://github.com/admin6501/3x-ui/releases",
         "https://github.com/" + CUSTOM_REPO + "/releases"),
        ("https://github.com/MHSanaei/3x-ui/releases",
         "https://github.com/" + CUSTOM_REPO + "/releases"),
        ("https://raw.githubusercontent.com/admin6501/3x-ui/main/",
         "https://raw.githubusercontent.com/" + CUSTOM_REPO + "/main/"),
        ("https://raw.githubusercontent.com/MHSanaei/3x-ui/main/",
         "https://raw.githubusercontent.com/" + CUSTOM_REPO + "/main/"),
        ("https://github.com/admin6501/3x-ui/raw/main/",
         "https://raw.githubusercontent.com/" + CUSTOM_REPO + "/main/"),
        ("https://github.com/MHSanaei/3x-ui/raw/main/",
         "https://raw.githubusercontent.com/" + CUSTOM_REPO + "/main/"),
    )
    count = 0
    for relative in REPO_URL_FILES:
        path = output_root / relative
        if not path.is_file() or path.is_symlink():
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        revised = original
        for old, new in replacements:
            revised = revised.replace(old, new)
        if revised != original:
            path.write_text(revised, encoding="utf-8", newline="")
            count += 1
    return count


def main() -> None:
    for ref in (BASE_REF, TARGET_REF):
        run(["git", "rev-parse", "--verify", ref])

    temp_root = Path(tempfile.mkdtemp(prefix="port-v385-"))
    try:
        current_root = temp_root / "current"
        base_root = temp_root / "base"
        target_root = temp_root / "target"
        output_root = temp_root / "result"
        archive_ref("HEAD", current_root)
        archive_ref(BASE_REF, base_root)
        archive_ref(TARGET_REF, target_root)
        output_root.mkdir()

        current_files = files_under(current_root)
        base_files = files_under(base_root)
        target_files = files_under(target_root)
        all_paths = sorted(set(current_files) | set(base_files) | set(target_files))

        clean_merges = 0
        conflict_hunks = 0
        conflict_paths: list[str] = []
        merge_failures: list[str] = []
        current_selected = 0
        upstream_selected = 0
        custom_paths = 0
        deleted_paths = 0

        for relative in all_paths:
            current_path = current_files.get(relative)
            base_path = base_files.get(relative)
            target_path = target_files.get(relative)
            current = read_payload(current_path) if current_path else None
            base = read_payload(base_path) if base_path else None
            target = read_payload(target_path) if target_path else None

            # The GitHub Actions token used by this workflow is not allowed to
            # push changes to workflow files. Keep existing fork workflows byte-for-byte
            # and do not import newly-added upstream workflows in this automated commit.
            # This keeps the code migration pushable; workflow updates can be reviewed
            # and applied separately by a repository maintainer.
            if relative.startswith(".github/workflows/"):
                if current_path is not None:
                    copy_path(current_path, relative, output_root)
                    current_selected += 1
                else:
                    deleted_paths += 1
                continue

            if relative in DEPENDENCY_FILES and target_path is not None:
                copy_path(target_path, relative, output_root)
                upstream_selected += 1
                continue

            if base_path is None:
                # Preserve fork-only features; add upstream-only files.
                if current_path is not None:
                    copy_path(current_path, relative, output_root)
                    custom_paths += 1
                elif target_path is not None:
                    copy_path(target_path, relative, output_root)
                    upstream_selected += 1
                continue

            if current_path is None and target_path is None:
                deleted_paths += 1
                continue
            if current_path is None:
                if target == base:
                    deleted_paths += 1
                else:
                    copy_path(target_path, relative, output_root)
                    upstream_selected += 1
                continue
            if target_path is None:
                if current == base:
                    deleted_paths += 1
                else:
                    copy_path(current_path, relative, output_root)
                    current_selected += 1
                continue

            if relative == "frontend/package.json":
                try:
                    merged_json = merge_package_json(base, current, target)
                    write_bytes(relative, merged_json, output_root, current_path)
                    clean_merges += 1
                    continue
                except (ValueError, UnicodeDecodeError, TypeError):
                    pass

            if current == base:
                copy_path(target_path, relative, output_root)
                upstream_selected += 1
                continue
            if target == base or current == target:
                copy_path(current_path, relative, output_root)
                current_selected += 1
                continue

            if current_path.is_symlink() or base_path.is_symlink() or target_path.is_symlink() or \
                    b"\x00" in current or b"\x00" in base or b"\x00" in target:
                # Binary conflicts prefer upstream; fork-only binary assets are preserved above.
                copy_path(target_path, relative, output_root)
                upstream_selected += 1
                continue

            try:
                merged, conflicts = merge_text(relative, current, base, target, temp_root)
            except RuntimeError as error:
                # Some workflow/config files can make git's external merge helper fail
                # without a useful diagnostic. Fall back explicitly and report the file
                # instead of aborting the complete migration.
                merge_failures.append(relative + ": " + str(error))
                conflict_paths.append(relative)
                if relative == ".github/workflows/release.yml":
                    # The v3.8.5 release workflow is required to build the migrated
                    # binary and publish architecture assets from this fork.
                    copy_path(target_path, relative, output_root)
                    upstream_selected += 1
                else:
                    # Prefer the current side for other files to avoid losing RBAC.
                    copy_path(current_path, relative, output_root)
                    current_selected += 1
                continue

            write_bytes(relative, merged, output_root, current_path)
            if conflicts:
                conflict_hunks += conflicts
                conflict_paths.append(relative)
            else:
                clean_merges += 1

        rewritten = redirect_fork_release_urls(output_root)

        readme = output_root / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            text = text.replace(
                "# 3X-UI — RBAC Fork (admin6501)",
                "# 3X-UI Advanced — v3.8.5 admin fork",
            )
            readme.write_text(text, encoding="utf-8", newline="")

        report = [
            "3X-UI v3.8.5 Port Report",
            "=========================",
            "",
            "Upstream target: MHSanaei/3x-ui tag v3.8.5.",
            "Three-way file baseline: MHSanaei/3x-ui tag v3.6.0.",
            "Conflict policy: auto-merge non-overlapping changes; conflicting text hunks keep the current admin fork and are listed for manual review.",
            "GitHub Actions workflow files are deliberately preserved from the current branch because this workflow's token cannot push edits to .github/workflows; review workflow changes separately.",
            "",
            "Merge statistics",
            "----------------",
            "Base files: " + str(len(base_files)),
            "Current fork files: " + str(len(current_files)),
            "Upstream files: " + str(len(target_files)),
            "Clean merges: " + str(clean_merges),
            "Conflict hunks resolved toward the admin fork: " + str(conflict_hunks),
            "Files containing conflict hunks or merge fallbacks: " + str(len(set(conflict_paths))),
            "Files where git merge-file failed and a side was selected: " + str(len(merge_failures)),
            "Current-side files selected: " + str(current_selected),
            "Upstream-side files selected: " + str(upstream_selected),
            "Fork-only paths preserved: " + str(custom_paths),
            "Paths removed by three-way deletion rules: " + str(deleted_paths),
            "Files with fork release URLs redirected: " + str(rewritten),
            "",
            "Files needing manual review",
            "---------------------------",
        ]
        if conflict_paths:
            report.extend("- " + path for path in sorted(set(conflict_paths)))
        else:
            report.append("No conflicting text hunks were detected.")
        if merge_failures:
            report += ["", "Merge helper errors and selected fallbacks", "------------------------------------------"]
            report.extend("- " + item for item in merge_failures)
        report += [
            "",
            "This is a migration candidate, not a guarantee that every bug is fixed. Run the Go tests, frontend build, and installer shell checks before deploying it. Review RBAC and database migrations especially carefully.",
            "",
        ]
        (output_root / "PORTING_REPORT_v3.8.5.md").write_text(
            "\n".join(report), encoding="utf-8", newline=""
        )

        # Replace the checkout contents but never touch the Git metadata.
        for child in ROOT.iterdir():
            if child.name == ".git":
                continue
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
        for child in output_root.iterdir():
            destination = ROOT / child.name
            if child.is_symlink():
                os.symlink(os.readlink(child), destination)
            elif child.is_dir():
                shutil.copytree(child, destination, symlinks=True)
            else:
                shutil.copy2(child, destination)

        print("Created a three-way v3.8.5 migration candidate.")
        print("Clean merges: " + str(clean_merges))
        print("Conflict hunks resolved toward the admin fork: " + str(conflict_hunks))
        print("Review PORTING_REPORT_v3.8.5.md before production use.")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()

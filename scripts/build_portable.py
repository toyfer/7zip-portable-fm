#!/usr/bin/env python3
"""Build a no-registry portable 7-Zip package from official installers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = "7zip-portable-fm/1.0 (+https://github.com/toyfer/7zip-portable-fm)"
GITHUB_API = "https://api.github.com/repos/ip7z/7zip/releases/latest"
GITHUB_RELEASE = "https://github.com/ip7z/7zip/releases/download/{tag}/{name}"
SEVENZIP_ORG_A = "https://www.7-zip.org/a/{name}"

# Portable runtime only — no shell extension, no uninstaller.
KEEP_FILES = {
    "7zFM.exe",
    "7zG.exe",
    "7z.exe",
    "7z.dll",
    "7z.sfx",
    "7zCon.sfx",
    "7-zip.chm",
    "License.txt",
    "History.txt",
    "readme.txt",
    "descript.ion",
}

EXCLUDE_NAMES = {
    "uninstall.exe",
    "7-zip.dll",
    "7-zip32.dll",
}

CMD_HEADER = r"""@echo off
setlocal
set "DIR=%~dp0"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
  set "BIN=%DIR%arm64"
) else if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" (
  set "BIN=%DIR%arm64"
) else if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
  set "BIN=%DIR%x64"
) else if /i "%PROCESSOR_ARCHITECTURE%"=="x86" (
  if defined PROCESSOR_ARCHITEW6432 (
    set "BIN=%DIR%x64"
  ) else (
    set "BIN=%DIR%x86"
  )
) else (
  set "BIN=%DIR%x64"
)
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def http_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"DL {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"download failed {url}: {e}") from e
    dest.write_bytes(data)
    log(f"  -> {dest.name} ({len(data)} bytes)")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_version(version: str) -> tuple[str, str, str]:
    """Return (dotted, compact, upstream_tag). Example: 26.02 -> 2602."""
    v = version.strip().lstrip("vV")
    if re.fullmatch(r"\d+\.\d+", v):
        major, minor = v.split(".")
        compact = f"{major}{minor}"
        return f"{major}.{minor}", compact, f"{major}.{minor}"
    if re.fullmatch(r"\d{4}", v):
        dotted = f"{v[:2]}.{v[2:]}"
        return dotted, v, dotted
    if re.fullmatch(r"\d{3}", v):
        dotted = f"{v[0]}.{v[1:]}"
        return dotted, v, dotted
    raise ValueError(f"unrecognized version: {version!r}")


def resolve_latest_version() -> tuple[str, str, str, list[dict]]:
    data = http_json(GITHUB_API)
    tag = data.get("tag_name") or ""
    dotted, compact, rel_tag = normalize_version(tag)
    assets = data.get("assets") or []
    return dotted, compact, rel_tag, assets


def asset_url(assets: list[dict], name: str, tag: str) -> str:
    for a in assets:
        if a.get("name") == name and a.get("browser_download_url"):
            return a["browser_download_url"]
    return GITHUB_RELEASE.format(tag=tag, name=name)


def find_7zz(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(explicit)
        return p
    for cand in ("7zz", "7zzs", "7z"):
        path = shutil.which(cand)
        if path:
            return Path(path)
    raise FileNotFoundError("7zz/7z not found on PATH; pass --sevenzz")


def ensure_linux_7zz(work: Path) -> Path:
    """Download official linux 7zz if nothing on PATH."""
    try:
        return find_7zz(None)
    except FileNotFoundError:
        pass

    candidates: list[str] = []
    try:
        data = http_json(GITHUB_API)
        tag = data.get("tag_name", "")
        for a in data.get("assets") or []:
            n = a.get("name") or ""
            if "linux-x64" in n and n.endswith((".tar.xz", ".tar.gz")):
                candidates.append(a["browser_download_url"])
        _, compact, _ = normalize_version(tag)
        candidates.append(SEVENZIP_ORG_A.format(name=f"7z{compact}-linux-x64.tar.xz"))
    except Exception as e:
        log(f"warn: latest probe failed: {e}")

    for name in (
        "7z2602-linux-x64.tar.xz",
        "7z2601-linux-x64.tar.xz",
        "7z2501-linux-x64.tar.xz",
    ):
        candidates.append(SEVENZIP_ORG_A.format(name=name))

    tar_path = work / "7z-linux.tar.xz"
    last_err: Exception | None = None
    for url in candidates:
        try:
            download(url, tar_path)
            break
        except Exception as e:
            last_err = e
            log(f"  skip: {e}")
    else:
        raise RuntimeError(f"could not download linux 7zz: {last_err}")

    subprocess.check_call(["tar", "xf", str(tar_path), "-C", str(work)])
    for p in work.rglob("7zz"):
        p.chmod(0o755)
        return p
    for p in work.rglob("7zzs"):
        p.chmod(0o755)
        return p
    raise RuntimeError("7zz not found inside linux archive")


def extract_archive(sevenzz: Path, archive: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(sevenzz), "x", "-y", f"-o{out_dir}", str(archive)]
    log("RUN " + " ".join(cmd))
    subprocess.check_call(cmd)


def copy_portable_arch(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in KEEP_FILES:
        s = src / name
        if s.is_file():
            shutil.copy2(s, dest / name)
        else:
            log(f"  warn missing {src.name}/{name}")
    lang = src / "Lang"
    if lang.is_dir():
        shutil.copytree(lang, dest / "Lang", dirs_exist_ok=True)
    for p in list(dest.iterdir()):
        if p.name.lower() in EXCLUDE_NAMES or p.suffix.lower() == ".reg":
            p.unlink()
            log(f"  removed excluded {p.name}")
    if (dest / "7zFM.exe").is_file():
        shutil.copy2(dest / "7zFM.exe", dest / "7-Zip.exe")
    n = sum(1 for x in dest.rglob("*") if x.is_file())
    size = sum(x.stat().st_size for x in dest.rglob("*") if x.is_file())
    log(f"{dest.name}: {n} files, {size / 1024 / 1024:.2f} MB")


def write_cmd(path: Path, exe_name: str, use_start: bool) -> None:
    lines = [CMD_HEADER.rstrip("\n")]
    lines.append(f'if not exist "%BIN%\\{exe_name}" (')
    lines.append(f'  echo {exe_name} not found in "%BIN%"')
    lines.append("  exit /b 1")
    lines.append(")")
    if use_start:
        lines.append(f'start "" "%BIN%\\{exe_name}" %*')
    else:
        lines.append(f'"%BIN%\\{exe_name}" %*')
    lines.append("")
    path.write_text("\r\n".join(lines), encoding="utf-8", newline="")


def write_readme(path: Path, dotted: str, compact: str, hashes: dict[str, str]) -> None:
    lines_h = "\n".join(f"  {k}:\n  {v}" for k, v in hashes.items())
    text = f"""7-Zip Portable {dotted} (no install / no registry)
===================================================
Built   : {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
Source  : Official installers (ip7z/7zip + 7-zip.org)
          7z{compact}-x64.exe / 7z{compact}-arm64.exe / 7z{compact}.exe
          + 7z{compact}-extra.7z (standalone 7za)

Official 7-Zip files only. NO registry, NO shell context menu, NO Uninstall.exe.

Usage
-----
1. Extract this ZIP anywhere (USB OK)
2. Double-click 7-Zip.cmd  -> File Manager
   or run x64\\7zFM.exe / arm64\\7zFM.exe / x86\\7zFM.exe
3. In File Manager: Add (compress), Extract, Test
4. CLI:  7z.cmd a archive.7z folder\\
         7z.cmd x archive.7z -oout\\

Layout
------
  7-Zip.cmd / 7z.cmd / 7zG.cmd
  x64/ arm64/ x86/
    7zFM.exe  7zG.exe  7z.exe  7z.dll  7z.sfx  7zCon.sfx  Lang/
  standalone-7za/   (optional lightweight 7za from official extra)

Excluded on purpose
-------------------
  Uninstall.exe, 7-zip.dll, 7-zip32.dll, any .reg

Copyright
---------
  7-Zip (c) Igor Pavlov — see License.txt
  https://www.7-zip.org/

Upstream installer SHA-256
--------------------------
{lines_h}
"""
    path.write_text(text.replace("\n", "\r\n"), encoding="utf-8", newline="")


def pack_standalone(extra: Path, dest_root: Path) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    x86_names = ["7za.exe", "7za.dll", "7zxa.dll"]
    if any((extra / n).is_file() for n in x86_names):
        d = dest_root / "x86"
        d.mkdir(exist_ok=True)
        for n in x86_names:
            if (extra / n).is_file():
                shutil.copy2(extra / n, d / n)
    for arch in ("x64", "arm64"):
        src = extra / arch
        if not src.is_dir():
            continue
        d = dest_root / arch
        d.mkdir(exist_ok=True)
        for n in x86_names:
            if (src / n).is_file():
                shutil.copy2(src / n, d / n)
    for n in ("License.txt", "readme.txt", "history.txt"):
        if (extra / n).is_file():
            shutil.copy2(extra / n, dest_root / n)


def build(
    version: str | None,
    out_dir: Path,
    sevenzz: str | None,
    work: Path | None,
) -> Path:
    work_ctx = tempfile.TemporaryDirectory(prefix="7zport-") if work is None else None
    work_path = Path(work) if work else Path(work_ctx.name)  # type: ignore[union-attr]
    work_path.mkdir(parents=True, exist_ok=True)

    try:
        assets: list[dict] = []
        if version:
            dotted, compact, rel_tag = normalize_version(version)
            try:
                data = http_json(GITHUB_API)
                if normalize_version(data.get("tag_name", ""))[0] == dotted:
                    assets = data.get("assets") or []
            except Exception:
                assets = []
            # Also try the specific release endpoint for assets
            if not assets:
                try:
                    data = http_json(
                        f"https://api.github.com/repos/ip7z/7zip/releases/tags/{rel_tag}"
                    )
                    assets = data.get("assets") or []
                except Exception:
                    pass
        else:
            dotted, compact, rel_tag, assets = resolve_latest_version()

        log(f"Version: {dotted} (compact={compact}, tag={rel_tag})")

        up_tag = rel_tag
        names = {
            "x64": f"7z{compact}-x64.exe",
            "arm64": f"7z{compact}-arm64.exe",
            "x86": f"7z{compact}.exe",
            "extra": f"7z{compact}-extra.7z",
        }

        dl_dir = work_path / "dl"
        ex_dir = work_path / "extract"
        hashes: dict[str, str] = {}

        for name in names.values():
            url = asset_url(assets, name, up_tag)
            dest = dl_dir / name
            try:
                download(url, dest)
            except Exception:
                download(SEVENZIP_ORG_A.format(name=name), dest)
            hashes[name] = sha256_file(dest)

        if sevenzz:
            zz = find_7zz(sevenzz)
        else:
            zz = ensure_linux_7zz(work_path / "linux7z")

        extract_archive(zz, dl_dir / names["x64"], ex_dir / "x64")
        extract_archive(zz, dl_dir / names["arm64"], ex_dir / "arm64")
        extract_archive(zz, dl_dir / names["x86"], ex_dir / "x86")
        extract_archive(zz, dl_dir / names["extra"], ex_dir / "extra")

        root = work_path / f"7-Zip-Portable-{dotted}"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()

        for arch in ("x64", "arm64", "x86"):
            copy_portable_arch(ex_dir / arch, root / arch)

        pack_standalone(ex_dir / "extra", root / "standalone-7za")

        write_cmd(root / "7-Zip.cmd", "7zFM.exe", use_start=True)
        write_cmd(root / "7z.cmd", "7z.exe", use_start=False)
        write_cmd(root / "7zG.cmd", "7zG.exe", use_start=False)
        write_readme(root / "README-PORTABLE.txt", dotted, compact, hashes)

        sum_lines = []
        for p in sorted(root.rglob("*")):
            if p.is_file():
                sum_lines.append(f"{sha256_file(p)}  {p.relative_to(root).as_posix()}")
        (root / "SHA256SUMS.txt").write_text(
            "\r\n".join(sum_lines) + "\r\n", encoding="utf-8", newline=""
        )

        for arch in ("x64", "arm64", "x86"):
            for req in ("7zFM.exe", "7z.exe", "7z.dll", "7zG.exe"):
                if not (root / arch / req).is_file():
                    raise RuntimeError(f"missing {arch}/{req}")
            for bad in EXCLUDE_NAMES:
                if (root / arch / bad).exists():
                    raise RuntimeError(f"excluded file present: {arch}/{bad}")

        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"7-Zip-Portable-{dotted}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    arc = Path(root.name) / p.relative_to(root)
                    zf.write(p, arcname=arc.as_posix())

        zip_hash = sha256_file(zip_path)
        (out_dir / f"7-Zip-Portable-{dotted}.zip.sha256").write_text(
            f"{zip_hash}  {zip_path.name}\n", encoding="utf-8"
        )
        meta = {
            "version": dotted,
            "compact": compact,
            "tag": f"v{dotted}",
            "upstream_tag": up_tag,
            "zip": zip_path.name,
            "zip_sha256": zip_hash,
            "upstream_sha256": hashes,
            "built_at": datetime.now(timezone.utc).isoformat(),
        }
        (out_dir / "build-meta.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        log(f"OK {zip_path} ({zip_path.stat().st_size} bytes)")
        log(f"SHA256 {zip_hash}")
        return zip_path
    finally:
        if work_ctx is not None:
            work_ctx.cleanup()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--version",
        default=os.environ.get("SEVENZIP_VERSION") or None,
        help="7-Zip version e.g. 26.02 (default: latest upstream)",
    )
    ap.add_argument("--out-dir", type=Path, default=Path("dist"))
    ap.add_argument(
        "--sevenzz",
        default=os.environ.get("SEVENZZ") or None,
        help="Path to 7zz binary",
    )
    ap.add_argument("--work-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    build(args.version, args.out_dir, args.sevenzz, args.work_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

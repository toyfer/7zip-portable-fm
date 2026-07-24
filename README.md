# 7-Zip Portable (File Manager)

Official [7-Zip](https://www.7-zip.org/) installers, unpacked into a **portable folder** with:

- **File Manager** (`7zFM.exe`)
- Compress / extract GUI (`7zG.exe`)
- CLI (`7z.exe` + `7z.dll`)

**No registry edits. No shell context menu. No uninstaller.**

When [ip7z/7zip](https://github.com/ip7z/7zip) publishes a new release, GitHub Actions rebuilds this portable package and publishes it under [Releases](../../releases).

> This is **not** a source fork of 7-Zip. It only repackages Igor Pavlov’s official Windows binaries. All credit and copyright for 7-Zip belong to the upstream project.

## Download

- Latest build: [Releases](https://github.com/toyfer/7zip-portable-fm/releases/latest)
- Asset name: `7-Zip-Portable-<version>.zip`

## Usage

1. Extract the ZIP anywhere (USB drive is fine).
2. Double-click **`7-Zip.cmd`** → opens File Manager.
   - Or run `x64\7zFM.exe` / `arm64\7zFM.exe` / `x86\7zFM.exe`.
3. Inside File Manager: **Add** (compress), **Extract**, **Test**, browse archives.
4. CLI examples:

```bat
7z.cmd a archive.7z C:\data\
7z.cmd x archive.7z -oC:\out\
```

### Layout

```
7-Zip-Portable-XX.XX/
  7-Zip.cmd          # launch File Manager (auto-picks arch)
  7z.cmd             # CLI
  7zG.cmd            # GUI helper
  x64/ arm64/ x86/
    7zFM.exe  7zG.exe  7z.exe  7z.dll  7z.sfx  7zCon.sfx  Lang/
  standalone-7za/    # optional lightweight 7za from official extra package
  README-PORTABLE.txt
  SHA256SUMS.txt
```

### Intentionally excluded

| File | Why |
|------|-----|
| `Uninstall.exe` | Not needed for portable use |
| `7-zip.dll` / `7-zip32.dll` | Explorer shell extension / context menu |
| Any `.reg` | No registry integration |

## How builds work

Workflow: [`.github/workflows/build.yml`](.github/workflows/build.yml)

| Trigger | Behavior |
|---------|----------|
| **Schedule** (daily) | Check latest upstream tag; build + release if new |
| **workflow_dispatch** | Manual run (optional version override) |
| **repository_dispatch** | External hook |
| **push** to `main` (script/workflow changes) | Rebuild current latest upstream |

Steps:

1. Resolve version from [ip7z/7zip releases](https://github.com/ip7z/7zip/releases) (or input).
2. Download official `7zNNNN-x64.exe`, `-arm64.exe`, `.exe` (x86), and `-extra.7z`.
3. Download Linux `7zz` from 7-zip.org to extract the Windows installers.
4. Pack portable tree via [`scripts/build_portable.py`](scripts/build_portable.py).
5. Create GitHub Release `v<version>` with the ZIP + checksums (skips if tag already exists, unless force).

### Run manually

Repo → **Actions** → **Build portable 7-Zip** → **Run workflow**

Optional inputs:

- `version` — e.g. `26.02` (empty = latest upstream)
- `force` — rebuild even if release already exists

### Local build

```bash
# needs curl, python3, and a 7zz binary on PATH (or pass --sevenzz)
python3 scripts/build_portable.py --version 26.02 --out-dir dist
```

## License

- **7-Zip binaries**: [GNU LGPL](https://www.7-zip.org/license.txt) (and other notices in upstream `License.txt`). Redistributed unchanged from official installers.
- **Packaging scripts / workflow in this repo**: [MIT](LICENSE)

Official site: <https://www.7-zip.org/>

## Disclaimer

Unofficial packaging only. Not affiliated with Igor Pavlov or 7-Zip.org. For the supported install experience, use the official installer from the upstream site.

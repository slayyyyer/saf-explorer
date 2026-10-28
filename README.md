# SAF Explorer

A small desktop tool for MX Simulator `.saf` archives: open one to see what is
inside and extract files, or pack a folder back into a `.saf`. Pure Python
standard library — no installs, no dependencies.

## Run it

Double-click **`saf_tool.pyw`**.

Or from a terminal:

```
py safgui.py
py safgui.py "C:\Users\justin\AppData\Local\MX Simulator\2025WinterCupOBJ.saf"
```

## Extract tab

* **Open .saf…** (or `Ctrl+O`) parses the header only, so a 900 MB archive opens
  instantly.
* The list shows every file with its size and type; the filter box narrows it
  as you type. `Ctrl+A` selects all.
* **Extract all** / **Extract selected** write the files under the folder in
  *Extract to*. The default destination is a folder named after the archive, next
  to it.
* Existing files are kept unless *Overwrite existing files* is ticked.
* Archive paths are sanitized, so `..`, absolute paths and drive letters can
  never escape the destination folder.
* Long operations run on a background thread with a progress bar and a
  **Cancel** button.

## Create tab

* **Choose folder…** scans a folder recursively. *Root name* (default: the
  folder name) becomes the first path component inside the archive, exactly the
  way retail archives are laid out (`mytrack/models/post.jm`).
* Uncheck *Store files inside the root folder* to put files at the archive root.
* Select rows and use **Exclude selected** to leave files out.
* **Build .saf** writes to a temporary file first and only replaces the target
  when every byte was copied, so an interrupted build never leaves a broken
  archive.

## The file format

A `.saf` is a plain, uncompressed container — header first, then raw bytes:

```
18216 mphOBJ2025/gates.jm\n
899712 mphOBJ2025/gatesbg.png\n
902443 mphOBJ2025/gatesmph.png\n
...
30003 mphOBJ2025/models/warning/warning_spec.png\n
-\n
<899712 bytes of PNG>
<902443 bytes of PNG>
...
```

* One line per file: decimal byte count, one space, archive-relative path,
  newline. Paths always use `/` and may contain spaces.
* The header ends with a line containing only `-`.
* File data follows immediately, concatenated in header order, each block
  exactly the declared size.
* No compression, no timestamps, no checksums. A file's offset is the sum of
  the sizes listed above it, so the archive is fully seekable.

This was verified against 424 `.saf` files in a retail MX Simulator folder:
every one uses the `-` terminator, and header length plus the sum of the sizes
equals the file size exactly. Extracting a 89 MB retail archive and repacking it
reproduces the original file **byte for byte** (covered by a test).

Notes picked up from retail archives:

* Some `.png` entries are not images at all but tiny `LINK @texture` stubs that
  point at another texture. They are extracted verbatim.
* Zero-byte entries occur (`0 some/file.txt`) and round-trip fine.
* Paths are ASCII in practice (`A-Z a-z 0-9 space # & ( ) - . / [ ] _`).

## Packaging a standalone .exe

`dist\SAF Explorer.exe` (~11.5 MB, single file, no Python needed) is built with
PyInstaller from a local virtualenv:

```
py -m venv .venv
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller "SAF Explorer.spec"
```

The checked-in `SAF Explorer.spec` holds the build settings (`--onefile`,
`--windowed`, current folder on the module path) so rebuilds use one command.
Equivalent from scratch:

```
.venv\Scripts\python -m PyInstaller --onefile --windowed --paths . --name "SAF Explorer" saf_tool.pyw
```

Drop a `.saf` onto the exe, or pass it on the command line, to open that
archive directly. The exe is unsigned, so Windows SmartScreen will warn on
first launch elsewhere (*More info* → *Run anyway*). Use `--onedir` instead of
`--onefile` for faster startup and fewer antivirus false positives.

## Layout

| File | Purpose |
| --- | --- |
| `safcore.py` | Format reader/writer + extraction. No GUI imports. |
| `safgui.py` | Tkinter interface, theming, background workers. |
| `saf_tool.pyw` | Double-click launcher (no console window). |
| `tests/test_saf.py` | Format, safety and round-trip tests. |
| `tests/test_gui_smoke.py` | Drives the real UI: open, filter, extract, build, exclude. |
| `SAF Explorer.spec` | PyInstaller build recipe. |
| `dist/SAF Explorer.exe` | Built standalone app. |

## Tests

```
py -m unittest discover -s tests -v
```

The round-trip test uses `2025WinterCupOBJ.saf` from
`%LOCALAPPDATA%\MX Simulator` when it is present and is skipped otherwise. Point
`MXS_SAF_TEST_FILE` at another archive to test a different one.

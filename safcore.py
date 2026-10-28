"""Reader/writer for MX Simulator ``.saf`` archives.

File layout (verified against 424 retail archives):

    <size> <path>\\n          for every file, in archive order
    <size> <path>\\n
    -\\n                       terminator line, always present
    <raw bytes>               concatenated file data, in the same order as
                              the header, each block exactly <size> bytes

* ``size`` is the decimal byte count, followed by a single space.
* ``path`` is relative and always uses forward slashes, e.g.
  ``mphOBJ2025/models/warning/warning.jm``. It may contain spaces.
* Nothing else is stored: no compression, no timestamps, no checksums.
  The header size is implied by the terminator; a file's offset is the sum
  of the sizes of the files listed above it.

This module has no third-party dependencies.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field

CHUNK = 1024 * 1024
TERMINATOR = b"-\n"

_RESERVED_WINDOWS_NAMES = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE
)
_ILLEGAL_WINDOWS_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


class SafError(Exception):
    """Raised when a file is not a valid .saf archive."""


@dataclass(frozen=True)
class SafEntry:
    """One file inside an archive."""

    name: str  # archive-relative path, '/'-separated
    size: int
    offset: int  # absolute byte offset of the file data

    @property
    def extension(self) -> str:
        ext = os.path.splitext(self.name)[1]
        return ext.lower() if ext else ""


@dataclass
class SafArchive:
    """Parsed header of a .saf archive."""

    path: str
    entries: list[SafEntry]
    header_size: int
    data_offset: int
    file_size: int
    terminator: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.entries)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def stem(self) -> str:
        return os.path.splitext(self.name)[0]


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def _decode_name(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def _encode_name(name: str) -> bytes:
    return name.encode("utf-8", "surrogateescape")


def read(path: str) -> SafArchive:
    """Parse the header of ``path`` without loading the file data."""

    file_size = os.path.getsize(path)
    entries: list[SafEntry] = []
    warnings: list[str] = []
    terminator = False

    with open(path, "rb") as handle:
        data_offset = 0
        while True:
            line = handle.readline()
            if not line:
                raise SafError(
                    "not an MX Simulator .saf archive (header has no terminator)"
                )
            if not line.endswith(b"\n"):
                raise SafError("not an MX Simulator .saf archive (truncated header)")

            body = line[:-1]
            if body.endswith(b"\r"):
                body = body[:-1]

            if body == b"-":
                terminator = True
                data_offset = handle.tell()
                break

            space = body.find(b" ")
            if space <= 0:
                raise SafError(
                    "not an MX Simulator .saf archive "
                    "(unexpected header line: %r)" % body[:80]
                )
            count, name = body[:space], body[space + 1 :]
            if not count.isdigit() or not name:
                raise SafError(
                    "not an MX Simulator .saf archive "
                    "(unexpected header line: %r)" % body[:80]
                )
            entries.append(
                SafEntry(name=_decode_name(name), size=int(count), offset=0)
            )

    if not entries:
        warnings.append("archive contains no files")

    # Fill in data offsets now that the header length is known.
    offset = data_offset
    resolved: list[SafEntry] = []
    for entry in entries:
        resolved.append(SafEntry(name=entry.name, size=entry.size, offset=offset))
        offset += entry.size

    expected = data_offset + sum(entry.size for entry in entries)
    if expected != file_size:
        warnings.append(
            "header lists %d bytes of data but the file holds %d "
            "(archive may be truncated or have trailing data)"
            % (offset - data_offset, file_size - data_offset)
        )

    return SafArchive(
        path=os.path.abspath(path),
        entries=resolved,
        header_size=data_offset,
        data_offset=data_offset,
        file_size=file_size,
        terminator=terminator,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# extracting
# --------------------------------------------------------------------------


def sanitize_name(name: str) -> str:
    """Turn an archive path into a safe relative filesystem path.

    Rejects absolute paths, drive letters and ``..`` components so a hostile
    archive cannot write outside the destination folder.
    """

    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise SafError("absolute paths are not allowed")
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise SafError("'..' path components are not allowed")
        if ":" in part:
            raise SafError("drive letters are not allowed")
        cleaned = _ILLEGAL_WINDOWS_CHARS.sub("_", part).rstrip(" .")
        if not cleaned:
            raise SafError("unsafe file name")
        if _RESERVED_WINDOWS_NAMES.match(cleaned):
            cleaned = "_" + cleaned
        parts.append(cleaned)
    if not parts:
        raise SafError("empty file name")
    return os.path.join(*parts)


@dataclass
class ExtractResult:
    dest: str
    written: int = 0
    skipped: int = 0
    cancelled: bool = False
    entries: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


def extract(
    archive: SafArchive,
    dest: str,
    entries: list[SafEntry] | None = None,
    overwrite: bool = True,
    progress=None,
    cancel=None,
) -> ExtractResult:
    """Write the selected entries of ``archive`` below ``dest``.

    ``progress`` is called as ``progress(done_bytes, total_bytes, name)`` and
    ``cancel`` as ``cancel()`` returning True to stop early.
    """

    selected = list(archive.entries if entries is None else entries)
    os.makedirs(dest, exist_ok=True)
    result = ExtractResult(dest=os.path.abspath(dest))
    total = sum(entry.size for entry in selected)
    done = 0
    used: set[str] = set()
    next_report = CHUNK

    with open(archive.path, "rb") as source:
        for entry in selected:
            if cancel is not None and cancel():
                result.cancelled = True
                break
            if progress is not None:
                progress(done, total, entry.name)
            try:
                target = os.path.join(dest, sanitize_name(entry.name))
            except SafError as exc:
                result.errors.append((entry.name, str(exc)))
                done += entry.size
                continue

            key = os.path.normcase(os.path.abspath(target))
            if key in used:
                unique = _unique_path(target, used)
                result.errors.append(
                    (entry.name, "duplicate name, written as %s" % os.path.basename(unique))
                )
                target = unique
                key = os.path.normcase(os.path.abspath(target))
            used.add(key)

            if not overwrite and os.path.exists(target):
                result.skipped += 1
                done += entry.size
                continue

            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            source.seek(entry.offset)
            remaining = entry.size
            try:
                with open(target, "wb") as out:
                    while remaining > 0:
                        if cancel is not None and cancel():
                            raise _Cancelled
                        block = source.read(min(CHUNK, remaining))
                        if not block:
                            raise SafError("unexpected end of archive data")
                        out.write(block)
                        remaining -= len(block)
                        done += len(block)
                        if progress is not None and done >= next_report:
                            next_report = done + CHUNK
                            progress(done, total, entry.name)
            except _Cancelled:
                result.cancelled = True
                break
            except OSError as exc:
                result.errors.append((entry.name, str(exc)))
                done += remaining
                continue
            result.written += 1
            result.entries.append(entry.name)

    if progress is not None:
        progress(total if not result.cancelled else done, total, "")
    return result


class _Cancelled(Exception):
    pass


def _unique_path(path: str, used: set[str]) -> str:
    stem, ext = os.path.splitext(path)
    index = 2
    while True:
        candidate = "%s (%d)%s" % (stem, index, ext)
        if os.path.normcase(os.path.abspath(candidate)) not in used:
            return candidate
        index += 1


# --------------------------------------------------------------------------
# creating
# --------------------------------------------------------------------------


@dataclass
class BuildResult:
    path: str
    count: int = 0
    total_bytes: int = 0
    cancelled: bool = False
    errors: list[tuple[str, str]] = field(default_factory=list)


def collect_files(folder: str, root_name: str | None = None) -> list[tuple[str, str]]:
    """List ``(archive name, absolute path)`` pairs for every file in ``folder``.

    ``root_name`` becomes the first path component inside the archive; pass
    None to store the files at the archive root.
    """

    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise SafError("not a folder: %s" % folder)
    prefix = (root_name or "").strip().strip("/\\").replace("\\", "/")

    items: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort(key=str.lower)
        for filename in sorted(filenames, key=str.lower):
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            arcname = "%s/%s" % (prefix, rel) if prefix else rel
            items.append((arcname, full))
    return items


def clean_archive_name(name: str) -> str:
    """Normalize a path for storage inside an archive."""

    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    if not normalized:
        raise SafError("empty file name")
    if any(part == ".." for part in normalized.split("/")):
        raise SafError("'..' path components are not allowed")
    if "\n" in normalized or "\r" in normalized:
        raise SafError("line breaks are not allowed in file names")
    return normalized


def build(
    output_path: str,
    items: list[tuple[str, str]],
    progress=None,
    cancel=None,
) -> BuildResult:
    """Write a .saf archive from ``(archive name, source path)`` pairs.

    The output is written to a temporary file next to ``output_path`` and moved
    into place only after every byte has been copied.
    """

    output_path = os.path.abspath(output_path)
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    prepared: list[tuple[str, str, int]] = []
    result = BuildResult(path=output_path)
    skip = os.path.normcase(output_path)
    for arcname, source in items:
        if os.path.normcase(os.path.abspath(source)) == skip:
            continue  # never pack the archive into itself
        try:
            name = clean_archive_name(arcname)
            size = os.path.getsize(source)
        except (SafError, OSError) as exc:
            result.errors.append((arcname, str(exc)))
            continue
        prepared.append((name, source, size))

    if not prepared:
        raise SafError("nothing to pack: no readable files were selected")

    total = sum(size for _, _, size in prepared)
    result.total_bytes = total

    handle, temp_path = tempfile.mkstemp(
        prefix=".saf-build-", suffix=".tmp", dir=out_dir
    )
    os.close(handle)
    done = 0
    next_report = CHUNK
    try:
        with open(temp_path, "wb") as out:
            header = bytearray()
            for name, _, size in prepared:
                header += b"%d " % size
                header += _encode_name(name)
                header += b"\n"
            header += TERMINATOR
            out.write(bytes(header))

            for name, source, size in prepared:
                if cancel is not None and cancel():
                    result.cancelled = True
                    break
                if progress is not None:
                    progress(done, total, name)
                try:
                    with open(source, "rb") as src:
                        while True:
                            if cancel is not None and cancel():
                                raise _Cancelled
                            block = src.read(CHUNK)
                            if not block:
                                break
                            out.write(block)
                            done += len(block)
                            if progress is not None and done >= next_report:
                                next_report = done + CHUNK
                                progress(done, total, name)
                except _Cancelled:
                    result.cancelled = True
                    break
                except OSError as exc:
                    result.errors.append((name, str(exc)))
                    raise SafError(
                        "could not read %s: %s" % (source, exc)
                    ) from exc
                result.count += 1

        if result.cancelled:
            return result

        written = os.path.getsize(temp_path)
        expected = len(header) + total
        if written != expected:
            raise SafError(
                "wrote %d bytes but expected %d" % (written, expected)
            )
        os.replace(temp_path, output_path)
        temp_path = ""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    if progress is not None:
        progress(total, total, "")
    return result


def human_size(count: int) -> str:
    """Format a byte count for display."""

    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return "%d B" % int(value)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%d B" % count

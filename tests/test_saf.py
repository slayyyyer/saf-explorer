"""Tests for the SAF reader/writer.  Run: py -m unittest discover -s tests -v"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import safcore

SAMPLE_SAF = os.environ.get(
    "MXS_SAF_TEST_FILE",
    os.path.join(
        os.environ.get("LOCALAPPDATA", r"C:\Users\justin\AppData\Local"),
        "MX Simulator",
        "2025WinterCupOBJ.saf",
    ),
)


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="saf-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _make_source(self, files):
        folder = os.path.join(self.tmp, "src")
        for name, payload in files.items():
            path = os.path.join(folder, name.replace("/", os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(payload)
        return folder

    def test_build_then_read(self):
        folder = self._make_source(
            {
                "track/track.jm": b"JM1\n1 2 3\n",
                "track/decal one.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
                "track/empty.sec": b"",
            }
        )
        items = safcore.collect_files(folder, "mytrack")
        out = os.path.join(self.tmp, "out.saf")
        result = safcore.build(out, items)
        self.assertEqual(result.count, 3)
        self.assertFalse(result.cancelled)

        archive = safcore.read(out)
        names = [entry.name for entry in archive.entries]
        self.assertEqual(
            names,
            [
                "mytrack/track/decal one.png",
                "mytrack/track/empty.sec",
                "mytrack/track/track.jm",
            ],
        )
        self.assertEqual(archive.warnings, [])

        # Header text matches the documented format byte for byte.
        with open(out, "rb") as handle:
            head = handle.read(archive.data_offset)
        expected = (
            b"%d mytrack/track/decal one.png\n"
            b"0 mytrack/track/empty.sec\n"
            b"%d mytrack/track/track.jm\n"
            b"-\n"
        ) % (58, 10)
        self.assertEqual(head, expected)

        dest = os.path.join(self.tmp, "extracted")
        extracted = safcore.extract(archive, dest)
        self.assertEqual(extracted.written, 3)
        self.assertEqual(extracted.errors, [])
        with open(os.path.join(dest, "mytrack", "track", "track.jm"), "rb") as handle:
            self.assertEqual(handle.read(), b"JM1\n1 2 3\n")
        with open(os.path.join(dest, "mytrack", "track", "empty.sec"), "rb") as handle:
            self.assertEqual(handle.read(), b"")

    def test_header_is_the_only_format(self):
        # A hand-written archive written straight from the spec.
        path = os.path.join(self.tmp, "manual.saf")
        data = b"hello"
        with open(path, "wb") as handle:
            handle.write(b"5 a/test.txt\n-\n" + data)
        archive = safcore.read(path)
        self.assertEqual(len(archive.entries), 1)
        self.assertEqual(archive.entries[0].name, "a/test.txt")
        self.assertEqual(archive.entries[0].offset, len(b"5 a/test.txt\n-\n"))
        dest = os.path.join(self.tmp, "manual")
        safcore.extract(archive, dest)
        with open(os.path.join(dest, "a", "test.txt"), "rb") as handle:
            self.assertEqual(handle.read(), data)

    def test_offsets_are_cumulative(self):
        folder = self._make_source(
            {"b.bin": b"x" * 300, "a.bin": b"y" * 7, "c.bin": b"z" * 129}
        )
        out = os.path.join(self.tmp, "cum.saf")
        safcore.build(out, safcore.collect_files(folder, None))
        archive = safcore.read(out)
        expected = archive.data_offset
        for entry in archive.entries:
            self.assertEqual(entry.offset, expected)
            expected += entry.size
        self.assertEqual(expected, os.path.getsize(out))

    def test_selective_extract_and_skip(self):
        folder = self._make_source({"one.txt": b"1", "two.txt": b"22", "three.txt": b"333"})
        out = os.path.join(self.tmp, "sel.saf")
        safcore.build(out, safcore.collect_files(folder, None))
        archive = safcore.read(out)
        dest = os.path.join(self.tmp, "sel")

        first = safcore.extract(
            archive,
            dest,
            entries=[entry for entry in archive.entries if entry.name != "three.txt"],
        )
        self.assertEqual(first.written, 2)
        self.assertFalse(os.path.exists(os.path.join(dest, "three.txt")))

        second = safcore.extract(archive, dest, overwrite=False)
        self.assertEqual(second.skipped, 2)
        self.assertEqual(second.written, 1)

    def test_cancel_stops_early(self):
        folder = self._make_source({"big.bin": b"a" * (3 * safcore.CHUNK)})
        out = os.path.join(self.tmp, "cancel.saf")
        safcore.build(out, safcore.collect_files(folder, None))
        archive = safcore.read(out)
        state = {"calls": 0}

        def cancel():
            state["calls"] += 1
            return state["calls"] > 1

        result = safcore.extract(archive, os.path.join(self.tmp, "c"), cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertLess(result.written, 2)

    def test_hostile_names_are_rejected(self):
        for bad in ("../escape.txt", "/abs.txt", "C:/drive.txt", "a/../../b.txt"):
            with self.assertRaises(safcore.SafError):
                safcore.sanitize_name(bad)
        self.assertEqual(
            safcore.sanitize_name("track/models/post.jm"),
            os.path.join("track", "models", "post.jm"),
        )
        self.assertEqual(safcore.sanitize_name("a/CON"), os.path.join("a", "_CON"))

    def test_path_separators_are_normalized_on_write(self):
        folder = self._make_source({"sub/deep/file.png": b"data"})
        out = os.path.join(self.tmp, "sep.saf")
        items = safcore.collect_files(folder, "root")
        self.assertIn("root/sub/deep/file.png", [name for name, _ in items])
        safcore.build(out, items)
        with open(out, "rb") as handle:
            head = handle.read(200)
        self.assertNotIn(b"\\", head)

    def test_collect_files_without_root(self):
        folder = self._make_source({"x.txt": b"1", "sub/y.txt": b"2"})
        items = safcore.collect_files(folder, None)
        self.assertEqual([name for name, _ in items], ["x.txt", "sub/y.txt"])

    def test_not_a_saf(self):
        path = os.path.join(self.tmp, "junk.saf")
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        with self.assertRaises(safcore.SafError):
            safcore.read(path)

    def test_packing_an_empty_folder_fails(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        with self.assertRaises(safcore.SafError):
            safcore.build(os.path.join(self.tmp, "e.saf"), safcore.collect_files(empty, None))


@unittest.skipUnless(os.path.exists(SAMPLE_SAF), "sample archive not available")
class RealArchiveTests(unittest.TestCase):
    """Round-trip a retail archive byte for byte."""

    def test_extract_and_repack_is_identical(self):
        tmp = tempfile.mkdtemp(prefix="saf-real-")
        self.addCleanup(shutil.rmtree, tmp, True)

        archive = safcore.read(SAMPLE_SAF)
        self.assertEqual(archive.warnings, [])
        self.assertTrue(archive.terminator)
        self.assertEqual(archive.data_offset + archive.total_size, archive.file_size)

        dest = os.path.join(tmp, "extracted")
        result = safcore.extract(archive, dest)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.written, len(archive.entries))

        # Repack in the original header order; the result must be identical.
        items = [
            (entry.name, os.path.join(dest, safcore.sanitize_name(entry.name)))
            for entry in archive.entries
        ]
        rebuilt = os.path.join(tmp, "rebuilt.saf")
        safcore.build(rebuilt, items)

        with open(SAMPLE_SAF, "rb") as a, open(rebuilt, "rb") as b:
            original = a.read()
            produced = b.read()
        self.assertEqual(len(produced), len(original))
        self.assertEqual(produced, original)

    def test_offsets_point_at_real_data(self):
        archive = safcore.read(SAMPLE_SAF)
        checked = 0
        with open(SAMPLE_SAF, "rb") as handle:
            for entry in archive.entries:
                if entry.extension == ".png":
                    handle.seek(entry.offset)
                    magic = handle.read(8)
                    # MXS also allows tiny "LINK" stubs that point at another
                    # texture instead of holding PNG bytes.
                    self.assertTrue(
                        magic == b"\x89PNG\r\n\x1a\n" or magic.startswith(b"LINK "),
                        "%s starts with %r" % (entry.name, magic),
                    )
                    checked += 1
                elif entry.extension == ".jm":
                    handle.seek(entry.offset)
                    self.assertEqual(handle.read(3), b"JM1")
                    checked += 1
        self.assertGreater(checked, 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)

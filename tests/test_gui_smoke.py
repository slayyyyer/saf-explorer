"""Smoke test that drives the real Tkinter UI without human clicks.

Windows are withdrawn during the test; the dialogs are stubbed out.
Skipped when Tk cannot start (no display).
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import safcore

try:
    import tkinter as tk

    _probe = tk.Tk()
    _probe.destroy()
    HAVE_TK = True
except Exception:  # pragma: no cover - depends on the machine
    HAVE_TK = False

SAMPLE_SAF = os.environ.get(
    "MXS_SAF_TEST_FILE",
    os.path.join(
        os.environ.get("LOCALAPPDATA", r"C:\Users\justin\AppData\Local"),
        "MX Simulator",
        "2025WinterCupOBJ.saf",
    ),
)


@unittest.skipUnless(HAVE_TK, "Tk is not available")
class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        import safgui

        self.safgui = safgui
        self.dialogs = []
        for name in ("showinfo", "showwarning", "showerror"):
            setattr(
                safgui.messagebox,
                name,
                lambda *args, _name=name, **kwargs: self.dialogs.append((_name, args)),
            )
        safgui.messagebox.askyesno = lambda *args, **kwargs: True
        self.tmp = tempfile.mkdtemp(prefix="saf-gui-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app = safgui.App()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def _wait_for_worker(self, timeout=120.0):
        deadline = time.time() + timeout
        while self.app.worker_kind is not None and time.time() < deadline:
            self.app.update()
            time.sleep(0.02)
        self.app.update()
        self.assertIsNone(self.app.worker_kind, "background task did not finish")

    def test_extract_tab_lists_and_extracts(self):
        if not os.path.exists(SAMPLE_SAF):
            self.skipTest("sample archive not available")
        app = self.app
        app.load_archive(SAMPLE_SAF)
        self.assertIsNotNone(app.archive)
        self.assertEqual(len(app.visible_entries), len(app.archive.entries))
        self.assertEqual(len(app.tree.get_children()), len(app.archive.entries))

        # Filter narrows the list, clearing it restores every row.
        app.filter_var.set("models/bales")
        app.update()
        self.assertLess(len(app.visible_entries), len(app.archive.entries))
        self.assertGreater(len(app.visible_entries), 0)
        for entry in app.visible_entries:
            self.assertIn("models/bales", entry.name)
        app.filter_var.set("")
        app.update()
        self.assertEqual(len(app.visible_entries), len(app.archive.entries))

        # Extract a couple of entries through the real button handler.
        chosen = app.visible_entries[:3]
        index = {id(entry): position for position, entry in enumerate(app.visible_entries)}
        app.tree.selection_set([str(index[id(entry)]) for entry in chosen])
        dest = os.path.join(self.tmp, "out")
        app.dest_var.set(dest)
        app.extract_selected()
        self._wait_for_worker()

        for entry in chosen:
            path = os.path.join(dest, safcore.sanitize_name(entry.name))
            self.assertTrue(os.path.isfile(path), entry.name)
            self.assertEqual(os.path.getsize(path), entry.size)
        self.assertIn("Extracted 3 files", app.extract_status_var.get())

    def test_create_tab_builds_archive(self):
        app = self.app
        source = os.path.join(self.tmp, "mytrack")
        os.makedirs(os.path.join(source, "models"))
        with open(os.path.join(source, "models", "post.jm"), "wb") as handle:
            handle.write(b"JM1\n1 2 3\n")
        with open(os.path.join(source, "trackinfo.txt"), "wb") as handle:
            handle.write(b"name = My Track\n")

        app.source_folder = source
        app.root_name_var.set("mytrack")
        app.wrap_root_var.set(True)
        output = os.path.join(self.tmp, "mytrack.saf")
        app.output_var.set(output)
        app._reload_create_list()
        self.assertEqual(len(app.create_items), 2)
        self.assertEqual(len(app.create_tree.get_children()), 2)

        app.build_saf()
        self._wait_for_worker()
        self.assertTrue(os.path.isfile(output))
        archive = safcore.read(output)
        self.assertEqual(
            sorted(entry.name for entry in archive.entries),
            ["mytrack/models/post.jm", "mytrack/trackinfo.txt"],
        )
        self.assertIn("Built mytrack.saf", app.create_status_var.get())

    def test_exclude_removes_file_from_archive(self):
        app = self.app
        source = os.path.join(self.tmp, "pack")
        os.makedirs(source)
        for name in ("a.png", "b.png", "c.png"):
            with open(os.path.join(source, name), "wb") as handle:
                handle.write(b"x")
        app.source_folder = source
        app.root_name_var.set("pack")
        app.wrap_root_var.set(True)
        output = os.path.join(self.tmp, "pack.saf")
        app.output_var.set(output)
        app._reload_create_list()

        app.create_tree.selection_set([os.path.join(source, "b.png")])
        app.exclude_selected()
        self.assertEqual(len(app.create_items), 2)

        app.build_saf()
        self._wait_for_worker()
        names = [entry.name for entry in safcore.read(output).entries]
        self.assertEqual(sorted(names), ["pack/a.png", "pack/c.png"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

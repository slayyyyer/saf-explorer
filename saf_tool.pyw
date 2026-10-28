"""Double-click launcher for the MX Simulator SAF Tool (no console window)."""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from safgui import main
except Exception:  # pragma: no cover - only shown when double-clicked
    traceback.print_exc()
    raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        text = traceback.format_exc()
        print(text)
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror("MX Simulator SAF Tool", text[-1500:])
        except Exception:
            pass
        raise SystemExit(1)

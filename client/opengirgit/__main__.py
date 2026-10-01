"""``python -m opengirgit [--print-settings | --list-devices | --check-render]``"""

from __future__ import annotations

import os
import sys


def _main() -> int:
    args = sys.argv[1:]

    if "--check-render" in args:
        # Verify the vendored KaTeX + mermaid rendering without a display.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from .webview import check_render
        except Exception as exc:  # noqa: BLE001 - report it instead of crashing
            print(f"math/diagram rendering unavailable: {exc}")
            return 2
        return check_render()

    if "--print-settings" in args:
        from .app import print_settings

        return print_settings()

    if "--list-devices" in args:
        from .app import list_audio_devices

        return list_audio_devices()

    if "--help" in args or "-h" in args:
        print(
            "usage: python -m opengirgit "
            "[--print-settings | --list-devices | --check-render]\n\n"
            "Runs the OpenGirGit overlay. See README.md for setup."
        )
        return 0

    from .app import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_main())

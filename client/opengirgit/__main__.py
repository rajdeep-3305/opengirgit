"""``python -m opengirgit [--print-settings | --list-devices]``"""

from __future__ import annotations

import sys


def _main() -> int:
    args = sys.argv[1:]

    if "--print-settings" in args:
        from .app import print_settings

        return print_settings()

    if "--list-devices" in args:
        from .app import list_audio_devices

        return list_audio_devices()

    if "--help" in args or "-h" in args:
        print(
            "usage: python -m opengirgit [--print-settings | --list-devices]\n\n"
            "Runs the OpenGirGit overlay. See README.md for setup."
        )
        return 0

    from .app import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_main())

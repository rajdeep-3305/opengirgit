#!/usr/bin/env python
"""Convenience launcher: ``python main.py`` (see also ``python -m opengirgit``)."""

from __future__ import annotations

import sys

from opengirgit.__main__ import _main

if __name__ == "__main__":
    sys.exit(_main())

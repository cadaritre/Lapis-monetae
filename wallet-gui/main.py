#!/usr/bin/env python3
from __future__ import annotations

import sys

from wallet_app import WalletGui


def main() -> int:
    app = WalletGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)

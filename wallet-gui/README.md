# Lapis Monetae Wallet GUI

Modern desktop wallet launcher for Lapis Monetae, built in Python with Tkinter.

This GUI wraps the existing project CLI (`kaspa-cli` / `lmt-cli`) and does not replace wallet core logic.

## Features

- Dark modern UI with animated buttons and toast notifications
- Wallet Phase 1 flows:
  - create / import / open wallet
  - wallet list
  - account balances
  - show and generate receive addresses
- Wallet Phase 2 flows:
  - send LMT with validation and confirmation
  - transfer between accounts with validation and confirmation
- Interactive CLI commands open in a separate console for secure secret prompts

## Folder Structure

`wallet-gui/`

- `main.py` - app entrypoint
- `wallet_app/config.py` - config and CLI binary resolution
- `wallet_app/cli_bridge.py` - command execution helpers
- `wallet_app/ui_components.py` - reusable UI components
- `wallet_app/app.py` - GUI and feature logic

## Requirements

- Python 3.10+
- Local CLI binary available:
  - via PATH (`kaspa-cli` or `lmt-cli`), or
  - manually selected from the GUI

No extra pip dependencies are required.

## Run

From repository root:

```bash
python wallet-gui/main.py
```

## Usage

1. Open app.
2. Set CLI path with **Browse** + **Save** (or rely on PATH).
3. Select network (`mainnet`, `testnet-10`, `testnet-11`).
4. Use wallet actions:
   - **Create Wallet**
   - **Import Wallet**
   - **Open Wallet**
   - **Wallet List**
   - **Accounts/Balances**
   - **Show Address**
   - **New Address**
   - **Send LMT**
   - **Transfer Between Accounts**

## Notes

- Configuration is stored in `wallet-gui/.wallet_gui_config.json`.
- For operations requiring wallet secrets, a new terminal console is spawned.
- GUI output panel logs command execution and results.

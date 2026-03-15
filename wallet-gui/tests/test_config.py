"""Smoke tests for wallet_app.config — load, save, profile migration."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wallet_app.config import (
    DEFAULT_NETWORK,
    PROFILE_DEFAULTS,
    active_profile,
    load_config,
    save_config,
)


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("wallet_app.config.CONFIG_PATH", tmp_path / "nonexistent.json")
        cfg = load_config()
        assert cfg["_version"] == 2
        assert "default" in cfg["profiles"]

    def test_malformed_json_returns_defaults(self, tmp_path: Path, monkeypatch) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid json", encoding="utf-8")
        monkeypatch.setattr("wallet_app.config.CONFIG_PATH", bad)
        cfg = load_config()
        assert cfg["_version"] == 2

    def test_flat_config_migrated(self, tmp_path: Path, monkeypatch) -> None:
        flat = tmp_path / "flat.json"
        flat.write_text(json.dumps({"cli_path": "/usr/bin/cli", "network": "testnet-10"}), encoding="utf-8")
        monkeypatch.setattr("wallet_app.config.CONFIG_PATH", flat)
        cfg = load_config()
        assert cfg["_version"] == 2
        assert cfg["active_profile"] == "default"
        assert cfg["profiles"]["default"]["cli_path"] == "/usr/bin/cli"
        assert cfg["profiles"]["default"]["network"] == "testnet-10"

    def test_versioned_config_loaded_as_is(self, tmp_path: Path, monkeypatch) -> None:
        v2 = {
            "_version": 2,
            "active_profile": "test",
            "profiles": {"test": {"cli_path": "/bin/test", "network": "mainnet"}},
        }
        p = tmp_path / "v2.json"
        p.write_text(json.dumps(v2), encoding="utf-8")
        monkeypatch.setattr("wallet_app.config.CONFIG_PATH", p)
        cfg = load_config()
        assert cfg["active_profile"] == "test"
        assert cfg["profiles"]["test"]["cli_path"] == "/bin/test"


class TestActiveProfile:
    def test_returns_named_profile(self) -> None:
        cfg = {
            "_version": 2,
            "active_profile": "prod",
            "profiles": {"prod": {"cli_path": "/prod"}, "dev": {"cli_path": "/dev"}},
        }
        p = active_profile(cfg)
        assert p["cli_path"] == "/prod"

    def test_fallback_to_defaults(self) -> None:
        cfg = {"_version": 2, "active_profile": "missing", "profiles": {}}
        p = active_profile(cfg)
        assert p["network"] == DEFAULT_NETWORK


class TestSaveConfig:
    def test_round_trip(self, tmp_path: Path, monkeypatch) -> None:
        fp = tmp_path / "cfg.json"
        monkeypatch.setattr("wallet_app.config.CONFIG_PATH", fp)
        data = {"_version": 2, "active_profile": "x", "profiles": {"x": {"cli_path": "a"}}}
        save_config(data)
        loaded = json.loads(fp.read_text(encoding="utf-8"))
        assert loaded == data

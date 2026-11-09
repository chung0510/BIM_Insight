import os

import pytest
from pymongo.errors import PyMongoError

from app import db


ATLAS = "mongodb+srv://example:fake-password@cluster0.21qrqqs.mongodb.net/?retryWrites=true&w=majority"


@pytest.mark.parametrize("uri", [ATLAS, ATLAS + "&tls=true&tlsAllowInvalidCertificates=false", "mongodb://example:fake-password@cluster0.21qrqqs.mongodb.net/?tls=true"])
def test_atlas_connection_uses_verified_tls_without_leaking_to_other_hosts(uri, monkeypatch):
    calls = []
    client = object()
    monkeypatch.setattr(db, "MongoClient", lambda uri, **options: calls.append((uri, options)) or client)
    assert db.connect_database(uri, "bim_insight") is client
    assert calls[0][0] == uri
    assert calls[0][1]["tls"] is True
    assert calls[0][1]["connect"] is False
    assert calls[0][1]["serverSelectionTimeoutMS"] >= 5000


@pytest.mark.parametrize("uri", [
    "mongodb+srv://example:fake-password@cluster0.21qrqqs.mongodb.net/?tls=false",
    "mongodb+srv://example:fake-password@cluster0.21qrqqs.mongodb.net/?ssl=false",
    "mongodb+srv://example:fake-password@cluster0.21qrqqs.mongodb.net/?tlsInsecure=true",
    "mongodb+srv://example:fake-password@cluster0.21qrqqs.mongodb.net/?tlsAllowInvalidCertificates=true",
    "mongodb+srv://example:fake-password@cluster0.21qrqqs.mongodb.net/?tlsAllowInvalidHostnames=true",
    "mongodb://cluster0.21qrqqs.mongodb.net/?retryWrites=true;tlsAllowInvalidCertificates=true",
    "mongodb+srv://cluster0.21qrqqs.mongodb.net/?retryWrites=true;tlsAllowInvalidHostnames=true",
    "mongodb+srv://cluster0.21qrqqs.mongodb.net/?retryWrites=true;tlsInsecure=true",
    "mongodb+srv://example:fake-password@cluster0.21qrqqs.mongodb.net.evil.example/",
    "mongodb://remote.example:27017",
    "mongodb+srv://localhost/",
])
def test_invalid_remote_configuration_is_rejected_before_driver_connect(uri, monkeypatch):
    monkeypatch.setattr(db, "MongoClient", lambda *args, **kwargs: pytest.fail("Untrusted connection reached driver"))
    with pytest.raises(ValueError) as error:
        db.connect_database(uri, "bim_insight")
    assert "fake-password" not in str(error.value)


def test_database_configuration_environment_takes_priority_over_private_file(tmp_path, monkeypatch):
    (tmp_path / "database.dpapi").write_bytes(b"corrupt")
    monkeypatch.setenv("BIM_MONGODB_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("BIM_DATABASE", "test_explicit")
    assert db.database_settings(tmp_path) == ("mongodb://127.0.0.1:27017", "test_explicit")


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_private_database_configuration_round_trip_and_database_override(tmp_path, monkeypatch):
    monkeypatch.delenv("BIM_MONGODB_URI", raising=False)
    monkeypatch.delenv("BIM_DATABASE", raising=False)
    db.save_database_settings(tmp_path, ATLAS, "bim_insight")
    stored = (tmp_path / "database.dpapi").read_bytes()
    assert b"fake-password" not in stored and b"mongodb" not in stored
    assert db.database_settings(tmp_path) == (ATLAS, "bim_insight")
    monkeypatch.setenv("BIM_DATABASE", "test_isolated")
    assert db.database_settings(tmp_path) == (ATLAS, "test_isolated")


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_corrupt_private_configuration_never_silently_falls_back_to_local(tmp_path, monkeypatch):
    monkeypatch.delenv("BIM_MONGODB_URI", raising=False)
    (tmp_path / "database.dpapi").write_bytes(b"invalid encrypted configuration")
    with pytest.raises(ValueError, match="database configuration"):
        db.database_settings(tmp_path)


def test_no_configuration_keeps_local_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BIM_MONGODB_URI", raising=False)
    monkeypatch.delenv("BIM_DATABASE", raising=False)
    assert db.database_settings(tmp_path) == ("mongodb://127.0.0.1:27017", "bim_insight")


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_configuration_command_saves_source_and_windows_settings_without_printing_secrets(tmp_path, monkeypatch, capsys):
    from app import __main__ as cli
    from unittest.mock import MagicMock

    monkeypatch.delenv("BIM_MONGODB_URI", raising=False)
    monkeypatch.delenv("BIM_DATABASE", raising=False)
    monkeypatch.setenv("BIM_DATA_DIR", str(tmp_path / "source"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr("sys.argv", ["bim_backend", "--configure-database"])
    monkeypatch.setattr(cli, "getpass", lambda prompt: ATLAS)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    client = MagicMock()
    monkeypatch.setattr(cli, "connect_database", lambda uri, name: client)
    cli.main()
    client.admin.command.assert_called_once_with("ping")
    for folder in [tmp_path / "source", tmp_path / "local" / "com.noodt.bim-insight" / "inspections"]:
        assert db.database_settings(folder) == (ATLAS, "bim_insight")
    output = capsys.readouterr()
    assert "fake-password" not in output.out + output.err
    assert "mongodb+srv://" not in output.out + output.err


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_failed_configuration_ping_keeps_previous_settings(tmp_path, monkeypatch, capsys):
    from app import __main__ as cli

    monkeypatch.setenv("BIM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["bim_backend", "--configure-database"])
    monkeypatch.setattr(cli, "getpass", lambda prompt: ATLAS)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    db.save_database_settings(tmp_path, "mongodb://127.0.0.1:27017", "bim_insight")
    previous = (tmp_path / "database.dpapi").read_bytes()
    def unavailable(uri, name):
        raise PyMongoError("fake-password must not appear")
    monkeypatch.setattr(cli, "connect_database", unavailable)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert (tmp_path / "database.dpapi").read_bytes() == previous
    output = capsys.readouterr()
    assert "fake-password" not in output.out + output.err

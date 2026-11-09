"""Local UI fixture: deliver synthetic email only to the test artifact outbox."""
import json
import os
from pathlib import Path
import re
import runpy
import smtplib

from app.settings import save_settings

assert os.environ.get("BIM_UI_TEST") == "1"
assert os.environ.get("BIM_MONGODB_URI") == "mongodb://127.0.0.1:27017"
assert os.environ.get("BIM_DATABASE", "").startswith("bim_insight_test_accounts011_")
directory = Path(os.environ["BIM_DATA_DIR"]).resolve()
assert directory.is_relative_to(Path("data/artifacts/accounts-0110").resolve())
directory.mkdir(parents=True, exist_ok=True)
save_settings(directory, "mail", {"email": "ui-sender@gmail.com", "app_password": "abcdefghijklmnop"})


class TestSMTP:
    def __init__(self, host, port, **kwargs):
        assert host == "smtp.gmail.com" and port == 465 and kwargs.get("context")

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def login(self, email, password):
        assert email == "ui-sender@gmail.com" and password == "abcdefghijklmnop"

    def send_message(self, message):
        code = re.search(r"\b([0-9]{6})\b", message.get_content()).group(1)
        with (directory / "test-outbox.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"to": message["To"], "code": code}) + "\n")


smtplib.SMTP_SSL = TestSMTP
runpy.run_module("app", run_name="__main__")

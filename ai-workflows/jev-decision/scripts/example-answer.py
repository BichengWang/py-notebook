"""Write a schema 2 answer record for the bundled support-ticket example (CI helper, not packaged).

    python example-answer.py OUT [--sign-key KEYFILE]

Runs the real `jev-decision` command line against a stand-in provider that returns the first
hand-written example response, so no API key or network is used.
"""
import json
import sys
from pathlib import Path
from unittest import mock

from jevdecision import JevBackend
from jevdecision.__main__ import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
RESPONSE = json.loads((EXAMPLES / "support-ticket-responses.jsonl").read_text().splitlines()[0])["response"]

backend = JevBackend(api_key="unused", transport=lambda *args: RESPONSE, env={})
with mock.patch("jevdecision.__main__.create_backend", return_value=backend):
    sys.exit(main(["--questions", str(EXAMPLES / "support-ticket.json"),
                   "--state", "Help! My payouts have been failing for 3 days.",
                   "--out", sys.argv[1], *sys.argv[2:]]))

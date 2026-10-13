from __future__ import annotations

import base64
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
STATELESS_RULE_ID = "github-app-token-stateless"


def _config() -> dict[str, object]:
    return tomllib.loads((ROOT / ".gitleaks.toml").read_text())


def _segment(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _stateless_github_token() -> str:
    # Built at runtime so the repository never holds a detector-shaped literal.
    header = _segment({"alg": "RS256", "typ": "JWT", "kid": "s2s"})
    claims = _segment(
        {
            "iat": 1792000000,
            "exp": 1792003600,
            "iss": "github",
            "app": 1234567,
            "inst": 87654321,
            "sub": "installation|87654321",
        }
    )
    signature = ("Ab9-Cd8_Ef7" * 32)[:342]
    return "ghs" + "_1234567_" + ".".join((header, claims, signature))


def _rules() -> list[dict[str, object]]:
    rules = _config().get("rules", [])
    assert isinstance(rules, list)
    return rules


def test_secret_scan_keeps_the_upstream_ruleset() -> None:
    extend = _config().get("extend")

    assert isinstance(extend, dict)
    assert extend.get("useDefault") is True


def test_secret_scan_detects_stateless_github_app_tokens() -> None:
    token = _stateless_github_token()
    rules = [rule for rule in _rules() if rule.get("id") == STATELESS_RULE_ID]

    assert len(rules) == 1
    match = re.search(str(rules[0]["regex"]), f"export GITHUB_TOKEN={token}\n")
    keywords = rules[0].get("keywords")

    assert len(token) > 500
    assert match is not None
    assert match.group(0) == token
    assert isinstance(keywords, list)
    assert "ghs_" in keywords

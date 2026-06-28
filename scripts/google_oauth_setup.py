"""One-time Google OAuth setup for READ-ONLY Calendar access.

Cross-device friendly (no localhost browser needed):

  1. --start  prints a consent URL. Open it on any device and approve.
     Google then redirects to a localhost URL that will NOT load — that is
     expected. Copy that full URL from the address bar; it carries ?code=...
  2. --finish "<pasted URL or code>"  exchanges the code for a token and
     writes it to --token-out.

The token grants calendar.readonly only. Keep it out of git (store it under
HERMES_HOME or another path outside the repo).

  python google_oauth_setup.py --start  --client-secret <path> --token-out <path>
  python google_oauth_setup.py --finish "<pasted redirect URL>"
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
# Loopback redirect for a Desktop client. We do NOT run a server — the user
# copies the redirect URL back — so the page failing to load is fine.
REDIRECT_URI = "http://localhost:8765"
STATE_PATH = Path(tempfile.gettempdir()) / "pa_google_oauth_state.json"


def _start(client_secret: Path, token_out: Path) -> None:
    flow = Flow.from_client_secrets_file(
        str(client_secret), scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    STATE_PATH.write_text(
        json.dumps(
            {
                "client_secret": str(client_secret),
                "token_out": str(token_out),
                "code_verifier": flow.code_verifier,
            }
        ),
        encoding="utf-8",
    )
    print("AUTHORIZE_URL:")
    print(auth_url)


def _finish(response: str) -> None:
    if not STATE_PATH.exists():
        raise SystemExit("No pending flow — run --start first.")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    code = _extract_code(response)
    flow = Flow.from_client_secrets_file(
        state["client_secret"], scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    flow.code_verifier = state["code_verifier"]
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_out = Path(state["token_out"])
    token_out.parent.mkdir(parents=True, exist_ok=True)
    token_out.write_text(creds.to_json(), encoding="utf-8")
    STATE_PATH.unlink(missing_ok=True)
    print(f"Saved token to {token_out}")
    print(f"Scopes: {creds.scopes}")
    print(f"Has refresh token: {bool(creds.refresh_token)}")


def _extract_code(response: str) -> str:
    response = response.strip()
    if response.startswith("http"):
        query = parse_qs(urlparse(response).query)
        if "code" not in query:
            raise SystemExit("That URL has no ?code= — paste the full redirect URL.")
        return query["code"][0]
    return response  # assume a bare code was pasted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    start = sub.add_parser("start", help="print the consent URL")
    start.add_argument("--client-secret", required=True, type=Path)
    start.add_argument("--token-out", required=True, type=Path)
    finish = sub.add_parser("finish", help="exchange the pasted code for a token")
    finish.add_argument("response", help="the pasted redirect URL (or bare code)")
    args = parser.parse_args(argv)

    if args.cmd == "start":
        _start(args.client_secret, args.token_out)
    else:
        _finish(args.response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

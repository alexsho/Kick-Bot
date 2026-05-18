import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


KICK_AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
KICK_TOKEN_URL = "https://id.kick.com/oauth/token"

CLIENT_ID = os.getenv("KICK_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("KICK_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("KICK_REDIRECT_URI", "http://localhost:8421/callback")
SCOPES = os.getenv("KICK_OAUTH_SCOPES", "chat:write user:read")
TOKEN_PATH = Path(os.getenv("KICK_TOKEN_PATH", "tokens/kick_user_token.json"))


def base64_urlsafe(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def build_pkce_pair() -> tuple[str, str]:
    verifier = base64_urlsafe(secrets.token_bytes(48))
    challenge = base64_urlsafe(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def save_token(token: dict[str, Any]) -> None:
    token["expires_at"] = time.time() + int(token.get("expires_in", 0))
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TOKEN_PATH.open("w", encoding="utf-8") as token_file:
        json.dump(token, token_file, indent=2)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        expected_path = urlparse(REDIRECT_URI).path

        if parsed_url.path != expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = parse_qs(parsed_url.query)
        self.server.oauth_code = params.get("code", [""])[0]
        self.server.oauth_state = params.get("state", [""])[0]
        self.server.oauth_error = params.get("error", [""])[0]

        self.send_response(200)
        self.end_headers()
        self.wfile.write(
            b"Kick OAuth complete. You can close this tab and return to the terminal."
        )

    def log_message(self, format: str, *args: Any) -> None:
        return


def wait_for_callback(redirect_uri: str, timeout_seconds: int = 180) -> tuple[str, str]:
    parsed_redirect = urlparse(redirect_uri)
    host = parsed_redirect.hostname or "localhost"
    port = parsed_redirect.port or 80

    server = HTTPServer((host, port), OAuthCallbackHandler)
    server.timeout = 1
    server.oauth_code = ""
    server.oauth_state = ""
    server.oauth_error = ""

    deadline = time.monotonic() + timeout_seconds
    print(f"Waiting for OAuth callback on {redirect_uri}")

    while time.monotonic() < deadline:
        server.handle_request()
        if server.oauth_error:
            raise RuntimeError(f"Kick OAuth error: {server.oauth_error}")
        if server.oauth_code:
            return server.oauth_code, server.oauth_state

    raise TimeoutError("Timed out waiting for Kick OAuth callback.")


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Set KICK_CLIENT_ID and KICK_CLIENT_SECRET before running OAuth login."
        )

    code_verifier, code_challenge = build_pkce_pair()
    state = secrets.token_urlsafe(24)
    auth_params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
    }
    auth_url = f"{KICK_AUTHORIZE_URL}?{urlencode(auth_params)}"

    print("Open this URL in your browser and authorize the app:")
    print(auth_url)

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    code, returned_state = wait_for_callback(REDIRECT_URI)
    if returned_state != state:
        raise RuntimeError("OAuth state mismatch. Refusing to exchange token.")

    response = requests.post(
        KICK_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
            "code": code,
        },
        timeout=20,
    )
    response.raise_for_status()

    save_token(response.json())
    print(f"Saved Kick token to {TOKEN_PATH}")


if __name__ == "__main__":
    main()

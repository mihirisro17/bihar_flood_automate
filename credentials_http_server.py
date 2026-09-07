"""
Run this on your PC.

What it does:
  1. Makes sure token.json is valid -- refreshes it silently if possible,
     or opens your browser to log into Gmail if it's expired/missing.
  2. Starts a small HTTP server on your LAN that serves token.json and
     credentials.json, protected by a shared secret token.
  3. Keeps re-checking/serving whatever is currently on disk -- if you
     re-run a login later while this is still running, the next pull
     from the compute server just gets the newer file automatically.

The compute server (192.168.2.54) pulls from this every loop. If your
PC is off, dash.py on the server just keeps using whatever it last
pulled -- it does not crash or block waiting for the PC.

Usage:
    python credentials_http_server.py

Keep this running (e.g. in a terminal, or start it whenever you expect
the server might need a credential refresh). Ctrl+C to stop.
"""

import os
import sys
import http.server
import socketserver

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow

import config_loader

REPO_DIR = config_loader.get_repo_dir()
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
TOKEN_PATH = os.path.join(REPO_DIR, 'token.json')
CREDS_PATH = os.path.join(REPO_DIR, 'credentials.json')


def ensure_valid_token():
    if not os.path.exists(CREDS_PATH):
        print(f"ERROR: {CREDS_PATH} not found. Put your OAuth client "
              f"credentials.json here first (from Google Cloud Console).")
        sys.exit(1)

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.valid:
        print("token.json is already valid -- nothing to do.")
        return

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_PATH, 'w') as f:
                f.write(creds.to_json())
            print("Refreshed token.json silently (no browser needed).")
            return
        except RefreshError:
            print("Silent refresh failed -- falling back to a browser login...")

    flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, 'w') as f:
        f.write(creds.to_json())
    print("Login complete. token.json saved.")


class AuthHandler(http.server.BaseHTTPRequestHandler):
    auth_token = None  # set in main() before the server starts

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {AuthHandler.auth_token}"

    def _serve_file(self, path):
        if not self._authorized():
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return
        if not os.path.exists(path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        with open(path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/token.json":
            self._serve_file(TOKEN_PATH)
        elif self.path == "/credentials.json":
            self._serve_file(CREDS_PATH)
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[request] {self.address_string()} {fmt % args}")


def main():
    ensure_valid_token()

    config = config_loader.load_config(REPO_DIR)
    secrets = config_loader.load_secrets(REPO_DIR)

    port = config["pc_credentials_server"]["port"]
    auth_token = secrets.get("pc_credentials_auth_token")
    if not auth_token or auth_token == "CHANGE_ME_TO_A_LONG_RANDOM_STRING":
        print("ERROR: set a real, random pc_credentials_auth_token in "
              "secrets.local.json first (same value must be set on the "
              "compute server's secrets.local.json too).")
        sys.exit(1)

    AuthHandler.auth_token = auth_token

    with socketserver.TCPServer(("0.0.0.0", port), AuthHandler) as httpd:
        print(f"Serving token.json / credentials.json on 0.0.0.0:{port}")
        print("Keep this running so 192.168.2.54 can pull fresh credentials.")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()

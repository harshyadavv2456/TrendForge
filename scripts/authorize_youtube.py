"""One-time local OAuth helper. Never run this script in GitHub Actions or commit its output."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize your own YouTube channel for TrendForge uploads.")
    parser.add_argument("--client-secrets", required=True, help="Path to a Google OAuth Desktop App client JSON file")
    parser.add_argument(
        "--output",
        default=str(Path.home() / ".trendforge" / "token.json"),
        help="Path outside the repository to store OAuth credentials",
    )
    args = parser.parse_args()
    source = Path(args.client_secrets).expanduser().resolve()
    if not source.is_file():
        parser.error(f"Client JSON not found: {source}")
    flow = InstalledAppFlow.from_client_secrets_file(str(source), SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(credentials.to_json())
    if not data.get("refresh_token"):
        raise SystemExit(
            "Google did not issue a refresh token. Revoke the existing app grant and authorize again with prompt=consent."
        )
    output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass
    print(f"OAuth credentials saved outside the repository: {output}")
    print("Copy the refresh_token value from this local file into GitHub Actions secret YOUTUBE_REFRESH_TOKEN.")
    print("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET from the same OAuth client JSON as separate repository secrets.")
    print("Do not print, paste, email, or commit the refresh token or the JSON file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

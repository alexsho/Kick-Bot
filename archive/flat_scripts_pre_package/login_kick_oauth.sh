#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

read -r -p "Kick Client ID: " KICK_CLIENT_ID
read -r -s -p "Kick Client Secret: " KICK_CLIENT_SECRET
printf "\n"

export KICK_CLIENT_ID
export KICK_CLIENT_SECRET
export KICK_REDIRECT_URI="${KICK_REDIRECT_URI:-http://localhost:8421/callback}"
export KICK_OAUTH_SCOPES="${KICK_OAUTH_SCOPES:-chat:write user:read}"

python ./kick_oauth_login.py

unset KICK_CLIENT_SECRET

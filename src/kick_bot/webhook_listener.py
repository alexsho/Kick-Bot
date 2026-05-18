import base64
import binascii
import json
import os
import random
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn


VERIFY_KICK_SIGNATURE = os.getenv("KICK_VERIFY_SIGNATURE", "1") != "0"

KICK_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAq/+l1WnlRrGSolDMA+A8
6rAhMbQGmQ2SapVcGM3zq8ANXjnhDWocMqfWcTd95btDydITa10kDvHzw9WQOqp2
MZI7ZyrfzJuz5nhTPCiJwTwnEtWft7nV14BYRDHvlfqPUaZ+1KR4OCaO/wWIk/rQ
L/TjY0M70gse8rlBkbo2a8rKhu69RQTRsoaf4DVhDPEeSeI5jVrRDGAMGL3cGuyY
6CLKGdjVEM78g3JfYOvDU/RvfqD7L89TZ3iN94jrmWdGz34JNlEI5hqK8dd7C5EF
BEbZ5jgB8s8ReQV8H+MkuffjdAj3ajDDX3DOJMIut1lBrUVD1AaSrGCKHooWoL2e
twIDAQAB
-----END PUBLIC KEY-----"""

KEYWORDS = {
    "giveaway": [
        "I'm in!",
        "Count me in!",
        "Let's goooo",
    ],
    "hello": [
        "Hey chat!",
        "What's up everyone?",
    ],
}

app = FastAPI()
public_key = serialization.load_pem_public_key(KICK_PUBLIC_KEY)


def keyword_response(message: str) -> Optional[str]:
    lower_message = message.lower()

    for keyword, responses in KEYWORDS.items():
        if keyword in lower_message and responses:
            return random.choice(responses)

    return None


def verify_kick_signature(request: Request, raw_body: bytes) -> bool:
    message_id = request.headers.get("Kick-Event-Message-Id", "")
    timestamp = request.headers.get("Kick-Event-Message-Timestamp", "")
    signature = request.headers.get("Kick-Event-Signature", "")

    if not message_id or not timestamp or not signature:
        return False

    signed_payload = b".".join(
        [
            message_id.encode("utf-8"),
            timestamp.encode("utf-8"),
            raw_body,
        ]
    )

    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        public_key.verify(
            signature_bytes,
            signed_payload,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError, binascii.Error):
        return False


@app.post("/kick/events")
async def kick_events(request: Request) -> JSONResponse:
    raw_body = await request.body()
    event_type = request.headers.get("Kick-Event-Type", "")

    if VERIFY_KICK_SIGNATURE and not verify_kick_signature(request, raw_body):
        return JSONResponse({"ok": False, "error": "invalid signature"}, status_code=401)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

    if event_type == "chat.message.sent":
        sender = payload.get("sender") or {}
        username = sender.get("username", "Unknown")
        content = payload.get("content", "")

        print(f"{username}: {content}")

        response = keyword_response(content)
        if response:
            print(f"[BOT RESPONSE CANDIDATE]: {response}")
    else:
        print(f"[{event_type}] {payload}")

    return JSONResponse({"ok": True})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8420)

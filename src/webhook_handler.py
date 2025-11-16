import os
import json
import hmac
import base64
import hashlib
import time
from typing import Any, Dict, Tuple

import boto3


sns = boto3.client("sns")


def _get_raw_body(event: Dict[str, Any]) -> bytes:
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    if isinstance(body, str):
        return body.encode("utf-8")
    return json.dumps(body).encode("utf-8")


def _verify_signature(raw_body: bytes, headers: Dict[str, str]) -> Tuple[bool, str]:
    # Stripe verification takes precedence if configured
    stripe_secret = os.environ.get("STRIPE_ENDPOINT_SECRET", "")
    if stripe_secret:
        ok, reason = _verify_stripe_signature(raw_body, headers, stripe_secret)
        return ok, reason

    signing_secret = os.environ.get("SIGNING_SECRET", "")
    if not signing_secret:
        return True, "signature check skipped (no secret configured)"

    # Expect generic 'X-Signature' with hex HMAC-SHA256 over raw body using SIGNING_SECRET
    supplied_sig = headers.get("X-Signature") or headers.get("x-signature") or ""
    if not supplied_sig:
        return False, "missing X-Signature header"

    expected = hmac.new(signing_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, supplied_sig):
        return True, "signature valid"
    return False, "signature invalid"

def _verify_stripe_signature(raw_body: bytes, headers: Dict[str, str], endpoint_secret: str) -> Tuple[bool, str]:
    sig_header = headers.get("Stripe-Signature") or headers.get("stripe-signature")
    if not sig_header:
        return False, "missing Stripe-Signature header"

    # Parse header: t=timestamp, v1=signature[, v1=alt]...
    parts = {}
    for item in sig_header.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            v = v.strip()
            parts.setdefault(k, []).append(v)

    timestamps = parts.get("t")
    signatures = parts.get("v1") or []
    if not timestamps or not signatures:
        return False, "invalid Stripe-Signature header"

    timestamp = timestamps[0]
    signed_payload = f"{timestamp}.{raw_body.decode('utf-8')}"
    computed = hmac.new(endpoint_secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    # constant-time compare against any provided v1 signature
    if not any(hmac.compare_digest(computed, s) for s in signatures):
        return False, "signature mismatch"

    # Enforce timestamp tolerance
    try:
        tolerance = int(os.environ.get("STRIPE_TOLERANCE_SECONDS", "300"))
    except ValueError:
        tolerance = 300
    try:
        t_int = int(timestamp)
    except ValueError:
        return False, "invalid timestamp"
    if abs(int(time.time()) - t_int) > tolerance:
        return False, "timestamp outside tolerance"

    return True, "stripe signature valid"


def handler(event, _context):
    try:
        headers = event.get("headers") or {}
        raw_body = _get_raw_body(event)

        ok, reason = _verify_signature(raw_body, headers)
        if not ok:
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": "unauthorized", "reason": reason}),
            }

        topic_arn = os.environ["BROADCAST_TOPIC_ARN"]
        # Forward the raw event body so clients receive provider-native payloads
        sns.publish(
            TopicArn=topic_arn,
            Message=raw_body.decode("utf-8"),
            MessageAttributes={
                "type": {
                    "DataType": "String",
                    "StringValue": headers.get("X-Event-Type", "payment_event"),
                }
            },
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "ok"}),
        }
    except Exception as exc:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"message": "internal error", "error": str(exc)}),
        }



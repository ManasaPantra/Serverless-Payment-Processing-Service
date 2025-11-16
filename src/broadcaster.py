import os
import json
from typing import Any, Dict, List

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTION_TABLE_NAME"])


def _get_management_client() -> Any:
    api_id = os.environ["WEBSOCKET_API_ID"]
    stage = os.environ["WEBSOCKET_STAGE"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
    return boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=endpoint_url,
        config=Config(retries={"max_attempts": 2, "mode": "standard"}),
    )


def _list_connections() -> List[str]:
    connection_ids: List[str] = []
    scan_kwargs: Dict[str, Any] = {}
    while True:
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            cid = item.get("connectionId")
            if cid:
                connection_ids.append(cid)
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return connection_ids


def handler(event, _context):
    mgmt = _get_management_client()

    records = event.get("Records", [])
    messages: List[str] = []
    for r in records:
        msg = r.get("Sns", {}).get("Message")
        if msg:
            messages.append(msg)

    if not messages:
        return {"statusCode": 200, "body": json.dumps({"delivered": 0})}

    payload = messages[-1]  # if batching, just deliver the latest payload

    delivered = 0
    stale: List[str] = []
    for connection_id in _list_connections():
        try:
            mgmt.post_to_connection(ConnectionId=connection_id, Data=payload.encode("utf-8"))
            delivered += 1
        except ClientError as e:
            code = e.response["Error"].get("Code")
            if code in ("GoneException", "410"):
                stale.append(connection_id)
            else:
                # Best effort; continue
                pass

    # Clean up stale connections
    for cid in stale:
        try:
            table.delete_item(Key={"connectionId": cid})
        except Exception:
            pass

    return {"statusCode": 200, "body": json.dumps({"delivered": delivered, "staleCleaned": len(stale)})}



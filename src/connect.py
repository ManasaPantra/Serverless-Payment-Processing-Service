import os
import json
import boto3


table_name = os.environ["CONNECTION_TABLE_NAME"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(table_name)


def handler(event, _context):
    connection_id = event.get("requestContext", {}).get("connectionId")
    if not connection_id:
        return {"statusCode": 400, "body": "Missing connectionId"}

    item = {"connectionId": connection_id}
    try:
        table.put_item(Item=item)
        return {"statusCode": 200, "body": json.dumps({"connected": True})}
    except Exception as exc:
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}



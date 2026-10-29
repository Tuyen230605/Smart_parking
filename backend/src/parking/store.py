"""Truy cập DynamoDB bằng client cấp thấp: chuyển kiểu, ghi có điều kiện và transaction."""
import re
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


class ConditionFailed(Exception):
    pass


class TransactionCancelled(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__(f"transaction bị hủy: {reasons}")
        self.reasons = reasons

    def failed(self, index: int) -> bool:
        """Op thứ `index` trong transaction có điều kiện sai."""
        return index < len(self.reasons) and self.reasons[index] == "ConditionalCheckFailed"


def _prepare(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _prepare(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_prepare(v) for v in value]
    return value


def _restore(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _restore(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_restore(v) for v in value]
    return value


def marshal(item: dict) -> dict:
    """Bỏ thuộc tính None: GSI thưa (claim, purge) dựa vào việc thuộc tính vắng mặt."""
    return {k: _serializer.serialize(_prepare(v)) for k, v in item.items() if v is not None}


def unmarshal(item: dict) -> dict:
    return {k: _restore(_deserializer.deserialize(v)) for k, v in item.items()}


def _expr(condition=None, values=None, names=None, **extra) -> dict:
    out = {k: v for k, v in extra.items() if v is not None}
    if condition:
        out["ConditionExpression"] = condition
    if values:
        out["ExpressionAttributeValues"] = {k: _serializer.serialize(_prepare(v)) for k, v in values.items()}
    if names:
        out["ExpressionAttributeNames"] = names
    return out


def set_clause(fields: dict, appends: dict | None = None) -> tuple[str, dict, dict]:
    """Tạo `SET ... REMOVE ...` với tên thay thế cho mọi thuộc tính (tránh từ khóa như state, source).

    Giá trị None nghĩa là xóa thuộc tính. `appends` nối thêm phần tử vào thuộc tính dạng list.
    Placeholder dùng tiền tố #f/:f và #a/:a, condition không được trùng.
    """
    sets, removes, names, values = [], [], {}, {}
    for i, (name, value) in enumerate(fields.items()):
        names[f"#f{i}"] = name
        if value is None:
            removes.append(f"#f{i}")
        else:
            values[f":f{i}"] = value
            sets.append(f"#f{i} = :f{i}")
    for i, (name, items) in enumerate((appends or {}).items()):
        names[f"#a{i}"] = name
        values[f":a{i}"] = list(items)
        values[":a_empty"] = []
        sets.append(f"#a{i} = list_append(if_not_exists(#a{i}, :a_empty), :a{i})")
    expr = ("SET " + ", ".join(sets) if sets else "") + (" REMOVE " + ", ".join(removes) if removes else "")
    return expr.strip(), names, values


def op_put(table, item, condition=None, values=None, names=None) -> dict:
    return {"Put": {"TableName": table, "Item": marshal(item), **_expr(condition, values, names)}}


def op_update(table, key, update, condition=None, values=None, names=None) -> dict:
    return {"Update": {"TableName": table, "Key": marshal(key),
                       **_expr(condition, values, names, UpdateExpression=update)}}


def op_check(table, key, condition, values=None, names=None) -> dict:
    return {"ConditionCheck": {"TableName": table, "Key": marshal(key), **_expr(condition, values, names)}}


def op_delete(table, key, condition=None, values=None, names=None) -> dict:
    return {"Delete": {"TableName": table, "Key": marshal(key), **_expr(condition, values, names)}}


def _cancellation_reasons(error: ClientError) -> list[str]:
    reasons = error.response.get("CancellationReasons")
    if reasons:
        return [r.get("Code", "None") for r in reasons]
    # Một số phiên bản botocore/moto chỉ ghi lý do trong message: "... reasons [None, ConditionalCheckFailed]".
    m = re.search(r"\[([^\]]*)\]", error.response["Error"].get("Message", ""))
    return [s.strip() for s in m[1].split(",")] if m else []


class Db:
    def __init__(self, client=None):
        self.client = client or boto3.client("dynamodb")

    def get(self, table, key, consistent=True) -> dict | None:
        r = self.client.get_item(TableName=table, Key=marshal(key), ConsistentRead=consistent)
        return unmarshal(r["Item"]) if "Item" in r else None

    def batch_get(self, table, keys: list[dict]) -> list[dict]:
        out, pending = [], [marshal(k) for k in keys]
        for attempt in range(6):
            if not pending:
                return out
            r = self.client.batch_get_item(RequestItems={table: {"Keys": pending[:100], "ConsistentRead": True}})
            out += [unmarshal(i) for i in r["Responses"].get(table, [])]
            pending = pending[100:] + r.get("UnprocessedKeys", {}).get(table, {}).get("Keys", [])
            if pending:
                time.sleep(0.05 * 2**attempt)
        raise RuntimeError("batch_get còn key chưa đọc được sau nhiều lần thử")

    def put(self, table, item, condition=None, values=None, names=None):
        try:
            self.client.put_item(TableName=table, Item=marshal(item), **_expr(condition, values, names))
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConditionFailed() from None
            raise

    def update(self, table, key, update, condition=None, values=None, names=None, return_new=False) -> dict | None:
        try:
            r = self.client.update_item(
                TableName=table, Key=marshal(key),
                **_expr(condition, values, names, UpdateExpression=update,
                        ReturnValues="ALL_NEW" if return_new else None),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConditionFailed() from None
            raise
        return unmarshal(r["Attributes"]) if return_new else None

    def query(self, table, key_condition, values, names=None, index=None, filter=None, descending=False) -> list[dict]:
        kwargs = {"TableName": table, "KeyConditionExpression": key_condition, "ScanIndexForward": not descending,
                  **_expr(None, values, names, IndexName=index, FilterExpression=filter)}
        out = []
        while True:
            r = self.client.query(**kwargs)
            out += [unmarshal(i) for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return out
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def query_page(self, table, key_condition, values, names=None, index=None, descending=False, limit=20,
                   start_key: dict | None = None) -> tuple[list[dict], dict | None]:
        """Một trang kết quả; `start_key`/khóa trả về ở dạng thô của DynamoDB để làm cursor."""
        kwargs = {"TableName": table, "KeyConditionExpression": key_condition, "ScanIndexForward": not descending,
                  "Limit": limit, **_expr(None, values, names, IndexName=index, ExclusiveStartKey=start_key)}
        try:
            r = self.client.query(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationException" and start_key:
                raise ValueError("cursor không hợp lệ") from None
            raise
        return [unmarshal(i) for i in r["Items"]], r.get("LastEvaluatedKey")

    def transact(self, ops: list[dict]):
        try:
            self.client.transact_write_items(TransactItems=ops)
        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException":
                raise TransactionCancelled(_cancellation_reasons(e)) from None
            raise

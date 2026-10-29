"""Bảng DynamoDB giống infra/aws/template.yaml, dùng cho test (moto) và API local."""
from parking.config import Tables

LOCAL_TABLES = Tables(slots="slots", sessions="sessions", active_plates="active-plates", processed="processed",
                      devices="devices", pricing="pricing")


def _table(client, name, key, indexes=()):
    attrs = {key}
    gsis = []
    for index_name, pk, sk, projection in indexes:
        attrs |= {pk, sk}
        gsis.append({"IndexName": index_name,
                     "KeySchema": [{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": sk, "KeyType": "RANGE"}],
                     "Projection": projection})
    kwargs = {"GlobalSecondaryIndexes": gsis} if gsis else {}
    client.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
                        KeySchema=[{"AttributeName": key, "KeyType": "HASH"}], **kwargs)


def create_tables(client, tables: Tables = LOCAL_TABLES):
    _table(client, tables.slots, "slot_id")
    _table(client, tables.sessions, "session_id", [
        ("by_state", "state", "created_at", {"ProjectionType": "ALL"}),
        ("by_site", "site_id", "created_at", {"ProjectionType": "ALL"}),
        ("active_claims", "claim_pk", "claim_expires_at",
         {"ProjectionType": "INCLUDE",
          "NonKeyAttributes": ["state", "session_ref", "slot_id", "claim_nonce", "created_at"]}),
        ("purge_due", "pii_pk", "purge_due_at", {"ProjectionType": "KEYS_ONLY"}),
    ])
    _table(client, tables.active_plates, "plate_normalized")
    _table(client, tables.processed, "message_id")
    _table(client, tables.devices, "device_id")
    _table(client, tables.pricing, "pricing_id")

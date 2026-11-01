"""Kiểm infra/aws/template.yaml: quyền IAM so với thao tác code thực hiện, và cấu hình CORS. Moto không kiểm IAM, nên thiếu
quyền chỉ lộ ra khi chạy trên AWS (Codex #2: ApiFunction thiếu ConditionCheckItem trên Devices)."""
from pathlib import Path

import yaml

TEMPLATE = Path(__file__).resolve().parents[2] / "infra" / "aws" / "template.yaml"

# Action của policy template SAM (samtranslator policy_templates.json).
SAM_POLICIES = {
    "DynamoDBReadPolicy": {"GetItem", "Scan", "Query", "BatchGetItem", "DescribeTable"},
    "DynamoDBCrudPolicy": {"GetItem", "DeleteItem", "PutItem", "Scan", "Query", "UpdateItem", "BatchWriteItem",
                           "BatchGetItem", "DescribeTable", "ConditionCheckItem"},
}

# Thao tác DynamoDB code dùng, theo Lambda và bảng (gồm Put/Update/Delete/ConditionCheck trong transaction).
REQUIRED = {
    "IngestFunction": {
        "SessionsTable": {"GetItem", "PutItem", "UpdateItem"},
        "SlotsTable": {"GetItem", "BatchGetItem", "UpdateItem"},
        "ActivePlatesTable": {"GetItem", "PutItem"},
        "ProcessedTable": {"GetItem", "PutItem"},
        "DevicesTable": {"GetItem", "UpdateItem", "ConditionCheckItem"},
        "PricingTable": {"GetItem"},
    },
    "ApiFunction": {
        "SessionsTable": {"GetItem", "BatchGetItem", "PutItem", "UpdateItem", "Query"},
        "SlotsTable": {"GetItem", "BatchGetItem", "UpdateItem"},
        "ActivePlatesTable": {"GetItem", "PutItem", "DeleteItem"},
        "ProcessedTable": {"GetItem", "PutItem", "DeleteItem"},
        "DevicesTable": {"GetItem", "BatchGetItem", "ConditionCheckItem"},
        "PricingTable": {"GetItem", "UpdateItem"},
    },
    "JobsFunction": {
        "SessionsTable": {"GetItem", "BatchGetItem", "UpdateItem", "Query"},
        "SlotsTable": {"GetItem", "UpdateItem"},
        "ActivePlatesTable": {"GetItem", "DeleteItem"},
    },
}


class CfnLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node, deep=True)}
    return {suffix: loader.construct_mapping(node, deep=True)}


CfnLoader.add_multi_constructor("!", _intrinsic)


def _properties(resource: str) -> dict:
    template = yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=CfnLoader)
    return template["Resources"][resource]["Properties"]


def _policies(function: str) -> list:
    return _properties(function)["Policies"]


def _granted(function: str) -> tuple[dict[str, set[str]], set[str]]:
    """Trả (action DynamoDB theo bảng, các action khác)."""
    tables: dict[str, set[str]] = {}
    other: set[str] = set()
    for policy in _policies(function):
        for name, actions in SAM_POLICIES.items():
            if name in policy:
                tables.setdefault(policy[name]["TableName"]["Ref"], set()).update(actions)
        for statement in policy.get("Statement", []):
            actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            resource = statement["Resource"]
            table = resource["GetAtt"].split(".")[0] if isinstance(resource, dict) and "GetAtt" in resource else None
            for action in actions:
                if table and action.startswith("dynamodb:"):
                    tables.setdefault(table, set()).add(action.removeprefix("dynamodb:"))
                else:
                    other.add(action)
    return tables, other


def test_lambdas_have_dynamodb_actions_their_code_uses():
    for function, needs in REQUIRED.items():
        granted, _ = _granted(function)
        for table, actions in needs.items():
            missing = actions - granted.get(table, set())
            assert not missing, f"{function} thiếu {sorted(missing)} trên {table}"


def test_publishers_can_resolve_account_iot_endpoint():
    for function in ("IngestFunction", "ApiFunction"):
        _, other = _granted(function)
        assert {"iot:Publish", "iot:DescribeEndpoint"} <= other, function


def test_http_api_cors_survives_sam_transform():
    """AllowOrigins viết bằng hàm thì SAM coi hàm đó là toàn bộ cấu hình CORS và bỏ các khóa khác: API deploy ra
    không trả header CORS, web trên CloudFront báo không kết nối được máy chủ."""
    cors = _properties("HttpApi")["CorsConfiguration"]
    if set(cors) == {"If"}:
        configs = cors["If"][1:]
    else:
        configs = [cors]
        assert isinstance(cors["AllowOrigins"], list), "bọc cả CorsConfiguration trong hàm, không chỉ AllowOrigins"
    for config in configs:
        assert {"AllowOrigins", "AllowMethods", "AllowHeaders"} <= set(config)
        assert "Authorization" in config["AllowHeaders"] and "Idempotency-Key" in config["AllowHeaders"]

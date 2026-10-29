"""Log JSON một dòng cho CloudWatch. Không truyền biển số, email hay token vào đây (docs/aws-deployment.md §6)."""
import json


def log(event: str, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str), flush=True)

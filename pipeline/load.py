import json
from pathlib import Path

from .types import Record


def load_business_and_management(data_dir: Path) -> list[Record]:
    records: list[Record] = []

    clients_path = data_dir / "clients.json"
    with open(clients_path, "r", encoding="utf-8") as f:
        clients = json.load(f)
    for c in clients:
        records.append(
            Record(
                id=f"client:{c['client_id']}",
                source="clients",
                timestamp=c.get("onboarding_date", ""),
                attributes=dict(c),
            )
        )

    vendors_path = data_dir / "vendors.json"
    with open(vendors_path, "r", encoding="utf-8") as f:
        vendors = json.load(f)
    for v in vendors:
        records.append(
            Record(
                id=f"vendor:{v['client_id']}",
                source="vendors",
                timestamp=v.get("onboarding_date", ""),
                attributes=dict(v),
            )
        )

    return records

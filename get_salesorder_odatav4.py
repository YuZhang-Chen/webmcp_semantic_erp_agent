"""Run a local, server-side SAP OData V4 diagnostic GET.

This diagnostic is not the Phase 03 browser evidence gate. It is retained to
reproduce a known V4 SalesOrder read while the formal gate runs in Chrome.
The service root and credentials come from the local .env file; no value is
written to the repository or to sanitized evidence.
"""

from __future__ import annotations

import argparse
import os
import re
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth


def service_root(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("SAP_ODATA_BASE_URL must be an absolute HTTPS service root")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("SAP_ODATA_BASE_URL must not contain credentials, query, or fragment")
    if parsed.path in {"", "/"}:
        raise ValueError("SAP_ODATA_BASE_URL must include the complete V4 service path")
    return candidate + "/"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sales-order", required=True, help="Sales Order key kept local to this diagnostic")
    parser.add_argument("--env-file", default=".env")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv(args.env_file)
    sales_order = args.sales_order.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{1,10}", sales_order):
        raise SystemExit("--sales-order must be 1-10 alphanumeric characters")
    user = os.getenv("SAP_USER", "").strip()
    password = os.getenv("SAP_PASSWORD", "")
    if not user or not password:
        raise SystemExit("SAP_USER and SAP_PASSWORD are required in the local .env")
    root = service_root(os.getenv("SAP_ODATA_BASE_URL", ""))
    client = os.getenv("SAP_CLIENT", "").strip()
    language = os.getenv("SAP_LANGUAGE", "").strip()
    literal = sales_order.replace("'", "''")
    url = f"{root}SalesOrder('{literal}')"
    params = {"sap-client": client, "$expand": "_Item"}
    if language:
        params["sap-language"] = language
    response = requests.get(
        url,
        params=params,
        headers={"Accept": "application/json"},
        auth=HTTPBasicAuth(user, password),
        verify=True,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    print("Sales Order:", data["SalesOrder"])
    print("Customer:", data["SoldToParty"])
    print("Total:", data["TotalNetAmount"], data["TransactionCurrency"])

    print("\nItems:")

    items = data.get("_Item", [])
    if isinstance(items, dict):
        items = items.get("value", [])
    for item in items:
        print(
            "Item:", item.get("SalesOrderItem"),
            "Material:", item.get("Material"),
            "Qty:", item.get("RequestedQuantity"),
            "Net:", item.get("NetAmount"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

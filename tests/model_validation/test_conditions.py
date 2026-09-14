from copy import deepcopy

from semantic_model.conditions import (
    canonicalize_arguments,
    compile_condition_suite,
    verify_condition_suite,
)
from semantic_model.compiler import artifact_bytes


def test_condition_suite_preserves_canonical_contract(compilable_pair):
    model, _evidence, _official = compilable_pair
    catalogs, manifest = compile_condition_suite(model)
    assert verify_condition_suite(catalogs, manifest)
    assert set(catalogs) == {"A", "B", "C"}
    assert all(len(catalog["tools"]) == 4 for catalog in catalogs.values())
    assert [tool["operationId"] for tool in catalogs["A"]["tools"]] == [
        "get_related_billing_documents",
        "get_related_deliveries",
        "get_sales_order",
        "search_sales_orders",
    ]
    assert [tool["outputSchema"] for tool in catalogs["A"]["tools"]] == [
        tool["outputSchema"] for tool in catalogs["C"]["tools"]
    ]


def test_condition_suite_is_deterministic(compilable_pair):
    model, _evidence, _official = compilable_pair
    first_catalogs, first_manifest = compile_condition_suite(model)
    second_catalogs, second_manifest = compile_condition_suite(deepcopy(model))
    assert first_manifest == second_manifest
    for condition in ("A", "B", "C"):
        assert artifact_bytes(first_catalogs[condition]) == artifact_bytes(second_catalogs[condition])


def test_a_and_b_canonicalize_to_the_same_arguments():
    assert canonicalize_arguments(
        "A",
        "search_sales_orders",
        {
            "filter": {
                "SoldToParty": "CUST01",
                "SalesOrderDate": {"ge": "2026-01-01", "le": "2026-01-31"},
                "OverallSDProcessStatus": "C",
            }
        },
    ) == {
        "criteria": {
            "customer_id": "CUST01",
            "order_date_from": "2026-01-01",
            "order_date_to": "2026-01-31",
            "order_status": "completed",
        }
    }
    assert canonicalize_arguments("A", "get_sales_order", {"SalesOrder": "100001"}) == {
        "sales_order_id": "100001"
    }


def test_b_excludes_c_semantic_context(compilable_pair):
    model, _evidence, _official = compilable_pair
    catalogs, _manifest = compile_condition_suite(model)
    rendered = str([
        {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
            "annotations": tool["annotations"],
        }
        for tool in catalogs["B"]["tools"]
    ])
    assert "generates" not in rendered
    assert "唯讀政策" not in rendered
    assert "PGI" not in rendered
    assert "Sales Order" not in rendered

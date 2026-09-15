from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.serve_phase06 import build_state, service_root, verify_hash
from semantic_model.loader import load_model
from semantic_model.runtime import compile_runtime_bindings


ROOT = Path(__file__).resolve().parents[1]
MODEL = load_model(ROOT / "semantic_models/sap_sd/model.yaml")


def test_runtime_compiler_emits_four_get_only_operations():
    artifact = compile_runtime_bindings(MODEL)
    assert set(artifact["operations"]) == {
        "search_sales_orders",
        "get_sales_order",
        "get_related_deliveries",
        "get_related_billing_documents",
    }
    assert artifact["policy"] == {"allowedHttpMethods": ["GET"], "fallback": "forbidden", "maxRows": 50}
    assert artifact["artifactSha256"]


def test_runtime_artifact_hash_rejects_tampering():
    artifact = compile_runtime_bindings(MODEL)
    assert verify_hash(artifact)
    artifact["operations"]["search_sales_orders"]["binding"]["entity_set"] = "Unexpected"
    assert not verify_hash(artifact)


def test_service_root_rejects_non_https_or_embedded_credentials():
    with pytest.raises(RuntimeError):
        service_root("http://sap.example/odata", "SAP_ODATA_BASE_URL")
    with pytest.raises(RuntimeError):
        service_root("https://user:pass@sap.example/odata", "SAP_ODATA_BASE_URL")


def test_launcher_serves_only_selected_condition(tmp_path):
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    bindings_path = tmp_path / "bindings.json"
    bindings = compile_runtime_bindings(MODEL)
    bindings_path.write_text(json.dumps(bindings), encoding="utf-8")
    from semantic_model.conditions import compile_condition_suite, artifact_bytes

    catalogs, _manifest = compile_condition_suite(MODEL)
    for condition, catalog in catalogs.items():
        (catalog_dir / {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}[condition]).write_bytes(artifact_bytes(catalog))
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SAP_USER=test\nSAP_PASSWORD=test\nSAP_CLIENT=600\nSAP_LANGUAGE=ZF\n"
        "SAP_ODATA_BASE_URL=https://sap.example/sales/\n"
        "SAP_DELIVERY_ODATA_BASE_URL=https://sap.example/delivery/\n"
        "SAP_BILLING_ODATA_BASE_URL=https://sap.example/billing/\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok", encoding="utf-8")
    state = build_state("B", frontend, catalog_dir, bindings_path, env_path)
    assert state["catalog"]["condition"] == "B"
    assert set(state["config"]["services"]) == set(bindings["services"])


def test_local_gateway_runtime_does_not_expose_upstream_or_credentials(tmp_path):
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    bindings_path = tmp_path / "bindings.json"
    bindings = compile_runtime_bindings(MODEL)
    bindings_path.write_text(json.dumps(bindings), encoding="utf-8")
    from semantic_model.conditions import artifact_bytes, compile_condition_suite

    catalogs, _manifest = compile_condition_suite(MODEL)
    for condition, catalog in catalogs.items():
        (catalog_dir / {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}[condition]).write_bytes(artifact_bytes(catalog))
    ca_cert = tmp_path / "sap.crt"
    ca_cert.write_text("test certificate", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SAP_USER=test\nSAP_PASSWORD=secret\nSAP_CLIENT=600\nSAP_LANGUAGE=ZF\n"
        "SAP_ODATA_BASE_URL=https://sap.example/sales/\n"
        "SAP_DELIVERY_ODATA_BASE_URL=https://sap.example/delivery/\n"
        "SAP_BILLING_ODATA_BASE_URL=https://sap.example/billing/\n"
        f"SAP_ODATA_CA_CERT={ca_cert}\nSAP_ODATA_CERT_SHA256={'a' * 64}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok", encoding="utf-8")
    state = build_state("A", frontend, catalog_dir, bindings_path, env_path, "local-gateway")
    assert state["config"]["transport"] == "local-gateway"
    assert state["config"]["gateway_base_path"] == "/api/odata"
    assert "username" not in state["config"]
    assert "password" not in state["config"]
    assert all(value.startswith("/api/odata/") for value in state["config"]["services"].values())

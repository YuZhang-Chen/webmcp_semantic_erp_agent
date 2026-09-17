"""Provider-neutral headless tool-calling loop for the Phase 08 prototype.

The module deliberately keeps model orchestration separate from SAP execution:
catalogs describe what the model sees, while an executor receives only the
canonical operation and arguments after condition-specific validation.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from semantic_model.conditions import CANONICAL_OPERATIONS, canonicalize_arguments


class ToolExecutor(Protocol):
    def __call__(self, operation_id: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class AgentRunResult:
    answer: str
    tool_calls: int
    elapsed_seconds: float
    provider: str
    model: str


class ToolCallLimitExceeded(RuntimeError):
    """The agent requested a call beyond the run's configured budget."""

    def __init__(self, limit: int, attempted: int) -> None:
        self.limit = limit
        self.attempted = attempted
        super().__init__(f"tool call limit exceeded: attempted {attempted}, limit {limit}")


ToolCallObserver = Callable[[str, str, Mapping[str, Any], bool, Mapping[str, Any] | None, float, Exception | None], None]


def catalog_to_openai_tools(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert a governed A/B/C catalog to Responses function-tool shape."""
    tools = catalog.get("tools")
    if not isinstance(tools, list) or len(tools) != 4:
        raise ValueError("condition catalog must expose exactly four tools")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tools:
        if not isinstance(item, Mapping):
            raise ValueError("catalog tool must be an object")
        operation = str(item.get("operationId", ""))
        name = str(item.get("name", ""))
        if operation not in CANONICAL_OPERATIONS or not name or name in seen:
            raise ValueError("catalog contains an invalid or duplicate tool")
        schema = item.get("inputSchema")
        if not isinstance(schema, Mapping):
            raise ValueError(f"tool {name} is missing inputSchema")
        seen.add(name)
        result.append({"type": "function", "name": name, "description": str(item.get("description", "")), "parameters": dict(schema), "_operation_id": operation})
    if len({str(item.get("operationId")) for item in tools}) != 4:
        raise ValueError("catalog must contain all canonical operations")
    return result


class ReplayExecutor:
    """Explicit replay executor; no live fallback is permitted."""

    def __init__(self, records: Mapping[str, Any]) -> None:
        self.records = dict(records)

    def __call__(self, operation_id: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        key = json.dumps({"operation_id": operation_id, "arguments": arguments}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        result = self.records.get(key)
        if not isinstance(result, Mapping):
            raise KeyError(f"replay record missing for {operation_id}")
        return dict(result)


class GatewayRuntimeExecutor:
    """Execute canonical operations through the existing localhost gateway."""

    def __init__(self, bindings: Mapping[str, Any], config: Mapping[str, Any], *, base_url: str = "http://localhost:5173") -> None:
        self.bindings = bindings
        self.config = config
        self.base_url = base_url.rstrip("/")

    def _get(self, service_id: str, entity_set: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
        service = self.config.get("services", {}).get(service_id)
        if not isinstance(service, str):
            raise ValueError(f"unknown runtime service {service_id}")
        query_params = dict(params)
        client = self.config.get("client")
        if isinstance(client, str) and client.strip():
            query_params["sap-client"] = client.strip()
        language = self.config.get("language")
        if isinstance(language, str) and language.strip():
            query_params["sap-language"] = language.strip()
        query = urllib.parse.urlencode(query_params)
        url = f"{self.base_url}{service}/{entity_set}?{query}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"gateway OData request failed: {exc}") from exc
        rows = payload.get("d", {}).get("results")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError("gateway returned invalid OData V2 rows")
        return rows

    @staticmethod
    def _field(binding: Mapping[str, Any], name: str) -> str:
        item = binding.get("parameters", {}).get(name) or binding.get("output_fields", {}).get(name)
        if not isinstance(item, Mapping) or not item.get("property"):
            raise ValueError(f"runtime binding field missing: {name}")
        return str(item["property"])

    def __call__(self, operation_id: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = self.bindings.get("operations", {}).get(operation_id)
        if not isinstance(operation, Mapping):
            raise ValueError(f"runtime operation missing: {operation_id}")
        binding = operation.get("binding")
        if not isinstance(binding, Mapping) or binding.get("method") != "GET":
            raise ValueError("runtime operation is not a governed GET")
        service_id, entity_set = str(binding["service_id"]), str(binding["entity_set"])
        select = ",".join(sorted({str(item["property"]) for item in binding.get("output_fields", {}).values() if isinstance(item, Mapping) and item.get("step_ref") != "enrichment"}))
        filters: list[str] = []
        if operation_id == "search_sales_orders":
            criteria = arguments.get("criteria", {})
            for name, operator in (("customer_id", "eq"), ("order_date_from", "ge"), ("order_date_to", "le"), ("order_status", "eq")):
                if name not in criteria:
                    continue
                value = criteria[name]
                if name == "order_status":
                    value = next((code for code, label in binding.get("parameters", {}).get(name, {}).get("code_map", {}).items() if label == value), value)
                literal = str(value).replace("'", "''")
                if name.startswith("order_date"):
                    literal = f"datetime'{literal}T{'23:59:59' if operator == 'le' else '00:00:00'}'"
                else:
                    literal = f"'{literal}'"
                filters.append(f"{self._field(binding, name)} {operator} {literal}")
        else:
            order_id = str(arguments["sales_order_id"]).replace("'", "''")
            filters.append(f"{self._field(binding, 'sales_order_id')} eq '{order_id}'")
            if operation_id in {"get_related_deliveries", "get_related_billing_documents"}:
                discriminator = binding.get("discriminator", {})
                target = "outbound_delivery" if operation_id.endswith("deliveries") else "billing_document"
                category = next((code for code, label in discriminator.get("code_map", {}).items() if label == target), None)
                if not discriminator.get("property") or not category:
                    raise ValueError("runtime discriminator is incomplete")
                filters.append(f"{discriminator['property']} eq '{category}'")
        rows = self._get(service_id, entity_set, {"$select": select, "$filter": " and ".join(filters), "$top": "20", "$format": "json"})
        items: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {}
            for name, field in binding.get("output_fields", {}).items():
                if isinstance(field, Mapping) and field.get("property") in row and field.get("step_ref") != "enrichment":
                    item[name] = row[field["property"]]
            items.append(item)
        if operation_id == "get_sales_order":
            return {"sales_order": items[0] if items else None}
        return {"items": items, "count": len(items)}


class OpenAIResponsesAdapter:
    """Small stdlib-only OpenAI Responses function-calling adapter."""

    provider = "openai-responses"

    def __init__(self, *, api_key: str | None = None, endpoint: str | None = None, model: str | None = None, opener: Callable[..., Any] | None = None) -> None:
        provider = os.environ.get("AI_PROVIDER", "openai").strip().lower()
        if provider == "azure_openai":
            azure_root = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
            self.provider = "azure-openai-responses"
            self.api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
            configured_endpoint = endpoint or azure_root
            if configured_endpoint:
                path = urllib.parse.urlsplit(configured_endpoint).path.rstrip("/")
                if path.endswith("/openai/responses") or path.endswith("/openai/v1/responses"):
                    # Accept a complete Azure endpoint copied from the portal.
                    self.endpoint = configured_endpoint
                else:
                    self.endpoint = f"{configured_endpoint}/openai/v1/responses"
            else:
                self.endpoint = ""
            self.model = model or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "")
            self.auth_header = "api-key"
        else:
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
            self.endpoint = endpoint or os.environ.get("OPENAI_RESPONSES_ENDPOINT", "https://api.openai.com/v1/responses")
            self.model = model or os.environ.get("HEADLESS_AGENT_MODEL", "")
            self.auth_header = "Authorization"
        self.opener = opener or urllib.request.urlopen
        if not self.api_key:
            raise ValueError("provider API key is required")
        if not self.endpoint:
            raise ValueError("provider Responses endpoint is required")
        if not self.model:
            raise ValueError("provider model or deployment name is required")

    def _request(self, payload: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        auth_value = self.api_key if self.auth_header == "api-key" else f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={self.auth_header: auth_value, "Content-Type": "application/json"})
        try:
            with self.opener(request, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"OpenAI Responses request failed: {exc}") from exc
        if not isinstance(parsed, Mapping):
            raise RuntimeError("OpenAI Responses response must be an object")
        return parsed

    @staticmethod
    def _output_items(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        items = response.get("output", [])
        return [item for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []

    def run(self, system_prompt: str, task_prompt: str, tools: list[dict[str, Any]], executor: ToolExecutor, *, condition: str, timeout_seconds: int, tool_call_limit: int, observer: ToolCallObserver | None = None) -> AgentRunResult:
        started = time.monotonic()
        wire_tools = [{key: value for key, value in tool.items() if not key.startswith("_")} for tool in tools]
        # Azure's Responses endpoint requires an input item object here;
        # OpenAI also accepts this portable role/content representation.
        conversation: list[Any] = [{"role": "user", "content": task_prompt}]
        payload: dict[str, Any] = {"model": self.model, "instructions": system_prompt, "input": conversation, "tools": wire_tools, "store": False}
        calls = 0
        while True:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("headless run exceeded timeout")
            response = self._request(payload, remaining)
            items = self._output_items(response)
            function_calls = [item for item in items if item.get("type") == "function_call"]
            if not function_calls:
                answer = response.get("output_text")
                if not isinstance(answer, str):
                    # Azure currently returns output text inside the message
                    # content array and may omit the convenience output_text.
                    parts: list[str] = []
                    for item in items:
                        if item.get("type") != "message":
                            continue
                        content = item.get("content", [])
                        if isinstance(content, list):
                            parts.extend(str(part["text"]) for part in content if isinstance(part, Mapping) and part.get("type") == "output_text" and isinstance(part.get("text"), str))
                    answer = "".join(parts)
                if not answer:
                    raise RuntimeError("Responses result did not contain output text")
                return AgentRunResult(answer=answer, tool_calls=calls, elapsed_seconds=time.monotonic() - started, provider=self.provider, model=self.model)
            outputs: list[dict[str, Any]] = []
            conversation.extend(items)
            for call in function_calls:
                calls += 1
                name = str(call.get("name", ""))
                raw_arguments = call.get("arguments", "{}")
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                if not isinstance(arguments, Mapping):
                    raise ValueError("model function arguments must be an object")
                operation = next((str(tool["_operation_id"]) for tool in tools if tool.get("name") == name), None)
                if operation is None:
                    raise ValueError(f"model selected unknown tool {name!r}")
                canonical = canonicalize_arguments(condition, operation, arguments)
                if calls > tool_call_limit:
                    error = ToolCallLimitExceeded(tool_call_limit, calls)
                    if observer:
                        observer(name, operation, canonical, False, None, 0.0, error)
                    raise error
                call_started = time.monotonic()
                try:
                    result = executor(operation, canonical)
                except Exception as exc:
                    if observer:
                        observer(name, operation, canonical, False, None, time.monotonic() - call_started, exc)
                    raise
                if observer:
                    observer(name, operation, canonical, True, result, time.monotonic() - call_started, None)
                outputs.append({"type": "function_call_output", "call_id": call.get("call_id"), "output": json.dumps(result, ensure_ascii=False, sort_keys=True)})
            conversation.extend(outputs)
            payload = {"model": self.model, "instructions": system_prompt, "input": conversation, "tools": wire_tools, "store": False}

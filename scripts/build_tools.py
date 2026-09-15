from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from erp_webmcp.compiler import build  # noqa: E402

if __name__ == "__main__":
    manifest = build(ROOT / "semantic_model" / "sap_sd_order_flow.json", ROOT / "web" / "generated")
    print(f"compiled {manifest['modelId']} {manifest['modelVersion']}")

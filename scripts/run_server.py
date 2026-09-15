from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from erp_webmcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()

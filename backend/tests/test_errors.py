from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ingest.wechat_cli.errors import map_failure  # noqa: E402


def test_public_errors_hide_internal_name():
    for kind in ("not_found", "not_inited", "wechat_down", "timeout"):
        err = map_failure(kind)
        assert "wechat" not in err.public_message.lower()
        assert "cli" not in err.public_message.lower()

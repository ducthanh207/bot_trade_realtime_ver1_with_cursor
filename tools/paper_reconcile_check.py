# -*- coding: utf-8 -*-
"""
Đối chiếu vốn Paper / Paper 2 từ file paper_state.json (không cần web đang chạy).

  python tools/paper_reconcile_check.py --slot 2
  python tools/paper_reconcile_check.py --slot 1 --json D:\\path\\paper_state.json

Khi bot + web đang chạy có thể gọi: GET http://<host>:<port>/api/paper/reconcile?slot=2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    p = argparse.ArgumentParser(description="Double-check paper ledger vs Excel formulas")
    p.add_argument("--slot", type=int, default=1, choices=(1, 2), help="1=Paper, 2=Paper2")
    p.add_argument("--json", type=Path, default=ROOT / "paper_state.json", help="paper_state.json path")
    args = p.parse_args()

    try:
        from config import settings
    except Exception as e:
        print("Không import được config.settings:", e)
        return 1

    from bot.paper_ledger_audit import reconcile_trades

    path = args.json
    if not path.is_file():
        print("Không thấy file:", path)
        print("Gợi ý: chạy từ thư mục gốc project, hoặc truyền --json đầy đủ.")
        return 1

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    taker = float(getattr(settings, "TAKER_FEE", 0.0004))
    if args.slot == 2:
        trades = list(data.get("paper2_trades") or [])
        init_cap = float(data.get("paper2_initial_capital") or 0)
        bal = data.get("paper2_balance")
        has_open = bool(data.get("paper2_open_trade"))
        label = "Paper trade 2"
    else:
        trades = list(data.get("paper_trades") or [])
        init_cap = float(data.get("paper_initial_capital") or 0)
        bal = data.get("paper_balance")
        has_open = bool(data.get("paper_open_trade"))
        label = "Paper trade (1)"

    rep = reconcile_trades(
        trades,
        init_cap,
        taker,
        float(bal) if bal is not None else None,
        has_open,
    )

    print("===", label, "| slot=", args.slot, "| file=", path.name, "===")
    for k, v in rep.items():
        if k == "hints_vi":
            continue
        print(f"  {k}: {v}")
    print("--- gợi ý ---")
    for line in rep.get("hints_vi") or []:
        print(" ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

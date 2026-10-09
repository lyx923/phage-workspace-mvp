# scripts/backfill_time_semantics.py
"""
给历史数据补 valid_from / valid_to。
用法：
    python scripts/backfill_time_semantics.py
"""
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import get_driver
from src.shared.time_service import backfill_valid_from, time_coverage_report


def main():
    print("=" * 80)
    print(f"  Stage2 时间语义回填  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    driver = get_driver()
    try:
        result = backfill_valid_from(driver)
        print(f"\n回填 valid_from：{result['updated']} 条")
        for lb, c in result["by_label"].items():
            if c > 0:
                print(f"  {lb:30s} {c}")

        print("\n=== 覆盖率报告 ===")
        report = time_coverage_report(driver)
        for lb, r in report.items():
            print(f"  {lb:30s} {r['covered']}/{r['total']}  ({r['coverage']}%)")
    finally:
        driver.close()

    print("\n完成。")


if __name__ == "__main__":
    main()
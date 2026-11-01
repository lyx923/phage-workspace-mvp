# scripts/verify_requirements.py
import re, json, urllib.request
from pathlib import Path
from typing import List, Tuple, Optional

REQUIREMENTS_PATH = Path("requirements.txt")

def parse_requirements(path: Path) -> List[Tuple[str, str, str]]:
    results = []
    if not path.exists(): return results
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*(==|>=|~=)?\s*([0-9][^\s;#]*)", line)
        if m: results.append((m.group(1), m.group(2) or "", m.group(3) or ""))
    return results

def fetch_pypi(package: str) -> Optional[dict]:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status == 200: return json.loads(resp.read().decode("utf-8"))
    except Exception: return None

def version_exists_on_pypi(package: str, version: str) -> bool:
    data = fetch_pypi(package)
    if not data: return False
    releases = data.get("releases", {})
    return version in releases and len(releases[version]) > 0

def main():
    packages = parse_requirements(REQUIREMENTS_PATH)
    print(f"共检查 {len(packages)} 个依赖\n")
    invalid = []
    for pkg, op, ver in packages:
        if op == "==" and ver:
            exists = version_exists_on_pypi(pkg, ver)
            status = "✅" if exists else "❌"
            print(f"  {status} {pkg}=={ver}")
            if not exists: invalid.append((pkg, op, ver))
        elif op in (">=", "~=") and ver:
            data = fetch_pypi(pkg)
            if not data:
                print(f"  ⚠️ {pkg}{op}{ver}（无法访问 PyPI）")
                continue
            print(f"  ✅ {pkg}{op}{ver}（包存在）")
        else:
            data = fetch_pypi(pkg)
            status = "✅" if data else "❌"
            print(f"  {status} {pkg}（无版本约束）")
            if not data: invalid.append((pkg, op, ver))
    if invalid:
        print(f"\n需要人工处理 {len(invalid)} 项：")
        for pkg, op, ver in invalid: print(f"  {pkg}{op}{ver}")

if __name__ == "__main__":
    main()
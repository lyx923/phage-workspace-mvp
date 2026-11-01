# scripts/separate_legacy_deps.py
"""
R-08 修复工具：分析 _legacy_streamlit/ 的独有依赖。
将归档目录的 import 清单与主 requirements.txt 进行比对，
找出需要移入 _legacy_streamlit/requirements.txt 的专属包。

用法：
    python scripts/separate_legacy_deps.py
"""
import ast
import re
import sys
from pathlib import Path
from typing import Set

# 自动定位项目根目录（假设本脚本在 scripts/ 目录下）
ROOT = Path(__file__).resolve().parent.parent
LEGACY_DIR = ROOT / "_legacy_streamlit"
MAIN_REQUIREMENTS = ROOT / "requirements.txt"
LEGACY_REQUIREMENTS = LEGACY_DIR / "requirements.txt"

# import 名 → PyPI 包名（只覆盖常见差异）
IMPORT_TO_PACKAGE = {
    "dotenv": "python-dotenv",
    "dash_bootstrap_components": "dash-bootstrap-components",
    "dash_ag_grid": "dash-ag-grid",
    "dash_cytoscape": "dash-cytoscape",
    "dash_iconify": "dash-iconify",
    "sklearn": "scikit-learn",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
}


def collect_imports(directory: Path) -> Set[str]:
    """扫描目录下所有 .py 文件，提取最顶层的 import 模块名"""
    imports = set()
    if not directory.exists():
        return imports
    for py_file in directory.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
    return imports


def collect_main_packages(req_path: Path) -> Set[str]:
    """解析主 requirements.txt，提取包名并标准化（小写、下划线）"""
    packages = set()
    if not req_path.exists():
        return packages
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 剥离版本约束、环境标记等
        line = re.split(r"[<>=!~\[\];\s]", line, maxsplit=1)[0]
        if line:
            packages.add(line.lower().replace("-", "_"))
    return packages


def main():
    print(f"🔍 正在分析归档目录: {LEGACY_DIR}")
    
    if not LEGACY_DIR.exists():
        print(f"✅ 归档目录不存在，无需分离。")
        return

    legacy_imports = collect_imports(LEGACY_DIR)
    if not legacy_imports:
        print("✅ 归档目录下未发现任何 import。")
        return

    main_packages = collect_main_packages(MAIN_REQUIREMENTS)
    
    legacy_only = set()
    for pkg in legacy_imports:
        # 把 import 名映射为真实的 PyPI 包名并标准化
        mapped_pkg = IMPORT_TO_PACKAGE.get(pkg, pkg)
        normalized = mapped_pkg.lower().replace("-", "_")
        
        # 如果主依赖里没有这个包，说明它是 legacy 专属的
        if normalized not in main_packages:
            legacy_only.add(mapped_pkg)

    print("\n📦 归档目录独有 import（可能需要移入 _legacy_streamlit/requirements.txt）：")
    if not legacy_only:
        print("   （无独有依赖，主 requirements.txt 已全覆盖）")
    else:
        for pkg in sorted(legacy_only):
            print(f"   - {pkg}")

    print(f"\n💡 建议：")
    print(f"   1. 检查 {LEGACY_REQUIREMENTS} 是否已存在并包含上述包。")
    print(f"   2. 如果主项目已不再使用 Jupyter/Notebook 等功能，建议从主 requirements.txt 中移除，并归入 legacy。")

if __name__ == "__main__":
    main()
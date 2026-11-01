# scripts/v08_tools.py
"""
v0.8 修复工具集（合并 R-02 / R-05 / R-08 / R-11 的落地脚本）。

用法：
    python scripts/v08_tools.py docs           # 生成 docs/ontology_schema.md 骨架
    python scripts/v08_tools.py requirements   # 检查 requirements.txt 版本是否在 PyPI 存在
    python scripts/v08_tools.py legacy         # 分析 _legacy_streamlit/ 独有依赖
    python scripts/v08_tools.py schema         # 核查 Graph Schema v2 节点/关系/字段
    python scripts/v08_tools.py all            # 依次执行以上四项

对应 PRD：
    R-02 本体文档缺失
    R-05 疑似虚构版本号
    R-08 _legacy_streamlit/ 依赖归属不清
    R-11 Graph Schema v2 去向不明
"""
import argparse
import ast
import json
import re
import urllib.request
from pathlib import Path
from typing import List, Optional, Set, Tuple

ROOT = Path(".").resolve()
SRC_DIR = ROOT / "src"
PAGES_DIR = ROOT / "pages"
LEGACY_DIR = ROOT / "_legacy_streamlit"
MAIN_REQUIREMENTS = ROOT / "requirements.txt"
LEGACY_REQUIREMENTS = LEGACY_DIR / "requirements.txt"
DOCS_DIR = ROOT / "docs"
ONTOLOGY_DOC = DOCS_DIR / "ontology_schema.md"


# ============================================================
# 公共：遍历源码
# ============================================================
def _iter_py_files(*dirs: Path):
    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if any(part.startswith(".") for part in p.parts):
                continue
            yield p


# ============================================================
# R-02：生成本体文档骨架
# ============================================================
NODE_PATTERNS = [
    r"FOR\s*\(\s*\w*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*\)",
    r"\(\s*\w*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*\)",
    r"\bMERGE\s*\(\s*\w*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*",
    r"\bCREATE\s*\(\s*\w*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*",
    r"\bMATCH\s*\(\s*\w*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*",
]

REL_PATTERNS = [
    r"FOR\s*\(\)\s*-\s*\[\s*\w*\s*:\s*([A-Z][A-Z0-9_]*)\s*\]",
    r"\[\s*\w*\s*:\s*([A-Z][A-Z0-9_]*)\s*\]",
    r"-\s*\[\s*\w*\s*:\s*([A-Z][A-Z0-9_]*)\s*\]\s*->",
]

NODE_BLACKLIST = {
    "MATCH", "RETURN", "CREATE", "MERGE", "SET", "WITH", "WHERE",
    "UNWIND", "CALL", "YIELD", "OPTIONAL", "DETACH", "DELETE",
}


def _extract_from_source(source: str, patterns: List[str]) -> Set[str]:
    found = set()
    for pat in patterns:
        for m in re.findall(pat, source):
            if m and m not in NODE_BLACKLIST:
                found.add(m)
    return found


def _build_ontology_doc(nodes: Set[str], rels: Set[str]) -> str:
    lines = [
        "# Ontology Schema 文档骨架",
        "",
        "> 本文件由 `python scripts/v08_tools.py docs` 自动生成，请勿手工修改自动生成行。",
        "> 请领域专家在「定义（待补充）」列填入中文定义。",
        "",
        "## 节点标签（Node Labels）",
        "",
        "| 节点标签 | 定义（待补充） |",
        "|---|---|",
    ]
    lines += [f"| {n} | |" for n in sorted(nodes)]
    lines += [
        "",
        "## 关系类型（Relationship Types）",
        "",
        "| 关系类型 | 定义（待补充） |",
        "|---|---|",
    ]
    lines += [f"| {r} | |" for r in sorted(rels)]
    lines += [
        "",
        "## 关系矩阵（人工补充）",
        "",
        "> 用于记录关系的「主语 → 宾语」和是否候选收敛，避免同名不同义。",
        "",
        "| 关系类型 | 主语 | 宾语 | 说明 | 是否候选收敛 |",
        "|---|---|---|---|---|",
        "| TARGETS_PACKAGE | KnowledgeReuseEvent | ScientificEvidencePackage | 复用事件指向证据包 | 待 P2 评估 |",
        "| TARGETS_PATHOGEN | DevelopmentProgram | Pathogen | 开发项目靶向病原 | 待 P2 评估 |",
        "| TARGETS | EngineeredPhageConstruct | Pathogen | 构建体靶向病原 | 待 P2 评估 |",
        "",
    ]
    return "\n".join(lines) + "\n"


def run_docs():
    if not SRC_DIR.exists():
        raise FileNotFoundError(f"找不到源码目录: {SRC_DIR}")

    nodes, rels = set(), set()
    for py_file in _iter_py_files(SRC_DIR, PAGES_DIR):
        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        nodes |= _extract_from_source(source, NODE_PATTERNS)
        rels |= _extract_from_source(source, REL_PATTERNS)

    # 强制纳入已确认的 v0.7 / v0.8 节点和关系，避免正则漏抽
    nodes |= {
        "EnzymeGene", "BiofilmAssay", "ExperimentBatch", "SchemaVersion",
        "Phage", "HostStrain", "LysisAssay", "ClinicalCase",
        "ScientificEvidencePackage", "KnowledgeReuseEvent",
        "Pathogen", "Organization", "SourceArtifact", "Review", "AuditEvent",
        "OntologyModule", "ControlledVocabulary", "ControlledTerm",
    }
    rels |= {
        "ENGINEERED_FROM", "DISPLAYS", "DEGRADES", "BELONGS_TO_BATCH",
        "PRECEDED_BY", "USED_IN", "TESTED_AGAINST", "IS_STRAIN_OF",
        "INVOLVES_PATHOGEN", "TREATED_WITH", "HAS_ISOLATE",
        "TARGETS_PACKAGE", "TARGETS_PATHOGEN", "TARGETS",
        "COVERS", "BASED_ON", "REVIEWS", "HAS_SOURCE",
    }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ONTOLOGY_DOC.write_text(_build_ontology_doc(nodes, rels), encoding="utf-8")

    print(f"[R-02] 输出：{ONTOLOGY_DOC}")
    print(f"       节点标签：{len(nodes)} 个")
    print(f"       关系类型：{len(rels)} 个")


# ============================================================
# R-05：检查 requirements.txt 版本是否在 PyPI 存在
# ============================================================
def _parse_requirements(path: Path) -> List[Tuple[str, str, str]]:
    results = []
    if not path.exists():
        print(f"[R-05] ⚠️ 找不到 {path}")
        return results
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*(==|>=|~=)?\s*([0-9][^\s;#]*)", line)
        if m:
            results.append((m.group(1), m.group(2) or "", m.group(3) or ""))
    return results


def _fetch_pypi(package: str) -> Optional[dict]:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


def _version_exists_on_pypi(package: str, version: str) -> bool:
    data = _fetch_pypi(package)
    if not data:
        return False
    releases = data.get("releases", {})
    return version in releases and len(releases[version]) > 0


def run_requirements():
    packages = _parse_requirements(MAIN_REQUIREMENTS)
    print(f"[R-05] 共检查 {len(packages)} 个依赖\n")

    invalid = []
    for pkg, op, ver in packages:
        if op == "==" and ver:
            exists = _version_exists_on_pypi(pkg, ver)
            status = "✅" if exists else "❌"
            print(f"  {status} {pkg}=={ver}")
            if not exists:
                invalid.append((pkg, op, ver))
        elif op in (">=", "~=") and ver:
            data = _fetch_pypi(pkg)
            if not data:
                print(f"  ⚠️ {pkg}{op}{ver}（无法访问 PyPI，跳过）")
                continue
            print(f"  ✅ {pkg}{op}{ver}（包存在，版本约束交由 pip 解析）")
        else:
            data = _fetch_pypi(pkg)
            status = "✅" if data else "❌"
            print(f"  {status} {pkg}（无版本约束）")
            if not data:
                invalid.append((pkg, op, ver))

    if invalid:
        print(f"\n[R-05] 需要人工处理 {len(invalid)} 项：")
        for pkg, op, ver in invalid:
            print(f"  {pkg}{op}{ver} → 请确认包名/版本，或改为真实稳定版")
    else:
        print("\n[R-05] 所有声明均通过基础检查。")
        print("       建议再在干净虚拟环境执行 pip install -r requirements.txt 做最终验证。")


# ============================================================
# R-08：分析 _legacy_streamlit/ 独有依赖
# ============================================================
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


def _collect_imports(directory: Path) -> Set[str]:
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


def _collect_main_packages(req_path: Path) -> Set[str]:
    packages = set()
    if not req_path.exists():
        return packages
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.split(r"[<>=!~\[\];\s]", line, maxsplit=1)[0]
        if line:
            packages.add(line.lower().replace("-", "_"))
    return packages


def run_legacy():
    if not LEGACY_DIR.exists():
        print(f"[R-08] 归档目录不存在: {LEGACY_DIR}，无需分离。")
        return

    legacy_imports = _collect_imports(LEGACY_DIR)
    main_packages = _collect_main_packages(MAIN_REQUIREMENTS)

    legacy_only = set()
    for pkg in legacy_imports:
        normalized = IMPORT_TO_PACKAGE.get(pkg, pkg).lower().replace("-", "_")
        if normalized not in main_packages:
            legacy_only.add(IMPORT_TO_PACKAGE.get(pkg, pkg))

    print("[R-08] 归档目录独有 import（可能需要移入 _legacy_streamlit/requirements.txt）：")
    if not legacy_only:
        print("       （无独有依赖，主 requirements.txt 已覆盖）")
    else:
        for pkg in sorted(legacy_only):
            print(f"       {pkg}")

    print(f"\n[R-08] 建议：检查 {LEGACY_REQUIREMENTS} 是否已存在并覆盖上述包。")
    print("       注意：jupyter / notebook 如果主应用不再使用，建议只保留在 legacy 中。")


# ============================================================
# R-11：核查 Graph Schema v2 节点/关系/字段
# ============================================================
V2_NODES = [
    "EnzymeGene",
    "ExperimentBatch",
    "BiofilmAssay",
    "SchemaVersion",
]

V2_RELATIONS = [
    "ENGINEERED_FROM",
    "DISPLAYS",
    "DEGRADES",
    "BELONGS_TO_BATCH",
    "PRECEDED_BY",
]

PHAGE_V2_FIELDS = [
    "is_engineered",
    "engineering_status",
    "engineering_method",
    "parent_phage_id",
    "regulatory_status",
]

ENZYME_V2_FIELDS = [
    "gene_symbol",
    "enzyme_class",
    "target_polysaccharide",
    "specific_activity",
    "activity_assay_date",
    "sequence_verified",
    "expression_vector",
    "purification_method",
]


def _search_term(term: str) -> List[Tuple[str, int, str]]:
    hits = []
    for p in _iter_py_files(SRC_DIR, PAGES_DIR):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if term in line:
                hits.append((str(p.relative_to(ROOT)), i, line.strip()[:120]))
    return hits


def _report_section(title: str, terms: List[str]):
    print(f"\n=== {title} ===")
    for t in terms:
        hits = _search_term(t)
        if hits:
            print(f"  ✅ {t}: 命中 {len(hits)} 处")
            for path, lineno, snippet in hits[:3]:
                print(f"      {path}:{lineno}  {snippet}")
        else:
            print(f"  ❌ {t}: 全仓库零命中 → 若交接材料描述存在，请在 docs/v08_notes.md 标注「规划中」")


def run_schema():
    print("[R-11] Graph Schema v2 核查（基于当前仓库，不跨分支）")
    _report_section("v2 节点类型", V2_NODES)
    _report_section("v2 关系类型", V2_RELATIONS)
    _report_section("Phage v2 字段", PHAGE_V2_FIELDS)
    _report_section("EnzymeGene v0.7 字段", ENZYME_V2_FIELDS)

    print("\n[R-11] 说明：")
    print("       - 命中即表示当前代码已使用该节点/关系/字段。")
    print("       - 未命中不代表错误，可能尚未实现；请项目负责人决定补实现或标注规划中。")
    print("       - 跨分支核查命令：git branch -a，然后 checkout 对应分支重跑本脚本。")


# ============================================================
# 入口 python scripts/v08_tools.py docs
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="v0.8 修复工具集")
    parser.add_argument(
        "command",
        choices=["docs", "requirements", "legacy", "schema", "all"],
        help="要执行的子命令",
    )
    args = parser.parse_args()

    if args.command in ("docs", "all"):
        run_docs()
    if args.command in ("requirements", "all"):
        run_requirements()
    if args.command in ("legacy", "all"):
        run_legacy()
    if args.command in ("schema", "all"):
        run_schema()

if __name__ == "__main__":
    main()
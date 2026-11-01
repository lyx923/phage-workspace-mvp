# scripts/generate_ontology_docs.py
import re
from pathlib import Path

ROOT = Path(".").resolve()
SRC_DIR = ROOT / "src"
PAGES_DIR = ROOT / "pages"
DOCS_DIR = ROOT / "docs"
ONTOLOGY_DOC = DOCS_DIR / "ontology_schema.md"

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

NODE_BLACKLIST = {"MATCH", "RETURN", "CREATE", "MERGE", "SET", "WITH", "WHERE", "UNWIND", "CALL", "YIELD", "OPTIONAL", "DETACH", "DELETE"}

def _iter_py_files(*dirs: Path):
    for d in dirs:
        if not d.exists(): continue
        for p in d.rglob("*.py"):
            if any(part.startswith(".") for part in p.parts): continue
            yield p

def _extract_from_source(source: str, patterns: list[str]) -> set[str]:
    found = set()
    for pat in patterns:
        for m in re.findall(pat, source):
            if m and m not in NODE_BLACKLIST:
                found.add(m)
    return found

def _build_ontology_doc(nodes: set[str], rels: set[str]) -> str:
    lines = [
        "# Ontology Schema 文档骨架",
        "",
        "> 本文件由 `python scripts/generate_ontology_docs.py` 自动生成。",
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
        "| 关系类型 | 主语 | 宾语 | 说明 | 是否候选收敛 |",
        "|---|---|---|---|---|",
        "| TARGETS_PACKAGE | KnowledgeReuseEvent | ScientificEvidencePackage | 复用事件指向证据包 | 待 P2 评估 |",
        "| TARGETS_PATHOGEN | DevelopmentProgram | Pathogen | 开发项目靶向病原 | 待 P2 评估 |",
        "| TARGETS | EngineeredPhageConstruct | Pathogen | 构建体靶向病原 | 待 P2 评估 |",
        "",
    ]
    return "\n".join(lines) + "\n"

def main():
    nodes, rels = set(), set()
    for py_file in _iter_py_files(SRC_DIR, PAGES_DIR):
        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception: continue
        nodes |= _extract_from_source(source, NODE_PATTERNS)
        rels |= _extract_from_source(source, REL_PATTERNS)

    # 强制纳入已知节点和关系
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
    print(f"✅ 输出：{ONTOLOGY_DOC}")
    print(f"   节点标签：{len(nodes)} 个")
    print(f"   关系类型：{len(rels)} 个")

if __name__ == "__main__":
    main()
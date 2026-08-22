# **Phage Intelligence Workspace - MVP**

**噬菌体精准治疗循证决策支持系统 —— 最小可行产品验证**

## **📖 项目简介**

**Phage Intelligence Workspace** 是一个基于知识图谱和大语言模型的噬菌体精准治疗循证决策支持系统。本项目通过构建噬菌体-宿主互作知识图谱，结合 DeepSeek 大模型的检索增强生成能力，为多重耐药菌感染的噬菌体治疗提供**可追溯、可复用、可审核**的循证证据包。

本阶段（第二阶段）已完成从“知识图谱原型”到 **Ontology-driven Learning System 原型** 的升级，建立了完整的**证据升级-人工审核-知识复用**闭环，并抽取了企业级 Foundation 共享层（来源、审核、审计、主数据、版本控制）。

### **🎯 核心验证目标**

| 目标 | 说明 | 状态 |
|:---|:---|:---|
| **V1** | Ontology 能否承载真实临床数据？ | ✅ 16 例病例，必填字段填充率 100% |
| **V2** | 历史病例知识能否被复用？ | ✅ 跨病例复用验证通过 |
| **V3** | 学习闭环是否可演示？ | ✅ 完整链路已跑通 |

### **✨ 核心功能**

**知识图谱构建**：基于 Neo4j 存储病原菌、噬菌体、宿主菌株、裂解实验、临床病例  
**Ontology 驱动**：采用 Palantir-style Ontology，所有业务对象可操作、可审核、可追溯  
**黄金规则管理**：支持导入临床验证的配型规则（如 CRAB KL2 → ΦK2-v3），按菌种+菌型精确匹配  
**双引擎推荐**：
- 规则引擎：确定性逻辑，0 成本，0 幻觉
- LLM 引擎：基于 DeepSeek 的 RAG，生成自然语言证据包  
**知识策展闭环**：
1. 病例结局录入 → 自动创建升级提案（`EvidenceUpgradeProposal`）
2. 专家人工审核（`Review`） → 批准/拒绝/需修改
3. 执行升级 → 证据等级从 L1/L2 升级至 L3  
**跨病例复用检测**：自动识别相似病例，推荐复用历史经验，需专家确认后才生效  
**证据包持久化**：`ScientificEvidencePackage` 节点存储，支持审核和后续引用  
**共享 Foundation**：`SourceArtifact`（来源）、`Review`（审核）、`AuditEvent`（审计）、`Pathogen`/`Organization`（主数据）、`OntologyModule`（版本）、`ControlledVocabulary`（词表）

---

## **📦 数据模型**

### **核心实体（当前实现）**

| 实体 | 说明 | 关键属性 |
|:---|:---|:---|
| **Pathogen** (Foundation) | 病原菌主数据 | `pathogen_id`, `species`, `taxonomy_id`, `aliases` |
| **Organization** (Foundation) | 组织主数据 | `organization_id`, `canonical_name`, `country` |
| **SourceArtifact** (Foundation) | 来源制品（文献、病例、实验文件） | `source_id`, `source_type`, `title`, `uri_or_path`, `access_level` |
| **Review** (Foundation) | 统一审核记录 | `review_id`, `review_type`, `decision`, `reviewer_id` |
| **AuditEvent** (Foundation) | 审计事件（状态变更追溯） | `audit_event_id`, `action_type`, `before_snapshot`, `after_snapshot` |
| **OntologyModule** (Foundation) | 本体模块版本管理 | `module_id`, `version`, `schema_hash` |
| **ControlledTerm** / **ControlledVocabulary** (Foundation) | 受控词表 | 用于状态、类型等标准化 |
| **Phage** (Scientific) | 噬菌体 | `phage_id`, `name`, `family`, `receptor_target` |
| **HostStrain** (Scientific) | 宿主菌株（分离株） | `host_strain_id`, `strain_label` |
| **LysisAssay** (Scientific) | 裂解实验（替代 PhageHostInteraction） | `assay_id`, `result`, `result_value`, `evidence_level` (L1-L5), `qc_status` |
| **ClinicalCase** (Scientific) | 临床病例 | `case_id`, `infection_type`, `phage_treatment`, `clinical_outcome`, `host_strain` |
| **ScientificKnowledgeRule** (Scientific) | 黄金规则 | `rule_id`, `strain_type`, `treatment`, `outcome`, `applicability` |
| **EvidenceUpgradeProposal** (Scientific) | 证据升级提案 | `proposal_id`, `assay_id`, `current_level`, `proposed_level`, `status(pending_review/approved/rejected)` |
| **ScientificEvidencePackage** (Scientific) | 持久化证据包 | `package_id`, `query_context`, `summary`, `review_status` |
| **KnowledgeReuseEvent** (Scientific) | 知识复用事件 | `reuse_event_id`, `source_object_id`, `status(detected/confirmed/rejected)` |

### **证据等级体系**

| 等级 | 名称 | 含义 |
|:---|:---|:---|
| **L1** | PUBLISHED_LITERATURE | 公开文献报道 |
| **L2** | IN_VITRO_VERIFIED | 体外实验验证 |
| **L3** | CLINICAL_SINGLE_CASE | 单例临床验证 |
| **L4** | CLINICAL_MULTI_CENTER | 多中心临床验证 |
| **L5** | ORGANIZATIONAL_LEARNING | 组织学习闭环 |
| **黄金规则** | 独立于 L1-L5，基于临床验证规则 | 优先级最高，必须满足适用条件才应用 |

### **核心关系**

```text
(Phage)-[:USED_IN]->(LysisAssay)-[:TESTED_AGAINST]->(HostStrain)
(HostStrain)-[:IS_STRAIN_OF]->(Pathogen)
(ClinicalCase)-[:INVOLVES_PATHOGEN]->(Pathogen)
(ClinicalCase)-[:TREATED_WITH]->(Phage)
(ClinicalCase)-[:HAS_ISOLATE]->(HostStrain)
(Pathogen)-[:HAS_VALIDATED_RULE]->(ScientificKnowledgeRule)-[:RECOMMENDS_PHAGE]->(Phage)
(LysisAssay)-[:DERIVED_FROM]->(SourceArtifact)
(ClinicalCase)-[:DERIVED_FROM]->(SourceArtifact)
(EvidenceUpgradeProposal)<-[:REVIEWS]-(Review)
(ScientificEvidencePackage)-[:USES_ASSAY]->(LysisAssay)
(ScientificEvidencePackage)-[:REFERENCES_CASE]->(ClinicalCase)
(ScientificEvidencePackage)-[:INCLUDES_CANDIDATE]->(Phage)
(ScientificEvidencePackage)-[:CITES_SOURCE]->(SourceArtifact)
(KnowledgeReuseEvent)-[:REUSES]->(LysisAssay)
(KnowledgeReuseEvent)-[:SOURCE_CASE]->(ClinicalCase)
(KnowledgeReuseEvent)-[:TARGETS_PACKAGE]->(ScientificEvidencePackage)
```

## **🏗️ 项目结构**

```text  
phage-workspace-mvp/
├── README.md                     # 项目说明（本文档）
├── requirements.txt              # Python 依赖
├── .env                          # 环境变量（DS_API_KEY 等）
├── config.py                     # Neo4j + DeepSeek 配置
├── data/                         # 数据文件
│   ├── patients.csv              # 患者主数据
│   ├── cases.csv                 # 临床病例
│   ├── phage_interactions.csv    # 30 条噬菌体互作记录（旧格式，用于兼容）
│   └── 肺克数据脱敏.csv           # 大规模裂解谱数据（L2 级）
├── src/
│   ├── foundation/               # 共享基础层
│   │   ├── schema.py             # 约束、索引、OntologyModule、受控词表
│   │   └── audit_service.py      # 审计事件记录 (AuditEvent)
│   ├── scientific/               # 科学知识域
│   │   ├── import_service.py     # 数据导入（患者、病例、噬菌体、裂解谱、黄金规则）
│   │   ├── retriever_service.py  # 噬菌体匹配、相似病例、跨病例复用分析
│   │   ├── validator_service.py  # 菌株配型验证、聚类、伪型别推荐
│   │   ├── evidence_package_service.py # 证据包构建（规则 + LLM）与持久化
│   │   └── evidence_upgrade_service.py # 证据升级提案、审核、执行
│   └── ci/                       # （预留）竞争情报域（仅占位）
├── notebooks/                    # Jupyter Notebook 演示
│   ├── 01_data_import.ipynb      # 数据导入 + V1 验证
│   ├── 02_evidence_package.ipynb # 证据包展示与配型验证
│   └── 03_cross_case_reuse.ipynb # 证据升级、知识复用、审核闭环 ⭐核心
├── tests/                        # 单元/集成测试（待完善）
└── docs/                         # 附加文档
    └── ontology_schema.md        # 完整数据模型定义
```

## **🚀 快速开始**

### **环境要求**

| 组件  | 版本要求 |
| --- | --- |
| Python | 3.11+ |
| Neo4j | 5.x (Community Edition) |
| 内存  | ≥ 8GB |

### **1\. 克隆项目**

bash

git clone [https://github.com/lyx923/phage-workspace-mvp.git](https://github.com/your-repo/phage-workspace-mvp.git)

cd phage-workspace-mvp

### **2\. 安装依赖**

bash

pip install -r requirements.txt

**requirements.txt:**

text

neo4j==6.2.0

pandas==3.0.3

openai==2.45.0

python-dotenv==1.2.2

jupyter==1.1.1

notebook==7.6.0

### **3\. 启动 Neo4j**

Bash

\# Docker 方式（推荐）

docker run -d --name neo4j \\

\-p 7474:7474 -p 7687:7687 \\

\-e NEO4J_AUTH=neo4j/your-password \\

neo4j:5.26

\# 或使用 Neo4j Desktop

### **4\. 配置环境变量**

创建 .env 文件：

env

NEO4J_URI=bolt://localhost:7687

NEO4J_USER=neo4j

NEO4J_PASSWORD=your-password

DS_API_KEY=sk-your-deepseek-api-key

DS_MODEL=deepseek-chat

DS_TEMPERATURE=0.3

DS_MAX_TOKENS=4096

### **5\. 启动 Jupyter Notebook**

bash

jupyter notebook

### **6\. 运行演示**

 1. 打开 notebooks/01_data_import.ipynb，按顺序运行所有 Cell（导入数据）

 2. 打开 notebooks/02_evidence_package.ipynb，测试检索与证据包生成

 3. 打开 notebooks/03_cross_case_reuse.ipynb，体验升级、复用、审核闭环


## **📊 验证结果**

### **V1：Ontology 可承载数据 ✅**

| 检查项 | 结果  |
| --- | --- |
| 必填字段填充率 | **100%** |
| Pathogen 节点 | 5 个 |
| Phage 节点 | 49 个 |
| HostStrain 节点 | 235 条 |
| LysisAssay 节点 | 932 个 |
| ClinicalCase 节点 | 17 条 |
| ScientificKnowledgeRule 节点 | 3 条 |

### **V2：知识可复用 ✅**

用例：CASE-001（大肠杆菌 UTI，噬菌体有效）→ CASE-003（同菌种同感染类型）

结果：系统成功识别相似性，推荐复用相同噬菌体，复用类型：direct_reuse

### **V3：学习闭环可演示 ✅**

完整链路已跑通：CASE-001 治疗经验 → 自动创建升级提案 → 专家审核 → 执行证据等级变更 → 更新 LysisAssay → 生成审计日志

## **📋 演示脚本**

**启动**：streamlit run app.py 或者 jupyter notebook

**展示数据库**：运行 01_data_import.ipynb 末尾 Cell，输出节点和关系统计

**展示黄金规则**：运行 03_cross_case_reuse.ipynb 中 import_golden_rules 后的查询 Cell

**规则引擎推荐**：运行 rule_based_evidence_package 展示黄金规则推荐的噬菌体排首位

**LLM验证**：运行 build_evidence_package_from_db 输出三部分 Evidence Package，每个噬菌体标注来源

**跨病例复用**：运行 analyze_and_persist_reuse 和 confirm_knowledge_reuse 展示检测→确认流程

**审计日志**：查询 MATCH (ae:AuditEvent) RETURN ae 查看所有状态变更记录

## **🔑 核心设计原则**

| 原则  | 落地方式 |
| --- | --- |
| **P1: AI 从真实业务开始** | 使用真实历史病例（已去标识化），不使用合成数据 |
| **P2: AI 学习经过验证的知识** | 所有输入数据均经微生物实验室验证，标注验证状态 |
| **P3: AI 放大不替代** | 领域专家对输出做最终评审，LLM 仅做文本组织 |
| **P4: Evidence-driven** | 输出标注证据来源和等级（L1-L5），每条推荐可追溯 |
| **P5: 学习是终点** | 知识策展闭环：新病例 → 新知识 → 更好推荐 |
| **P6: 人工审核不伪造** | 系统从不自动批准升级或确认复用，所有关键决策须经真实专家操作 |

## **🤝 贡献**

本项目为 MVP 验证版本，主要面向内部演示和概念验证。如需扩展或生产部署，请联系项目团队。

## **🔗 相关资源**

- [Neo4j 官方文档](https://neo4j.com/docs/)
- [DeepSeek API 文档](https://api-docs.deepseek.com/)

- [PHIAF 数据集](https://github.com/mengluli-web/PHIAF)

**Phage Intelligence Workspace — 让上一个病例的经验，成为下一个病例的起点。**
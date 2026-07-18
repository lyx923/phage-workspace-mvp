# **Phage Intelligence Workspace - MVP**

**噬菌体精准治疗循证决策支持系统 —— 最小可行产品验证**

## **📖 项目简介**

**Phage Intelligence Workspace** 是一个基于知识图谱和大语言模型的噬菌体精准治疗循证决策支持系统。本项目通过构建噬菌体-宿主互作知识图谱，结合 DeepSeek 大模型的检索增强生成（RAG）能力，为多重耐药菌感染的噬菌体治疗提供**可追溯、可复用的循证证据包**。

### **🎯 核心验证目标**

| **目标** | **说明** | **状态** |
| --- | --- | --- |
| **V1** | Ontology 能否承载真实临床数据？ | ✅ 15 例病例，必填字段填充率 100% |
| **V2** | 历史病例知识能否被复用？ | ✅ 跨病例复用验证通过 |
| **V3** | 学习闭环是否可演示？ | ✅ 完整链路已跑通 |

### **✨ 核心功能**

**知识图谱构建**：基于 Neo4j 存储病原菌、噬菌体、互作关系、临床病例  
**黄金规则管理**：支持导入临床验证的配型规则（如 CRAB KL2 → ΦK2-v3）  
**双引擎推荐**：规则引擎：确定性逻辑，0 成本，0 幻觉  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;LLM 引擎：基于 DeepSeek 的 RAG，生成自然语言证据包  
**知识策展闭环**：病例结局回写 → 证据等级自动升级（L1/L2 → L3）  
**跨病例复用检测**：自动识别相似病例，推荐复用历史经验  

## **📦 数据模型**

### **核心实体**

| **实体** | **说明** | **关键属性** |
| --- | --- | --- |
| **Pathogen** | 病原菌 | species, resistance_mechanism, verification_status |
| **Phage** | 噬菌体 | name, family, receptor_target |
| **PhageHostInteraction** | 噬菌体-宿主互作 | evidence_level(L1-L5), evidence_ref, infection_probability |
| **ClinicalCase** | 临床病例 | case_id, infection_type, phage_treatment, clinical_outcome |
| **KnowledgeRule** | 黄金规则 | rule_id, strain_type, treatment, outcome |

### **证据等级体系**

| **等级** | **名称** | **含义** |
| --- | --- | --- |
| **L1** | PUBLISHED_LITERATURE | 公开文献报道 |
| **L2** | IN_VITRO_VERIFIED | 体外实验验证 |
| **L3** | CLINICAL_SINGLE_CASE | 单例临床验证 |
| **L4** | CLINICAL_MULTI_CENTER | 多中心临床验证 |
| **L5** | ORGANIZATIONAL_LEARNING | 组织学习闭环 |

### **核心关系**

text

(Phage)-\[:HAS_INTERACTION\]->(PhageHostInteraction)-\[:TARGETS\]->(Pathogen)

(ClinicalCase)-\[:INVOLVES_PATHOGEN\]->(Pathogen)

(ClinicalCase)-\[:TREATED_WITH\]->(Phage)

(Pathogen)-\[:HAS_VALIDATED_RULE\]->(KnowledgeRule)-\[:RECOMMENDS_PHAGE\]->(Phage)

## **🏗️ 项目结构**

text  
phage-workspace-mvp/  
├── README.md                     # 项目说明  
├── requirements.txt              # Python 依赖  
├── .env                          # 环境变量（DS_API_KEY 等）  
├── config.py                     # Neo4j + DeepSeek 配置  
├── data/                         # 数据文件  
│   ├── cases.csv                 # 临床病例  
│   └── phage_interactions.csv    # 30 条噬菌体互作记录  
├── src/  
│   ├── data_loader.py            # CSV → Neo4j 数据导入  
│   ├── retriever.py              # Cypher 查询（匹配噬菌体 + 相似病例）  
│   ├── package_builder.py        # Evidence Package 生成（LLM + 规则引擎）  
│   ├── curation.py               # 知识策展（结局回写 + 证据升级）  
│   ├── schema.py                 # 数据库约束和索引创建  
│   └── utils.py                  # 公共工具函数  
├── notebooks/                    # Jupyter Notebook 演示  
│   ├── 01_data_import.ipynb      # 数据导入 + V1 验证  
│   ├── 02_evidence_package.ipynb # Evidence Package 展示  
│   └── 03_cross_case_reuse.ipynb # 跨病例复用 + LLM 验证 ⭐核心  
└── tests/  
    └── manual_checks.md          # 手动验证记录  


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

打开 notebooks/01_data_import.ipynb，按顺序运行所有 Cell：

python

_\# 1. 清空数据库_

clear_database()

_\# 2. 创建约束和索引_

with get_driver() as driver:

create_schema(driver)

_\# 3. 导入噬菌体互作数据_

load_phages_from_csv("../data/phage_interactions.csv")

_\# 4. 导入临床病例数据_

load_cases_from_csv("../data/cases.csv")

## **📊 验证结果**

### **V1：Ontology 可承载数据 ✅**

| 检查项 | 结果  |
| --- | --- |
| 必填字段填充率 | **100%** |
| Pathogen 节点 | 4 个 |
| Phage 节点 | 33 个 |
| PhageHostInteraction 节点 | 30 条 |
| ClinicalCase 节点 | 17 个 |
| KnowledgeRule 节点 | 3 条 |

### **V2：知识可复用 ✅**

用例：CASE-001（大肠杆菌 UTI，噬菌体有效）→ CASE-003（同菌种同感染类型）

结果：系统成功识别相似性，推荐复用相同噬菌体复用类型：direct_reuse

### **V3：学习闭环可演示 ✅**

完整链路已跑通：CASE-001 治疗经验 → 编码为 L3 知识 → CASE-003 检索命中 → 建议复用 → 专家确认

## **📋 演示脚本**

**展示数据库**：MATCH (n) RETURN labels(n), count(\*)4 Pathogen, 33 Phage, 30 PhageHostInteraction, 17 ClinicalCase, 3 KnowledgeRule

**展示黄金规则**：运行 Cell 2（03_cross_case_reuse.ipynb）3 条规则：CRAB KL2 → ΦK2-v3, CRKP KL47 → ΦK47-w7, E. coli O25 → CP-p-EC-23086

**规则引擎推荐**：运行 Cell 4展示黄金规则推荐的噬菌体排首位

**LLM验证**：运行 Cell 5输出三部分 Evidence Package每个噬菌体都标注了证据来源（CASE-XXX / PMID / 黄金规则）

**跨病例复用**：运行 Cell 6展示 reuse_type: "direct_reuse", is_reuse_valid: true

## **🔑 核心设计原则**

| 原则  | 落地方式 |
| --- | --- |
| **P1: AI 从真实业务开始** | 使用真实历史病例（已去标识化），不使用合成数据 |
| **P2: AI 学习经过验证的知识** | 所有输入数据均经微生物实验室验证，标注验证状态 |
| **P3: AI 放大不替代** | 领域专家对输出做最终评审，LLM 仅做文本组织 |
| **P4: Evidence-driven** | 输出标注证据来源和等级（L1-L5），每条推荐可追溯 |
| **P5: 学习是终点** | 知识策展闭环：新病例 → 新知识 → 更好推荐 |

## **🤝 贡献**

本项目为 MVP 验证版本，主要面向内部演示和概念验证。如需扩展或生产部署，请联系项目团队。

## **🔗 相关资源**

- [Neo4j 官方文档](https://neo4j.com/docs/)
- [DeepSeek API 文档](https://api-docs.deepseek.com/)

- [PHIAF 数据集](https://github.com/mengluli-web/PHIAF)

**Phage Intelligence Workspace — 让上一个病例的经验，成为下一个病例的起点。**
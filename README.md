# **Phage Intelligence Workspace - MVP v0.8.0-EXP**

**噬菌体精准治疗 + 竞争情报 + 工程化噬菌体情报  
—— 三域一体的 Ontology 驱动决策智能系统**

# **一、项目简介**

Phage Intelligence Workspace 是一个基于知识图谱和大语言模型的企业级 Ontology 驱动决策智能平台。平台覆盖三个相互连接的领域：

- Scientific Domain：噬菌体-宿主互作、裂解实验、临床病例、证据包
- Competitive Intelligence (CI) Domain：竞争对手、研发项目、情报事件、专利、临床试验
- Engineering Intelligence Domain：工程化噬菌体构建体、工程策略、技术主张、实验结果

共享 Foundation 层（SourceArtifact / Pathogen / Organization / Review / AuditEvent / OntologyModule），并通过 Decision & Learning Layer 将外部情报连接成可追溯、可审核、可学习的组织知识系统。

当前版本为 v0.8.0-EXP，已完成实验集成验证并补齐了基线自动化测试。

## **1.1 核心验证目标**

|     |     |     |
| --- | --- | --- |
| **目标** | **说明** | **状态** |
| V1  | Ontology 能否承载真实临床数据？ | ✅ 16 例病例，必填字段填充率 100% |
| V2  | 历史病例知识能否被复用？ | ✅ 跨病例复用验证通过 |
| V3  | 学习闭环是否可演示？ | ✅ 完整链路已跑通 |
| CI-V1 | 竞争对手情报能否统一映射？ | ✅ 22 组织 / 15 项目 / 22 事件 |
| CI-V2 | 工程化噬菌体策略能否标准化？ | ✅ 5 策略 / 10 构建体 |
| CI-V3 | 跨域决策支持能否闭环？ | ✅ 归因链 2 条完整链路 |

## **1.2 核心能力**

**三域知识图谱**

- 科学域：噬菌体、宿主菌株、裂解实验、临床病例、黄金规则
- CI 域：组织、研发项目、情报事件、专利族、临床试验、竞争评估
- 工程情报域：工程策略、构建体、技术主张、技术结果、技术评估

**Ontology 驱动（Palantir-style）**

- 事实层 / 分析层 / 决策层严格分层
- 所有事实对象 100% 关联 SourceArtifact
- 所有状态变更 100% 写入 AuditEvent
- 所有关键判断须经 Review 审核

**双引擎推荐**

- 规则引擎：确定性逻辑，0 成本，0 幻觉
- LLM 引擎：DeepSeek 仅负责文本组织，不产生未检索事实

**知识策展闭环**

- 病例结局录入 → 自动创建 EvidenceUpgradeProposal
- 专家人工审核（Review） → approved / rejected / needs_revision
- 执行升级 → LysisAssay 证据等级从 L1/L2 升级至 L3

**跨病例复用检测**

- 自动识别相似病例，推荐复用历史经验
- 创建 KnowledgeReuseEvent，需专家确认后才生效

**归因链（Learning Engine）**

SourceArtifact → IntelligenceEvent → IntelligenceProduct → Review → DecisionRecord → IntelligenceUseEvent

# **二、快速开始**

## **2.1 环境要求**

|     |     |
| --- | --- |
| **组件** | **版本要求** |
| Python | 3.11+ |
| Neo4j | 5.x（Community Edition） |
| Redis | 7.x（可选，用于监控缓存） |
| 内存  | ≥ 8GB |

## **2.2 克隆与安装**

git clone https://github.com/lyx923/phage-workspace-mvp.git  
cd phage-workspace-mvp  
pip install -r requirements.txt

## **2.3 启动 Neo4j 与 Redis**

docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \\  
\-e NEO4J_AUTH=neo4j/your-password neo4j:5.26  
<br/>docker run -d --name redis -p 6379:6379 redis:7-alpine

## **2.4 配置环境变量**

复制项目根目录的 .env.example 为 .env，并按实际情况填写。注意：DeepSeek 的变量名以 DS_ 开头，Redis 连接使用 REDIS_HOST 和 REDIS_PORT。

cp .env.example .env

## **2.5 初始化数据与验收测试**

\# 初始化沙箱数据  
python scripts/setup_all_stage2.py  
<br/>\# 运行基础断言测试（确保代码环境正常）  
python -m pytest tests/test_v08_acceptance.py -v

## **2.6 启动前端**

python app.py

默认前端运行在 http://localhost:8501。Dash 默认端口为 8050，本仓库 app.py 固定 8501，如需改端口请同步修改 config.py 中的 PORT。

# **三、项目结构**

下方目录树反映当前仓库真实状态：

phage-workspace-mvp/  
├── app.py # Dash 应用入口  
├── auth.py # 认证模块（verify_user / session）  
├── config.py # 环境变量读取  
├── requirements.txt # 主依赖  
├── README.md  
├── components/  
│ ├── navbar.py  
│ ├── sidebar.py  
│ ├── confirm_dialog.py  
│ └── kpi_card.py  
├── data_access/  
│ ├── queries.py # 只读 Cypher 集中层  
│ ├── mutations.py # 写入层（走 src/ 服务）  
│ └── audit.py # AuditEvent 统一写入  
├── pages/  
│ ├── dashboard.py  
│ ├── ai_assistant.py  
│ ├── knowledge_graph.py  
│ ├── login.py  
│ ├── admin/ # 包含 schema.py, data_import.py, experiment_batch.py 等  
│ ├── ci/ # 包含 events.py, programs.py, strategies.py 等  
│ └── scientific/ # 包含 enzyme_gene.py, biofilm_assay.py, lysis_assay.py 等  
├── scripts/  
│ ├── generate_ontology_docs.py # R-02 生成本体文档  
│ ├── verify_requirements.py # R-05 验证依赖版本  
│ ├── separate_legacy_deps.py # R-08 归档依赖分离  
│ └── monitor_runner.py # 情报抓取脚本  
├── src/ # 后端服务层（包含 foundation/, scientific/, ci/ 等）  
├── tests/ # 验收脚本  
│ ├── test_v08_acceptance.py # R-07 断言起点  
│ └── acceptance_stage2.py # 原验收脚本（改造中）  
├── docs/  
│ ├── ontology_schema.md # 自动生成的本体文档  
│ └── planned_nodes.md # 规划中 / 已废弃节点与关系说明  
└── \_legacy_streamlit/ # 已归档，不参与主应用运行

# **四、核心设计原则**

|     |     |
| --- | --- |
| **原则** | **落地方式** |
| P1: AI 从真实业务开始 | 使用真实历史病例（已去标识化），不使用合成数据 |
| P2: AI 学习经过验证的知识 | 所有输入数据均经微生物实验室验证 |
| P3: AI 放大不替代 | 领域专家对输出做最终评审，LLM 仅做文本组织 |
| P4: Evidence-driven | 输出标注证据来源和等级（L1-L5），每条推荐可追溯 |
| P5: 学习是终点 | 知识策展闭环：新病例 → 新知识 → 更好推荐 |
| P6: 人工审核不伪造 | 系统从不自动批准升级或确认复用 |
| P7: 事实/分析/决策分层 | 不允许 AI 幻觉污染事实层 |
| P8: 归因链纯净 | 单 Brief 的归因链中事件必须属于同组织 |
| P9: 时间语义 | 所有对象带 valid_from，Brief 必带 as_of_date |
| P10: 来源可信度 ≠ 内容正确性 | 来源评级与事实置信度分开记录 |

# **五、技术栈**

|     |     |
| --- | --- |
| **层** | **技术** |
| 数据存储 | Neo4j 5.x + Redis 7.x |
| LLM | DeepSeek Chat（OpenAI 兼容 SDK） |
| 后端  | Python 3.11+ |
| 前端（当前） | Dash 2.17+ + dash-bootstrap-components + dash-ag-grid + dash-cytoscape + Plotly |
| 前端（归档） | Streamlit（已归档至 \_legacy_streamlit/，不参与主应用运行） |
| 数据处理 | pandas / numpy / scikit-learn |
| Notebook | Jupyter |

# **六、版本历史**

|     |     |     |
| --- | --- | --- |
| **版本** | **日期** | **主要变更** |
| v0.1 | —   | 早期 MVP 初版 |
| v0.2 | —   | 沙箱版 / CI 增补 PRD |
| v0.4 | —   | Enterprise Ontology Foundation 设计 |
| v0.5 | 2026-08-24 | CI Demo 修复；Learning Engine 闭环目标 |
| v0.6 | 2026-08-31 | 修复 v0.5 验收遗留问题；AuditEvent/OntologyModule 强制完成；消除归因链语义污染 |
| v0.7 | 2026-09-19 | 实验集成验证迭代（工程化噬菌体、酶基因、生物膜、实验批次） |
| v0.8 | 2026-10-14 | 基线修复（依赖澄清、本体文档生成、pytest 断言、Schema 清理） |

**Phage Intelligence Workspace — 让上一个病例的经验，成为下一个病例的起点；让外部情报，成为内部决策的依据。**
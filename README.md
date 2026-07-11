**Phage Intelligence Workspace — MVP PRD V3.0**

**沙箱精简版 | 1.5人×4周 | 开发专用**

版本：V3.0-lightweight  
用途：开发人员理解需求、设计业务流程与架构  
约束：1.5人（1全职开发 + 0.5领域专家）× 4周  
LLM：DeepSeek（DS）  
核心原则：**砍到骨头，只验证一件事——Learning Engine 的核心假设能否成立**

**目录**

一、产品定义  
二、核心验证目标  
三、前置条件  
四、用户与角色  
五、功能需求  
六、Ontology 设计  
七、技术架构  
八、数据流  
九、验收标准  
十、4周开发计划  
十一、交付物清单  
十二、边界声明  
十三、附录：术语对照

**一、产品定义**

**1.1 一句话**

**Phage Intelligence Workspace 沙箱 MVP 是 Learning Engine 核心假设的最小技术验证器：在 4 周内，用 15 个历史 CRAB 病例 + 精选文献知识，证明"上一份病例的经验可以被编码、被检索、被复用"。**

**1.2 产品层次**

| **层级** | **名称** | **说明** |
| --- | --- | --- |
| Platform（平台） | Learning-driven Precision Infection Platform | 未来  |
| Workspace（产品） | Phage Intelligence Workspace | 本 MVP 的产品层 |
| Copilot（MVP 能力） | Evidence-driven Phage Matching Copilot | 本 MVP 的能力模块 |

📄 三层命名来源：最新 MVP 章节描述。

**1.3 产品不是 / 产品是**

| **不是** | **是** |
| --- | --- |
| AI 医生 / 自动诊断 / 医疗大模型 | 循证智能助手 |
| 医院生产系统 | 实验室沙箱中的技术验证器 |
| 完整 Evidence Package 系统 | 最小可行检索 + 组织 + 输出管线 |
| 50 病例的完整验证 | 15 病例的聚焦验证 |

📄 "不是/是"定义来源：最新 MVP 章节原文。

**1.4 设计原则**

| **#** | **原则** | **📄 来源** | **4 周落地约束** |
| --- | --- | --- | --- |
| P1  | AI 从真实业务开始 | V4.0 1.2 节 | 使用真实历史病例（已去标识化），不使用合成数据 |
| P2  | AI 学习经过验证的知识 | V4.0 1.2 节 | 所有输入数据均经微生物实验室验证，Ontology 实例标注验证状态 |
| P3  | AI 放大不替代 | V4.0 1.2 节 | 领域专家对输出做最终评审，LLM 仅做检索和文本组织 |
| P4  | Evidence-driven | 最新 MVP 章节 | 输出标注证据来源和等级（L1-L5），每条推荐可追溯 |
| P5  | Copilot 不是终点，Learning 是终点 | 最新 MVP 章节 | **本次唯一必须验证的假设** |

**二、核心验证目标**

**2.1 唯一必验命题**

**"上一个 CRAB 病例的噬菌体配型经验，能否在下一个相似 CRAB 病例中被检索到、并被领域专家判断为'有用的参考'？"**

**2.2 验证目标（三项）**

| **ID** | **验证目标** | **4 周可测算法** | **通过标准** |
| --- | --- | --- | --- |
| **V1** | Ontology 能否承载真实数据？ | 15 例病例导入，必填字段填充率统计 | ≥ 90% |
| **V2** | 知识能否被复用？ | 领域专家逐条判断"病例 B 的 Evidence Package 中引用病例 A 的信息是否有效" | ≥ 2 个有效实例 |
| **V3** | Learning 闭环是否可演示？ | 1 条完整链路：病例A → 知识编码 → 病例B检索命中 → 专家确认改善 | 1 条可演示链路 |

⚠️ 原五大验证目标（来源：最新 MVP 章节）中的 Workflow Validation 和 Capability Amplification 在 4 周沙箱中不做验证。Workflow Validation 需要医院生产环境，Capability Amplification 需要多轮迭代数据，均不可在 4 周沙箱中测量。

**2.3 验证目标与 BP 的对应**

| **PRD 验证目标** | **📄 BP 对应概念** | **出处** |
| --- | --- | --- |
| V1（Ontology 承载数据） | "知识策展：将原始数据转化为经过验证的知识" | V4.0 第 508-510 行 |
| V2（知识复用） | "历史知识是否能够持续被下一次病例调用" | 最新 MVP 章节 KV-3 |
| V3（学习闭环） | "Learning Flywheel：新病例 → 新知识 → 更好 Copilot" | 最新 MVP 章节 KV-5 |

**三、前置条件**

⛔ 以下条件必须在 Day 0 之前满足。如不满足，4 周计划无法启动。

| **#** | **前置条件** | **状态** | **负责人** |
| --- | --- | --- | --- |
| PC-1 | 合作医院已批准的去标识化 CRAB 历史病例数据（≥ 15 例）已获取 | ☐   | 项目发起人 |
| PC-2 | 病例数据包含以下字段：菌种鉴定、耐药谱（耐药机制 + 耐药基因）、标本类型、感染诊断、治疗方案（如已治疗）、临床结局（如已知） | ☐   | 项目发起人 |
| PC-3 | 领域专家（微生物/噬菌体/感染科方向，1 人）已确认可投入约 8 天（分散在 4 周内） | ☐   | 项目发起人 |
| PC-4 | 开发环境就绪：1 台机器（内存 ≥ 16GB，可运行 Neo4j + Python + DeepSeek API 调用），操作系统 Linux/macOS/Windows 均可 | ☐   | 开发人员 |

📄 PC-2 病例字段要求依据：V4.0 第 148-149 行描述的临床数据维度（菌种、耐药机制、标本类型），以及 V4.0 第 17-18 行"经过验证的知识"的定义。

**四、用户与角色**

| **角色** | **在 4 周中的职责** | **投入量** |
| --- | --- | --- |
| **开发人员**（1 人，全职） | 环境搭建、Ontology schema 实现、数据导入脚本、图数据库搭建、检索逻辑开发、Evidence Package 生成管线、验证报告撰写 | 4 周 × 5 天 = 20 人天 |
| **领域专家**（1 人，0.5 兼职） | Ontology schema 审核、知识策展质量抽检、Evidence Package 评审打分、跨病例复用有效性判断 | 约 8 天（分散在 4 周内） |

**五、功能需求**

**5.1 优先级定义**

| **优先级** | **含义** | **不交付时的后果** |
| --- | --- | --- |
| **P0** | 必须交付。不交付 = MVP 失败 | V1/V2/V3 中至少一项无法验证 |
| **P1** | 应该交付。不交付 = 验证质量下降但不致命 | 演示效果打折扣，但不影响核心验证 |
| **P2** | 锦上添花 | 可降级为手工操作 |

**5.2 功能清单**

| **ID** | **功能** | **优先级** | **说明** | **预计工作量** |
| --- | --- | --- | --- | --- |
| FR-1 | 历史病例 CSV 导入 | P0  | 读取 CSV 文件，字段映射到 Ontology schema，写入 Neo4j 图数据库。含数据验证（必填字段检查、枚举值校验） | 1 天 |
| FR-2 | 文献知识手动导入 | P0  | 精选 30-50 条 CRAB 噬菌体-宿主互作关系（人工从 PubMed 文献中提取），通过脚本批量写入 Neo4j | 1 天 |
| FR-3 | 图数据库查询 API | P0  | 输入：病原菌 species + resistance_mechanism；输出：匹配的 PhageHostInteraction 列表 + 相似 ClinicalCase 列表。基于 Cypher 实现 | 2 天 |
| FR-4 | Evidence Package 生成 | P0  | 调用 DeepSeek API 将 FR-3 的查询结果组织为结构化的 Evidence Package（三部分）。LLM 仅做文本组织，不做推理 | 2 天 |
| FR-5 | 知识策展录入 | P0  | 单个病例的治疗 + 结局信息手动/半自动编码为 Ontology 实例（更新 ClinicalCase 节点 + 升级 PhageHostInteraction 证据等级） | 1 天 |
| FR-6 | Jupyter Notebook 交互界面 | P1  | 选择一个病例 → 点击"生成 Evidence Package"→ 展示三部分结果。包含领域专家评分的录入区域 | 1.5 天 |
| FR-7 | 跨病例复用检测脚本 | P1  | 输入病例 A 和病例 B，自动检测病例 B 的 Evidence Package 中是否引用了病例 A 的知识，标记引用类型 | 1 天 |
| FR-8 | Neo4j Browser 内置可视化 | P2  | 直接使用 Neo4j Browser 自带功能，无需额外开发 | 0 天 |

**5.3 Evidence Package 结构（三部分）**

📄 原始架构为五部分（来源：最新 MVP 章节）：① Candidate Phage、② Matching Evidence、③ Clinical Evidence、④ Literature Evidence、⑤ Explanation。  
4 周版将 Candidate Phage 并入 Matching Evidence，Literature Evidence 融入 Matching Evidence 和 Explanation 中，保留三部分：

| **部分** | **内容** | **数据来源** |
| --- | --- | --- |
| **Matching Evidence** | 候选噬菌体列表（名称、家族、受体靶点）+ 匹配依据（感染结果/概率）+ 证据等级 + 文献引用 | Phage + PhageHostInteraction 节点 |
| **Clinical Evidence** | 相似历史病例摘要（病例编号、感染类型、耐药谱、治疗方案、临床结局） | ClinicalCase 节点 |
| **Explanation** | 推荐理由概述、风险提示、缺失信息标注、当前知识局限说明、证据等级总结 | DeepSeek 基于以上两部分生成 |

**5.4 证据等级体系**

**TEXT**

EVIDENCE_LEVEL:

L1 — PUBLISHED_LITERATURE 公开文献中的噬菌体-宿主互作结论

L2 — IN_VITRO_VERIFIED 体外实验已验证感染活性

L3 — CLINICAL_SINGLE_CASE 单例临床使用验证

L4 — CLINICAL_MULTI_CENTER 多中心临床验证

L5 — ORGANIZATIONAL_LEARNING 已进入学习闭环（多次复用 + 结果一致）

📄 证据等级体系依据：V4.0 第 17-18 行"经过验证的知识"定义、第 168-177 行"知识策展"概念。具体等级命名（L1-L5）为 🔮 推断，基于 BP 中描述的从文献→体外→临床→多中心→组织学习的递进验证链。

**5.5 不做的功能（边界明确声明）**

| **不做** | **原因** |
| --- | --- |
| Literature Agent 自动扫描 PubMed | 4 周内手动精选 30-50 条更可控、质量更高、zero 幻觉风险 |
| LIS / HL7 / FHIR 对接 | 沙箱不接医院系统，CSV 导入即可 |
| 向量检索（RAG / Embedding） | 图查询已覆盖核心检索需求。向量检索是 M1 优化项 |
| React 前端 | Jupyter Notebook 足够用于演示和评审 |
| 用户权限 / 认证系统 | 沙箱单用户环境 |
| 自动化测试套件 | 4 周内手动验证 + 领域专家评审 |
| CRAB 以外的病原菌 | V4.0 第 213 行明确 CRAB 为首期优先级 |
| 知识版本管理系统 | 通过 evidence_level 字段升级手动管理 |
| 治疗建议 / 自动决策 | 违反 P3（AI 不替代人）和 P4（Evidence-driven） |

**六、Ontology 设计**

**6.1 设计策略**

轻 Ontology：4 实体 + 核心关系 + Property Graph（Neo4j）。无 OWL。无自动推理。

📄 设计策略依据：此前 Ontology 引入 MVP 的可行性分析结论——"MVP 做轻 Ontology，不做 OWL 推理层"。

**6.2 实体定义**

**Pathogen（病原菌）**

| **属性** | **类型** | **必填** | **说明** | **示例值** |
| --- | --- | --- | --- | --- |
| pathogen_id | String | ✅   | 唯一标识 | PATH-001 |
| species | String | ✅   | 菌种名称 | Acinetobacter baumannii |
| resistance_mechanism | String | ✅   | 耐药机制（大类） | Carbapenem-resistant |
| resistance_genes | List\[String\] | ✅   | 具体耐药基因 | \["OXA-23", "TEM-1"\] |
| ST_type | String | 否   | MLST 分型 | ST2 |
| verification_status | String | ✅   | 验证状态 | MICROBIOLOGY_LAB_VERIFIED |

**Phage（噬菌体）**

| **属性** | **类型** | **必填** | **说明** | **示例值** |
| --- | --- | --- | --- | --- |
| phage_id | String | ✅   | 唯一标识 | PHAGE-001 |
| name | String | ✅   | 噬菌体名称 | vB_AbaM_AbTZI |
| family | String | 否   | 分类科属 | Myoviridae |
| receptor_target | String | 否   | 靶向受体 | Capsular polysaccharide |
| lifecycle | String | 否   | 生命周期 | Lytic |
| safety_flags | List\[String\] | 否   | 安全标记 | \["no_toxin_genes", "no_integrase"\] |
| genome_accession | String | 否   | GenBank 登录号 | NC_048XXX |

**PhageHostInteraction（噬菌体-宿主互作）**

| **属性** | **类型** | **必填** | **说明** | **示例值** |
| --- | --- | --- | --- | --- |
| interaction_id | String | ✅   | 唯一标识 | PHI-001 |
| phage_id | String | ✅   | 关联 Phage | PHAGE-001 |
| pathogen_id | String | ✅   | 关联 Pathogen | PATH-001 |
| infection_result | String | 否   | 感染结果 | Lytic / No infection / Partial |
| infection_probability | Float | 否   | 感染概率（0-1） | 0.94 |
| evidence_level | Enum | ✅   | L1-L5 | L2  |
| evidence_ref | List\[String\] | 否   | 证据来源（PMID / CaseID） | \["PMID:12345678"\] |
| notes | String | 否   | 备注信息 | —   |

**ClinicalCase（临床病例）**

| **属性** | **类型** | **必填** | **说明** | **示例值** |
| --- | --- | --- | --- | --- |
| case_id | String | ✅   | 唯一标识（去标识化编号） | CASE-001 |
| pathogen_id | String | ✅   | 关联 Pathogen | PATH-001 |
| infection_type | String | ✅   | 感染类型 | VAP |
| infection_site | String | ✅   | 感染部位 | Lung |
| specimen_type | String | ✅   | 标本类型 | BALF |
| patient_age_group | String | 否   | 年龄段 | 55-65 |
| comorbidities | List\[String\] | 否   | 基础疾病 | \["COPD", "DM"\] |
| prior_antibiotics | List\[String\] | 否   | 既往抗生素 | \["Meropenem", "Colistin"\] |
| phage_treatment | String | 否   | 噬菌体治疗方案（如有） | Cocktail: φA+φB, 雾化吸入 |
| clinical_outcome | String | 否   | 临床结局（如有） | Clinical improvement at Day 7 |
| microbiological_outcome | String | 否   | 微生物学结局 | 菌量下降3log |
| curated_by | String | 否   | 策展人标识 | FDE-01 |
| curation_date | Date | 否   | 策展日期 | 2026-08-15 |

**6.3 核心关系**

Neo4j 中的关系类型：

**TEXT**

(Phage)-\[:HAS_INTERACTION\]->(PhageHostInteraction)-\[:TARGETS\]->(Pathogen)

(ClinicalCase)-\[:INVOLVES_PATHOGEN\]->(Pathogen)

(ClinicalCase)-\[:TREATED_WITH\]->(Phage)

语义说明：

| **关系** | **方向** | **含义** |
| --- | --- | --- |
| HAS_INTERACTION | Phage → PhageHostInteraction | 噬菌体具有一条互作记录 |
| TARGETS | PhageHostInteraction → Pathogen | 该互作记录针对某病原菌 |
| INVOLVES_PATHOGEN | ClinicalCase → Pathogen | 病例涉及某病原菌感染 |
| TREATED_WITH | ClinicalCase → Phage | 病例使用了某噬菌体治疗 |

**6.4 设计简化说明**

以下实体/关系在 4 周版中不建独立节点，属性并入其他实体：

| **原设计** | **4 周版处理** |
| --- | --- |
| Specimen（标本） | 属性（specimen_type）并入 ClinicalCase |
| LiteratureEvidence（文献证据） | 属性（evidence_ref）并入 PhageHostInteraction |
| PhageTreatment（治疗事件） | 属性（phage_treatment）并入 ClinicalCase |
| TreatmentOutcome（治疗结局） | 属性（clinical_outcome, microbiological_outcome）并入 ClinicalCase |

**七、技术架构**

**7.1 技术栈**

| **层** | **选型** | **原因** |
| --- | --- | --- |
| 图数据库 | Neo4j Community Edition 5.x | 最成熟；Cypher 查询直观；Neo4j Browser 内置可视化（FR-8 零成本） |
| 后端语言 | Python 3.11+ | 开发效率最高；LLM SDK 生态最好 |
| 图数据库驱动 | neo4j（官方 Python driver） | 官方维护，文档完善 |
| LLM | DeepSeek（DS）API | 📄 V4.0 第 166 行原则：LLM 可替换。选择 DS 基于成本、速度和中文能力 |
| 数据导入 | pandas + neo4j driver | CSV → DataFrame → Cypher batch insert |
| 交互界面 | Jupyter Notebook（P0）/ Streamlit（P1 备选） | 零前端成本，开发人员直接操作 |
| 环境管理 | venv | 最轻量 |
| 版本控制 | Git | —   |

**7.2 架构图**

**TEXT**

┌─────────────────────────────────────────────┐

│ Jupyter Notebook │ ← 交互层

│ （病例选择 → 生成Evidence Package → 展示 → │

│ 领域专家评分录入） │

└──────────────────┬──────────────────────────┘

│ Python 调用

┌──────────────────▼──────────────────────────┐

│ Copilot Engine（Python） │ ← 业务逻辑层

│ │

│ ┌───────────────┐ ┌───────────────────┐ │

│ │ Retriever │ │ Package Builder │ │

│ │ (Cypher查询) │ │ (DeepSeek组织文本)│ │

│ └───────┬───────┘ └────────┬──────────┘ │

│ │ │ │

└──────────┼───────────────────┼───────────────┘

│ │

┌──────────▼───────────────────▼───────────────┐

│ Data Layer │ ← 数据层

│ │

│ ┌──────────────┐ ┌───────────────────┐ │

│ │ Neo4j │ │ 文件系统 │ │

│ │ (Knowledge │ │ (CSV病例数据 │ │

│ │ Layer) │ │ 导入日志/配置) │ │

│ └──────────────┘ └───────────────────┘ │

│ │

└──────────────────────────────────────────────┘

│

│ HTTPS API Call

┌──────────▼──────────────────────────────────┐

│ DeepSeek API │ ← LLM层

│ 输入：检索到的匹配证据 + 历史病例摘要 │

│ 输出：结构化的 Evidence Package（JSON） │

│ ⚠️ LLM 不存储知识，不记忆，仅做文本组织 │

└──────────────────────────────────────────────┘

**7.3 核心模块**

项目目录结构：

**TEXT**

phage-workspace-mvp/

├── README.md

├── requirements.txt

├── .env # DS_API_KEY 等配置

├── config.py # 数据库连接、LLM 配置

├── data/

│ ├── cases.csv # 15例历史病例

│ └── phage_interactions.csv # 精选文献知识

├── src/

│ ├── data_loader.py # FR-1, FR-2: CSV → Neo4j

│ ├── retriever.py # FR-3: Cypher 查询

│ ├── package_builder.py # FR-4: Evidence Package 生成

│ ├── curation.py # FR-5: 知识策展（回写）

│ └── utils.py # 公共工具函数

├── notebooks/

│ ├── 01_data_import.ipynb # 数据导入演示

│ ├── 02_evidence_package.ipynb # FR-6: 交互界面

│ └── 03_cross_case_reuse.ipynb # FR-7: 跨病例复用检测

└── tests/

└── manual_checks.md # 手动验证记录

**7.4 模块接口定义**

**data_loader.py**

**TEXT**

load_cases_from_csv(csv_path: str) -> list\[dict\]

读取病例 CSV，验证必填字段，返回病例字典列表。

验证规则：species/resistance_mechanism/infection_type/

infection_site/specimen_type 非空。

insert_pathogen(driver, pathogen_data: dict) -> str

插入 Pathogen 节点，返回 pathogen_id。已存在则更新。

insert_clinical_case(driver, case_data: dict) -> str

插入 ClinicalCase 节点，建立 INVOLVES_PATHOGEN 关系。

返回 case_id。

batch_insert_phage_interactions(driver, csv_path: str) -> int

批量插入 Phage + PhageHostInteraction 节点和关系。

返回插入的 PhageHostInteraction 数量。

**retriever.py**

**TEXT**

find_matching_phages(

driver,

pathogen_species: str,

resistance: str

) -> list\[dict\]

查询匹配该病原菌的所有噬菌体互作关系。

返回按 evidence_level DESC, infection_probability DESC 排序。

Cypher：MATCH (ph:Phage)-\[:HAS_INTERACTION\]->(phi:PhageHostInteraction)

\-\[:TARGETS\]->(p:Pathogen)

WHERE p.species = $species

AND p.resistance_mechanism = $resistance

RETURN ph.\*, phi.\*

find_similar_cases(

driver,

pathogen_species: str,

infection_type: str,

limit: int = 5

) -> list\[dict\]

查询相同病原菌 + 相同感染类型的历史病例。

Cypher：MATCH (c:ClinicalCase)-\[:INVOLVES_PATHOGEN\]->(p:Pathogen)

WHERE p.species = $species

AND c.infection_type = $infection_type

OPTIONAL MATCH (c)-\[:TREATED_WITH\]->(ph:Phage)

RETURN c.\*, collect(ph.name) as phages_used

ORDER BY c.case_id DESC

**package_builder.py**

**TEXT**

build_evidence_package(

matching_phages: list\[dict\],

similar_cases: list\[dict\],

query_context: dict # {species, resistance, infection_type, ...}

) -> dict

调用 DeepSeek API 组织输出。

返回格式：

{

"matching_evidence": \[

{

"phage_name": "vB_AbaM_AbTZI",

"family": "Myoviridae",

"infection_result": "Lytic",

"infection_probability": 0.94,

"evidence_level": "L2",

"evidence_ref": \["PMID:12345678"\],

"notes": "靶向CPS受体"

},

...

\],

"clinical_evidence": \[

{

"case_id": "CASE-003",

"infection_type": "VAP",

"phage_treatment": "Cocktail: φA+φB, 雾化",

"clinical_outcome": "Day 7 临床改善",

"microbiological_outcome": "菌量下降3log"

},

...

\],

"explanation": "基于以上匹配证据，本次查询共检索到..."

}

**curation.py**

**TEXT**

curate_case_outcome(

driver,

case_id: str,

treatment: dict, # {phage_ids, route, cocktail_name}

outcome: dict # {clinical_outcome, microbiological_outcome}

) -> str

更新 ClinicalCase 的治疗和结局字段。

如果该病例使用的噬菌体有对应的 PhageHostInteraction，

将其 evidence_level 从 L1/L2 升级为 L3（CLINICAL_SINGLE_CASE）。

返回更新摘要。

**7.5 DeepSeek API 调用规范**

**TEXT**

模型：deepseek-chat（或最新可用版本）

调用方式：OpenAI 兼容 SDK（deepseek 官方 Python SDK）

最大 token：4096

Temperature：0.3（低温度确保输出稳定、可复现）

Prompt 设计约束（对应原则 P2、P4）：

\- 禁止 LLM 凭空编造噬菌体或临床结果

\- 所有输出必须引用输入的检索结果

\- 无法确定的内容标注"未知"或"请人工判断"

\- 不做治疗推荐，只组织证据

System Prompt 示例：

"你是一个精准抗感染领域的循证助手。

你的职责是组织已有的检索结果，不是创造新知识。

你只使用下面提供的检索结果，不添加任何未在检索结果中出现的信息。

对于缺失的信息，标注'需人工进一步确认'。

不做治疗推荐。

输出严格的 JSON 格式。"

**八、数据流**

**8.1 端到端流程**

**TEXT**

┌──────────────────────────────────────────────────────┐

│ 沙箱环境（单机） │

│ │

│ Phase 1: 数据导入（Week 1-2） │

│ ┌───────────┐ ┌───────────────┐ │

│ │ cases.csv │ │ interactions │ │

│ │ (15例CRAB) │ │ .csv (精选30- │ │

│ │ │ │ 50条文献知识) │ │

│ └─────┬─────┘ └───────┬───────┘ │

│ │ │ │

│ └──────────┬──────────┘ │

│ ▼ │

│ Phase 2: Knowledge Layer 构建（Week 2） │

│ ┌───────────────────────────────┐ │

│ │ data_loader.py │ │

│ │ → 字段验证 → Ontology 映射 │ │

│ │ → Cypher batch insert │ │

│ └───────────────┬───────────────┘ │

│ ▼ │

│ ┌───────────────────────────────┐ │

│ │ Neo4j 图数据库 │ │

│ │ Pathogen: 15 节点 │ │

│ │ Phage: ~50 节点 │ │

│ │ PhageHostInteraction: ~80 节点 │ │

│ │ ClinicalCase: 15 节点 │ │

│ └───────────────┬───────────────┘ │

│ ▼ │

│ Phase 3: Copilot Engine 运行（Week 3） │

│ ┌───────────────────────────────┐ │

│ │ retriever.py │ │

│ │ → Cypher 查询匹配噬菌体 │ │

│ │ → Cypher 查询相似病例 │ │

│ ├───────────────────────────────┤ │

│ │ package_builder.py │ │

│ │ → DeepSeek API 组织输出 │ │

│ │ → Evidence Package (JSON) │ │

│ └───────────────┬───────────────┘ │

│ ▼ │

│ Phase 4: 评审与回写（Week 3-4） │

│ ┌───────────────────────────────┐ │

│ │ Jupyter Notebook │ │

│ │ → 选择病例 → 查看输出 → 评分 │ │

│ └───────────────┬───────────────┘ │

│ ▼ │

│ ┌───────────────────────────────┐ │

│ │ curation.py │ │

│ │ → 病例结局回写 │ │

│ │ → 证据等级升级（L1/L2→L3） │ │

│ └───────────────────────────────┘ │

│ │

└──────────────────────────────────────────────────────┘

**8.2 关键场景：跨病例知识复用（V2/V3 验证核心）**

**TEXT**

前置状态：

\- 所有 15 例病例已导入 Knowledge Layer

\- 病例 CASE-001 ~ CASE-008 的治疗结局已通过 curation.py 回写

\- 涉及 8 个 PhageHostInteraction 升级为 L3（单例临床验证）

步骤 1：取出一个未策展的病例（CASE-009，CRAB VAP）

→ 运行 retriever.find_matching_phages("Acinetobacter baumannii", "Carbapenem-resistant")

→ 返回 12 条 PhageHostInteraction（其中 3 条为 L3，来自 CASE-001/004/007 的回写）

步骤 2：运行 retriever.find_similar_cases("Acinetobacter baumannii", "VAP")

→ 返回 7 个相似病例（其中 CASE-001/004/007 有完整治疗+结局数据）

步骤 3：运行 package_builder.build_evidence_package(...)

→ Evidence Package 的 Clinical Evidence 部分包含 CASE-001/004/007

→ Evidence Package 的 Matching Evidence 中 3 条 L3 条目标注来源为 CASE-001/004/007

步骤 4：领域专家评审

→ 判断：CASE-001 的治疗结果（Cocktail A 有效）对 CASE-009 的配型是否有参考价值？

→ 如判断"是" → 1 个有效跨病例复用实例（V2 计数 +1）

步骤 5：回写 CASE-009 的治疗结局（假设已知）

→ curation.py 将 CASE-009 使用的噬菌体对应的 PhageHostInteraction 从 L2→L3

→ 完成一条 Learning Flywheel 链路：CASE-001 → ... → CASE-009 受益 → CASE-009 又贡献新知识

→ 此链路可作为 V3 演示

**8.3 核心 Cypher 查询（开发用参考）**

查询匹配的噬菌体：

**CYPHER**

MATCH (ph:Phage)-\[:HAS_INTERACTION\]->(phi:PhageHostInteraction)-\[:TARGETS\]->(p:Pathogen)

WHERE p.species = $species

AND p.resistance_mechanism = $resistance

RETURN ph.phage_id, ph.name, ph.family, ph.receptor_target,

phi.interaction_id, phi.infection_result, phi.infection_probability,

phi.evidence_level, phi.evidence_ref, phi.notes

ORDER BY phi.evidence_level DESC, phi.infection_probability DESC

查询相似病例：

**CYPHER**

MATCH (c:ClinicalCase)-\[:INVOLVES_PATHOGEN\]->(p:Pathogen)

WHERE p.species = $species

AND c.infection_type = $infection_type

OPTIONAL MATCH (c)-\[:TREATED_WITH\]->(ph:Phage)

RETURN c.case_id, c.infection_type, c.infection_site,

c.prior_antibiotics, c.phage_treatment,

c.clinical_outcome, c.microbiological_outcome,

collect(ph.name) AS phages_used

ORDER BY c.case_id DESC

LIMIT $limit

**九、验收标准**

**9.1 三项核心指标**

| **验证目标** | **测量方法** | **通过标准** | **未通过时的处理** |
| --- | --- | --- | --- |
| **V1: Ontology 可承载数据** | 15 例病例导入后，统计必填字段（species, resistance_mechanism, infection_type, infection_site, specimen_type, verification_status, 及各 ID 字段）共约 10 个必填字段 × 15 病例 = 150 个值，统计缺失数量 | 缺失 ≤ 15 个（≥ 90% 填充率） | 检查缺失分布。若集中在某字段 → 该字段可能不是真正的必填项，修改 schema；若分散 → 数据质量问题，与数据提供方沟通 |
| **V2: 知识可复用** | 领域专家逐条审查病例 B 的 Evidence Package 中引用病例 A 的信息，给出"有效/部分有效/无效"判断 | ≥ 2 个"有效"实例 | ① 病例间相似度不够 → 从 15 例中选择更相似的子集重测；② 检索逻辑未命中 → 调整 Cypher 查询条件（如放宽 infection_type 匹配）；③ 知识编码不完整 → 检查 curation.py 回写逻辑 |
| **V3: 闭环可演示** | 存在可追溯的链路：病例A 的治疗结局 → curation.py 写入 → 病例B 的包生成器检索到 → DeepSeek 组织进 Explanation → 领域专家确认"病例A 的经验改善了病例B 的证据包" | 1 条完整可演示链路 | 若 V2 通过但 V3 不通过（有复用但无完整闭环），检查是否缺少"病例A 结局改善病例B 建议"的明确步骤。可能需要重新组织演示脚本，或在 Explanation 中显式标注跨病例引用来源。 |

**9.2 功能验收清单**

| **功能** | **验收方式** | **通过标准** |
| --- | --- | --- |
| FR-1 病例导入 | 执行 src/data_loader.py，在 Neo4j Browser 中检查节点数 | Pathogen ≥ 15, ClinicalCase ≥ 15 |
| FR-2 文献知识导入 | 执行导入脚本，在 Neo4j Browser 中检查 PhageHostInteraction 节点数 | PhageHostInteraction ≥ 30（其中 evidence_level 为 L1/L2 的 ≥ 20） |
| FR-3 图查询 | 在 Jupyter Notebook 中给定已知 CRAB 参数，调用 retriever 函数 | 返回 ≥ 1 个 Phage 匹配结果，返回 ≥ 1 个相似病例 |
| FR-4 Evidence Package | 调用 build_evidence_package，检查返回的 dict | 包含三部分（matching_evidence, clinical_evidence, explanation），每部分非空 |
| FR-5 知识策展 | 调用 curation.curate_case_outcome 更新一个病例，再查询确认 | Neo4j 中该病例的 clinical_outcome 字段已更新，相关 PhageHostInteraction 的 evidence_level 已升级 |
| FR-6 交互界面 | 在 02_evidence_package.ipynb 中选择病例，依次运行所有 Cell | 从选择到展示完成 ≤ 2 分钟，中间不需要手动修改代码 |
| FR-7 跨病例复用 | 运行 03_cross_case_reuse.ipynb，输入病例 A 和病例 B | 自动检测并标注引用类型，输出可读的报告 |

**9.3 最终演示脚本（给投资人的 5 分钟演示）**

**TEXT**

1\. 打开 Neo4j Browser

→ 运行 MATCH (n) RETURN labels(n), count(\*)

→ 展示：15 Pathogen, ~50 Phage, ~80 PhageHostInteraction, 15 ClinicalCase

2\. 打开 02_evidence_package.ipynb

→ Cell 1：选择一个病例（CASE-005，CRAB VAP，碳青霉烯全耐药）

→ Cell 2：运行 retriever → 输出匹配的 12 条噬菌体互作记录

→ Cell 3：运行 retriever → 输出 7 个相似历史病例

3\. 展示 Evidence Package

→ Cell 4：调用 DeepSeek → 输出完整的三部分 Evidence Package

→ 高亮 Clinical Evidence 中引用 CASE-001/004 的具体内容

→ 高亮 Matching Evidence 中 L3 条目标注"来源：CASE-001 验证"

4\. 解释 Learning 闭环

→ Cell 5：展示跨病例引用关系图

→ "CASE-001 的治疗经验 → 已编码为 Knowledge Layer 中的 L3 知识

→ 在 CASE-005 中被检索到 → 领域专家确认该引用有效

→ 这就是 Learning Engine 的核心假设：上一个病例让下一个更聪明"

5\. 回答投资人唯一需要回答的问题

→ "这个飞轮能在真实医院里转起来吗？"

→ "15 个病例已经展示了'编码→检索→复用'的技术链路是通的。

下一步是在生产环境中验证医生是否愿意使用。"

**十、4 周开发计划**

**10.1 总览**

| **周** | **主题** | **开发人员** | **领域专家** | **里程碑** |
| --- | --- | --- | --- | --- |
| W1  | 环境搭建 + 数据导入 | 5 天 | 0.5 天（确认数据字段） | Neo4j 中有数据 |
| W2  | 检索 + 策展 + Evidence Package | 5 天 | 1.5 天（审核 Ontology + 评审首批输出） | 首份 Evidence Package 通过专家评审 |
| W3  | 跨病例复用 + 迭代 | 5 天 | 3 天（大量评审 + 复用判断） | V2 达标（≥ 2 个复用实例） |
| W4  | 验收 + 演示准备 | 5 天 | 3 天（最终评审 + 演示演练） | V3 达标（演示脚本就绪） |

**10.2 W1：环境搭建 + 数据导入（Day 1-5）**

| **天** | **开发人员任务** | **交付物** |
| --- | --- | --- |
| D1  | 安装 Neo4j、Python 环境、配置 DeepSeek API key。初始化 Git 仓库。 | 可运行的空项目 |
| D2  | 实现 Ontology schema（Cypher 建约束/索引）。编写 data_loader.py 的 Pathogen + ClinicalCase 导入逻辑。 | schema.py + data_loader.py（初版） |
| D3  | 完成病例 CSV 导入脚本 + 验证逻辑。导入 15 例病例。 | 15 例病例在 Neo4j 中可见 |
| D4  | 手动精选 30-50 条文献知识 → 整理为 phage_interactions.csv。编写批量导入脚本。 | 文献知识导入完成 |
| D5  | 导入完成确认。Neo4j Browser 验证节点数和关系数。领域专家（0.5 天）审核 Ontology schema 确认实体和属性定义正确。 | W1 完成：数据就绪，Ontology schema 经专家确认 |

**W1 通过标准**：Neo4j Browser 中可查询到 ≥ 15 Pathogen、≥ 30 Phage、≥ 50 PhageHostInteraction、≥ 15 ClinicalCase。

**10.3 W2：检索 + 策展 + Evidence Package（Day 6-10）**

| **天** | **开发人员任务** | **交付物** |
| --- | --- | --- |
| D6  | 实现 retriever.py 的两个查询函数 + 单元级手动验证。 | retriever.py |
| D7  | 实现 package_builder.py：DeepSeek API 调用 + System Prompt + JSON 解析。生成首批 3 份 Evidence Package。 | package_builder.py + 首批输出样本 |
| D8  | 领域专家（1 天）评审首批 3 份 Evidence Package。开发人员根据反馈调整 System Prompt 和检索参数。 | 首批评审记录 + Prompt 迭代 |
| D9  | 实现 curation.py。回写 8 个已治疗病例的结局。相关 PhageHostInteraction 升级为 L3。 | curation.py + 8 条 L3 知识 |
| D10 | 用升级后的 Knowledge Layer 重新生成 Evidence Package。领域专家（0.5 天）验证 L3 知识是否在 Evidence Package 中正确体现。 | W2 完成：首份"有历史病例知识"的 Evidence Package 通过评审 |

**W2 通过标准**：至少 1 份 Evidence Package（含 L3 历史病例引用）获得领域专家综合评分 ≥ 3/5。

**10.4 W3：跨病例复用 + 迭代（Day 11-15）**

| **天** | **开发人员任务** | **交付物** |
| --- | --- | --- |
| D11 | 实现 FR-6 Jupyter Notebook 交互界面（01 + 02）。确保从选择病例到展示 Evidence Package 一条龙可运行。 | 02_evidence_package.ipynb |
| D12 | 实现 FR-7 跨病例复用检测脚本。选择 5 对相似病例，逐一运行检测。 | 03_cross_case_reuse.ipynb |
| D13 | 领域专家（1 天）评审跨病例检测结果：逐条判断引用有效性。记录 V2 计数。 | V2 初步计数 |
| D14 | 如果 V2 计数 < 2：开发人员根据专家反馈调整检索条件或重新选择病例对，重新测试。 | V2 最终计数 |
| D15 | 如果 V2 已达标：准备 V3 演示链路（选择 1 条最清晰的闭环）。领域专家（1 天）逐链路审核。 | W3 完成：V2 达标 |

**W3 通过标准**：V2 ≥ 2 个有效跨病例复用实例。

**10.5 W4：验收 + 演示准备（Day 16-20）**

| **天** | **开发人员任务** | **交付物** |
| --- | --- | --- |
| D16 | V1 正式统计（必填字段填充率）。如有缺失 → 补充或记录原因。 | V1 通过报告 |
| D17 | V3 演示链路最终确认 + 演练。编写 README.md。代码整理 + 注释补充。 | 演示脚本 + 文档 |
| D18 | 领域专家（1.5 天）最终评审：验证 V2/V3 全部实例，确认"引用有效"判断无异议。 | 专家评审最终意见 |
| D19 | 最终集成测试：从零执行 README 步骤，确认全流程可复现。准备 PRD V3.0（生产就绪版）的差距分析。 | 复现验证 + 差距分析草稿 |
| D20 | 缓冲区。处理意外问题。代码冻结。 | 最终交付 |

**W4 通过标准**：V1/V2/V3 全部达标，5 分钟演示脚本可在 Jupyter Notebook 中完整复现。

**十一、交付物清单**

| **#** | **交付物** | **形式** | **说明** |
| --- | --- | --- | --- |
| D-1 | 源代码仓库 | Git 仓库 | 含 README.md、requirements.txt、全部 Python 模块、Jupyter Notebook |
| D-2 | Neo4j 数据库（含数据） | Neo4j dump 文件 | 可直接 restore，包含全部 15 例病例 + 文献知识 |
| D-3 | Ontology Schema 文档 | Markdown | 实体定义、属性说明、关系图、设计决策记录 |
| D-4 | 15 例病例导入完成确认 | CSV 导入日志 | 字段填充率统计、缺失字段记录 |
| D-5 | Evidence Package 样本集 | JSON 文件 | ≥ 10 份 Evidence Package（含领域专家评分） |
| D-6 | 跨病例复用验证报告 | Markdown | V2 实例逐条记录（含专家判断依据） |
| D-7 | V3 演示脚本 | Jupyter Notebook | 03_cross_case_reuse.ipynb 即为演示脚本 |
| D-8 | 验收报告 | Markdown | V1/V2/V3 达标情况 + 功能验收清单结果 |
| D-9 | 领域专家评审记录 | Markdown / 表格 | 每次评审的时间、对象、评分、反馈 |
| D-10 | 生产部署差距分析 | Markdown | 沙箱 → 生产还需解决的 5 个关键问题（PRD V3.0 的前置输入） |

**十二、边界声明**

**12.1 沙箱已验证的内容**

| **已验证** | **程度** | **证据** |
| --- | --- | --- |
| Ontology schema 可承载真实 CRAB 临床数据 | 15 例验证 | V1 填充率 ≥ 90% |
| 公开文献知识可被编码为可检索的图结构 | 30-50 条验证 | FR-2 导入完成 |
| 病例经验可被回写并升级证据等级 | 8 例验证 | curation.py 运行结果 |
| 历史病例知识可被新病例检索命中 | 5 对验证 | V2 实例 |
| Learning 闭环链路存在且可演示 | 1 条验证 | V3 演示脚本 |
| DeepSeek 可基于检索结果组装 Evidence Package | ≥ 10 份验证 | 专家评分 |

**12.2 沙箱未验证的内容（留待生产环境）**

| **未验证** | **为什么沙箱做不了** | **需要什么条件** |
| --- | --- | --- |
| 医生是否愿意使用 Copilot | 无真实 ICU 工作流、无临床压力 | 合作医院生产部署 + 观察 |
| LIS 系统对接是否顺畅 | 无医院 IT 环境 | 医院 IT 配合 + HL7/FHIR 接口开发 |
| Evidence Package 是否能加速临床决策 | 无真实医生、无计时基线 | 生产环境 A/B 对照试验 |
| Learning Flywheel 的转速（天/周/月） | 4 周时间太短 | 至少 3-6 个月的生产运行数据 |
| 15 例以上的规模化策展是否可行 | 15 例手工策展 ≠ 500 例的瓶颈分析 | 更大规模数据 + 半自动化策展工具 |
| CRAB 以外的病原菌 | 仅验证 CRAB | 多病原菌数据 |
| 合规路径（伦理审查、个人信息保护法） | 沙箱数据已有科研伦理审批，不代表生产合规路径 | 正式伦理审批 + 数据合规评估 |

**12.3 已知技术债务（可接受的 MVP 妥协）**

| **技术债务** | **为什么接受** | **何时偿还** |
| --- | --- | --- |
| 文献知识手工精选（非自动扫描） | 4 周内自动化扫描 + 实体抽取质量无法保证，手工 30-50 条质量可控 | M1：引入 Literature Agent 自动化 |
| Neo4j Community Edition（非企业版） | 15 病例 + 30-50 文献规模下 Community 完全够用 | 生产部署前评估是否需升级 |
| 无向量检索 | 图查询已覆盖"匹配噬菌体"和"相似病例"两个核心检索需求 | M1：Graph + RAG 混合检索 |
| Jupyter Notebook 而非 Web 应用 | 零前端成本，开发可直接操作和演示 | 生产部署前改为 Web 应用 |
| 无自动化测试 | 4 周手动验证 + 专家评审更有效 | M1：建立测试框架 |
| 证据等级手动升级（无自动规则） | 15 例下规则引擎过度设计 | M1：定义自动升级规则 |
| Specimen/LiteratureEvidence 无独立节点 | 属性并入主实体降低复杂度，15 例下不影响查询 | 数据量扩大后再拆分 |

**十三、附录：术语对照**

| **缩写/术语** | **全称** | **说明** |
| --- | --- | --- |
| MVP | Minimum Viable Product / Platform Capability Validator | 本 PRD 中指第一个平台能力验证器，非传统意义的最小软件产品 |
| Workspace | Phage Intelligence Workspace | 产品层名称。📄 来源：最新 MVP 章节 |
| Copilot | Evidence-driven Phage Matching Copilot | MVP 第一能力模块。📄 来源同上 |
| Platform | Learning-driven Precision Infection Platform | 平台层名称 |
| Evidence Package | 循证证据包 | Copilot 的核心输出。4 周版精简为三部分：Matching Evidence + Clinical Evidence + Explanation |
| Knowledge Layer | 知识层 | Ontology 结构化实例数据所在的图数据库 |
| Knowledge Curation | 知识策展 | 将原始临床数据按 Ontology schema 填充、标记验证状态、写入 Knowledge Layer 的过程。📄 来源：V4.0 第 508-510 行 |
| Learning Engine | 学习引擎 | 组织学习能力的系统实现。📄 来源：V4.0 核心主张 |
| Learning Flywheel | 学习飞轮 | 病例 → 知识 → 更好配型 → 更多病例的闭环。📄 来源：V4.0 第 86-90 行 |
| FDE | Forward Deployed Engineer | 嵌入客户现场的工程师。此 PRD 沙箱版中 FDE 工作由开发人员承担 |
| CRAB | Carbapenem-Resistant Acinetobacter baumannii | 碳青霉烯耐药鲍曼不动杆菌。📄 V4.0 第 213 行：CRAB 占合作医院耐药菌 51%，为首期目标病原菌 |
| VAP | Ventilator-Associated Pneumonia | 呼吸机相关肺炎 |
| BALF | Bronchoalveolar Lavage Fluid | 支气管肺泡灌洗液 |
| AST | Antimicrobial Susceptibility Testing | 抗菌药物敏感性试验 |
| LIS | Laboratory Information System | 医院实验室信息系统 |
| DeepSeek (DS) | —   | 本 MVP 使用的 LLM。📄 选型依据：V4.0 第 166 行"LLM 可替换"原则 + 成本/速度/中文能力考量 |
| Neo4j | —   | 图数据库。Property Graph 模型，Cypher 查询语言 |
| Ontology | —   | Knowledge Layer 的结构骨架：定义实体类型、属性、关系。4 周版做轻 Ontology（4 实体 + Property Graph，无 OWL 推理） |
| L1-L5 | Evidence Level 1-5 | 证据等级体系：L1 公开文献、L2 体外验证、L3 单例临床、L4 多中心、L5 组织学习闭环 |
| PHI | Protected Health Information | 受保护的健康信息。沙箱不持有任何 PHI |
| PII | Personally Identifiable Information | 个人可识别信息。沙箱不持有任何 PII |
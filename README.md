**Phage Intelligence Workspace — MVP PRD V3.0**

**目录**

一、Ontology 设计  
二、技术架构  
三、数据流  
四、功能  

**一、Ontology 设计**

**1.1 设计策略**

轻 Ontology：4 实体 + 核心关系 + Property Graph（Neo4j）。

**1.2 实体定义**

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

**1.3 核心关系**

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


**二、技术架构**

**2.1 技术栈**

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

**2.2 架构图**

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

**2.3 核心模块**

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


**三、数据流**

**3.1 端到端流程**

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

**3.2 关键场景：跨病例知识复用（V2/V3 验证核心）**

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


**四、功能**

**4.1 功能验收清单**

| **功能** | **验收方式** | **通过标准** |
| --- | --- | --- |
| FR-1 病例导入 | 执行 src/data_loader.py，在 Neo4j Browser 中检查节点数 | Pathogen ≥ 15, ClinicalCase ≥ 15 |
| FR-2 文献知识导入 | 执行导入脚本，在 Neo4j Browser 中检查 PhageHostInteraction 节点数 | PhageHostInteraction ≥ 30（其中 evidence_level 为 L1/L2 的 ≥ 20） |
| FR-3 图查询 | 在 Jupyter Notebook 中给定已知 CRAB 参数，调用 retriever 函数 | 返回 ≥ 1 个 Phage 匹配结果，返回 ≥ 1 个相似病例 |
| FR-4 Evidence Package | 调用 build_evidence_package，检查返回的 dict | 包含三部分（matching_evidence, clinical_evidence, explanation），每部分非空 |
| FR-5 知识策展 | 调用 curation.curate_case_outcome 更新一个病例，再查询确认 | Neo4j 中该病例的 clinical_outcome 字段已更新，相关 PhageHostInteraction 的 evidence_level 已升级 |
| FR-6 交互界面 | 在 02_evidence_package.ipynb 中选择病例，依次运行所有 Cell | 从选择到展示完成 ≤ 2 分钟，中间不需要手动修改代码 |
| FR-7 跨病例复用 | 运行 03_cross_case_reuse.ipynb，输入病例 A 和病例 B | 自动检测并标注引用类型，输出可读的报告 |

**4.2 环境配置**

requirements.txt

neo4j==6.2.0
pandas==3.0.3
openai==2.45.0
python-dotenv==1.2.2
jupyter==1.1.1
notebook==7.6.0

.env 示例

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=12345678
DS_API_KEY=api_key


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



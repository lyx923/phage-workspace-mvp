
# Ontology Schema — Phage Intelligence Workspace MVP

> 版本：v0.4  
> 对应代码基线：`phage-workspace-mvp` 仓库  
> 最后更新：2026-08-22

本文档定义 Neo4j 图数据库的完整数据模型，包括所有节点标签、属性、关系类型、约束、索引及常用查询。模型分为 **Foundation**（共享基础层）和 **Scientific**（科学知识域）两个逻辑层，符合企业级 Ontology 设计原则。


## 1. 实体定义（节点标签）

### 1.1 Foundation 层（共享对象）

#### Pathogen（病原菌主数据）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `pathogen_id` | String | ✅ | 唯一标识 | `PATH-001` |
| `species` | String | ✅ | 菌种名称 | `Acinetobacter baumannii` |
| `taxonomy_id` | String | ❌ | NCBI Taxonomy ID | `470` |
| `aliases` | List[String] | ❌ | 别名列表 | `["A. baumannii", "Ab"]` |
| `reference_status` | String | ❌ | 引用状态 | `verified` |

#### Organization（组织主数据）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `organization_id` | String | ✅ | 唯一标识 | `ORG-001` |
| `canonical_name` | String | ✅ | 正式名称 | `University of X` |
| `aliases` | List[String] | ❌ | 别名 | `["UoX"]` |
| `organization_type` | String | ❌ | 类型 | `academic` / `biotech` |
| `country` | String | ❌ | 国家 | `USA` |

#### SourceArtifact（来源制品）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `source_id` | String | ✅ | 唯一标识 | `SRCabc123` |
| `source_domain` | String | ✅ | 所属域 | `scientific` |
| `source_type` | String | ✅ | 类型 | `literature` / `clinical_case` / `lysis_assay_file` |
| `title` | String | ✅ | 标题或描述 | `PMID:12345678` |
| `uri_or_path` | String | ❌ | 外部链接或路径 | `https://doi.org/...` |
| `publisher_or_owner` | String | ❌ | 发布者或所有者 | `Publisher X` |
| `published_at` | DateTime | ❌ | 发布时间 | `2025-01-01T00:00:00Z` |
| `retrieved_at` | DateTime | ✅ | 检索时间 | `2026-08-22T10:00:00Z` |
| `document_hash` | String | ❌ | 内容哈希 | `sha256:...` |
| `access_level` | String | ✅ | 访问级别 | `public` / `internal` / `restricted` |
| `review_status` | String | ✅ | 审核状态 | `pending` / `approved` / `rejected` |
| `created_at` | DateTime | ✅ | 创建时间 | |
| `updated_at` | DateTime | ✅ | 更新时间 | |
| `schema_version` | String | ✅ | Schema 版本 | `1.0.0` |

#### Review（统一审核记录）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `review_id` | String | ✅ | 唯一标识 | `REV-12345678` |
| `review_type` | String | ✅ | 类型 | `assay_qc` / `evidence_upgrade` / `scientific_package_review` / `knowledge_reuse_review` |
| `target_domain` | String | ✅ | 目标域 | `scientific` |
| `target_object_type` | String | ✅ | 目标对象类型 | `LysisAssay` |
| `target_object_id` | String | ✅ | 目标对象 ID | `ASSAY-001` |
| `reviewer_id` | String | ✅ | 审核人 ID | `expert_001` |
| `decision` | String | ✅ | 决策 | `approved` / `rejected` / `needs_revision` / `confirmed` |
| `comment` | String | ❌ | 审核评语 | `数据充分，同意升级` |
| `review_policy_version` | String | ✅ | 审核策略版本 | `v1.0` |
| `reviewed_at` | DateTime | ✅ | 审核时间 | |
| `created_at` | DateTime | ✅ | 创建时间 | |

#### AuditEvent（审计事件）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `audit_event_id` | String | ✅ | 唯一标识 | `SCI:AUDIT:ABC123` |
| `domain` | String | ✅ | 所属域 | `scientific` |
| `action_type` | String | ✅ | 操作类型 | `EVIDENCE_UPGRADE_APPROVED` |
| `object_type` | String | ✅ | 对象类型 | `LysisAssay` |
| `object_id` | String | ✅ | 对象 ID | `ASSAY-001` |
| `actor_id` | String | ✅ | 操作者 ID | `expert_001` |
| `occurred_at` | DateTime | ✅ | 发生时间 | |
| `correlation_id` | String | ✅ | 关联 ID（同一业务操作的多个事件） | `CORR-123456` |
| `before_snapshot` | String (JSON) | ❌ | 变更前状态 | `{"evidence_level": "L2"}` |
| `after_snapshot` | String (JSON) | ❌ | 变更后状态 | `{"evidence_level": "L3"}` |
| `reason` | String | ❌ | 变更原因 | `审核通过升级` |
| `request_id` | String | ❌ | 请求 ID（用于链路追踪） | |
| `schema_version` | String | ✅ | Schema 版本 | `v1` |

#### OntologyModule（本体模块版本）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `module_id` | String | ✅ | 模块 ID | `foundation-core` |
| `module_name` | String | ✅ | 模块名称 | `foundation-core` |
| `domain` | String | ✅ | 所属域 | `foundation` |
| `version` | String | ✅ | 版本号 | `1.0.0` |
| `status` | String | ✅ | 状态 | `active` / `draft` |
| `owner` | String | ✅ | 负责人 | `platform_team` |
| `schema_hash` | String | ❌ | Schema 内容哈希 | `sha256:...` |
| `activated_at` | DateTime | ❌ | 激活时间 | |
| `created_at` | DateTime | ✅ | 创建时间 | |

#### ControlledVocabulary / ControlledTerm（受控词表）

**ControlledVocabulary** 属性：
- `vocabulary_id` (String, ✅), `vocabulary_name` (String, ✅), `version` (String, ✅), `domain` (String, ✅), `status` (String), `owner` (String), `created_at` (DateTime)

**ControlledTerm** 属性：
- `term_id` (String, ✅), `vocabulary_id` (String, ✅), `code` (String, ✅), `display_name` (String), `description` (String), `status` (String), `replaced_by` (String, ❌), `created_at` (DateTime)


### 1.2 Scientific 层（科学知识域）

#### Phage（噬菌体）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `phage_id` | String | ✅ | 唯一标识 | `PHAGE-001` |
| `name` | String | ✅ | 噬菌体名称 | `vB_AbaM_AbTZI` |
| `family` | String | ❌ | 分类科属 | `Myoviridae` |
| `receptor_target` | String | ❌ | 靶向受体 | `Capsular polysaccharide` |
| `lifecycle` | String | ❌ | 生命周期 | `Lytic` |
| `safety_flags` | List[String] | ❌ | 安全标记 | `["no_toxin_genes"]` |
| `genome_accession` | String | ❌ | GenBank 登录号 | `NC_048XXX` |

#### HostStrain（宿主菌株）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `host_strain_id` | String | ✅ | 唯一标识（稳定 ID） | `HOST:PARTNER_A:B-KP11` |
| `strain_label` | String | ✅ | 菌株编号（显示名称） | `B-KP11` |
| `sequence_type` | String | ❌ | MLST 分型 | `ST23` |
| `capsule_type` | String | ❌ | 荚膜型 | `KL1` |

#### LysisAssay（裂解实验）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `assay_id` | String | ✅ | 唯一标识 | `ASSAY-001` |
| `pathogen_id` | String | ✅ | 关联 Pathogen ID | `PATH-001` |
| `assay_type` | String | ✅ | 实验类型 | `lysis_assay` / `unknown` |
| `result` | String | ✅ | 标准化结果 | `Lytic` / `No infection` / `Partial` |
| `result_value` | Float | ❌ | 定量值（0-1） | `0.94` |
| `result_unit` | String | ❌ | 单位 | `probability` |
| `evidence_level` | String | ✅ | 证据等级（L1-L5） | `L2` |
| `evidence_ref` | List[String] | ❌ | 证据来源引用 | `["CASE-001", "PMID:12345678"]` |
| `qc_status` | String | ✅ | QC 状态 | `pending` / `passed` / `failed` |
| `validation_status` | String | ✅ | 验证状态 | `unreviewed` / `verified` |
| `evidence_policy_version` | String | ✅ | 证据策略版本 | `v1.0` |
| `source_domain` | String | ✅ | 来源域 | `scientific` |
| `created_at` | DateTime | ✅ | 创建时间 | |
| `updated_at` | DateTime | ✅ | 更新时间 | |
| `version` | Integer | ✅ | 版本号 | `1` |

#### ClinicalCase（临床病例）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `case_id` | String | ✅ | 唯一标识（去标识化） | `CASE-001` |
| `infection_type` | String | ✅ | 感染类型 | `VAP` |
| `infection_site` | String | ✅ | 感染部位 | `Lung` |
| `specimen_type` | String | ✅ | 标本类型 | `BALF` |
| `patient_age_group` | String | ❌ | 年龄段 | `55-65` |
| `comorbidities` | List[String] | ❌ | 基础疾病 | `["COPD", "DM"]` |
| `prior_antibiotics` | List[String] | ❌ | 既往抗生素 | `["Meropenem"]` |
| `phage_treatment` | String | ❌ | 噬菌体治疗方案（描述） | `Cocktail: φA+φB, 雾化吸入` |
| `clinical_outcome` | String | ❌ | 临床结局 | `Clinical improvement at Day 7` |
| `microbiological_outcome` | String | ❌ | 微生物学结局 | `菌量下降3log` |
| `curated_by` | String | ❌ | 策展人标识 | `FDE-01` |
| `curation_date` | Date | ❌ | 策展日期 | `2026-08-15` |

#### ScientificKnowledgeRule（黄金规则）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `rule_id` | String | ✅ | 唯一标识 | `RULE_CRAB_KL2` |
| `strain_type` | String | ✅ | 菌株型别 | `KL2` |
| `treatment` | String | ✅ | 推荐治疗方案 | `ΦK2-v3 单用` |
| `outcome` | String | ✅ | 预期临床结局 | `第14天微生物清除` |
| `evidence_from` | String | ✅ | 证据来源 | `肖易倍团队` |
| `rule_type` | String | ✅ | 规则类型 | `clinical_validation` |
| `status` | String | ✅ | 状态 | `active` / `pending_review` |
| `applicability` | JSON | ❌ | 适用条件（额外约束） | `{"species":"Acinetobacter baumannii", "strain_type":"KL2"}` |
| `required_attributes` | List[String] | ✅ | 必须提供的属性 | `["species", "strain_type"]` |
| `exclusion_conditions` | JSON | ❌ | 排除条件 | `{}` |
| `review_status` | String | ✅ | 审核状态 | `pending` / `approved` |
| `valid_from` | Date | ❌ | 生效日期 | |
| `valid_until` | Date | ❌ | 失效日期 | |
| `policy_version` | String | ✅ | 策略版本 | `v1.0` |

#### EvidenceUpgradeProposal（证据升级提案）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `proposal_id` | String | ✅ | 唯一标识 | `SCI:PROPOSAL:ABC123` |
| `assay_id` | String | ✅ | 关联 LysisAssay ID | `ASSAY-001` |
| `source_case_id` | String | ✅ | 触发升级的病例 ID | `CASE-001` |
| `current_level` | String | ✅ | 当前证据等级 | `L2` |
| `proposed_level` | String | ✅ | 目标证据等级 | `L3` |
| `reason` | String | ✅ | 升级理由 | `基于病例临床结局` |
| `status` | String | ✅ | 状态 | `pending_review` / `approved` / `rejected` / `executed` / `cancelled` |
| `proposed_by` | String | ✅ | 提案人 | `system` / `curator_001` |
| `proposed_at` | DateTime | ✅ | 提案时间 | |
| `reviewed_at` | DateTime | ❌ | 审核时间 | |
| `reviewer_id` | String | ❌ | 审核人 ID | `expert_001` |

#### ScientificEvidencePackage（证据包）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `package_id` | String | ✅ | 唯一标识 | `EP-ABCD1234` |
| `package_type` | String | ✅ | 类型 | `evidence_summary` |
| `query_context` | String (JSON) | ✅ | 检索上下文（参数） | `{"species":"Acinetobacter baumannii", "strain_type":"KL2"}` |
| `status` | String | ✅ | 状态 | `draft` / `pending_review` / `approved` / `rejected` / `superseded` |
| `generated_by` | String | ✅ | 生成者 | `system` / `curator_001` |
| `model_used` | String | ❌ | 使用的 LLM 模型 | `deepseek-v3` |
| `prompt_version` | String | ❌ | Prompt 版本 | `v1.0` |
| `summary` | String | ❌ | 概要说明 | `针对 CRAB KL2 的候选噬菌体` |
| `limitations` | String | ❌ | 局限性声明 | `需人工进一步确认` |
| `review_status` | String | ✅ | 审核状态 | `pending` / `approved` / `rejected` |
| `created_at` | DateTime | ✅ | 创建时间 | |
| `updated_at` | DateTime | ✅ | 更新时间 | |
| `schema_version` | String | ✅ | Schema 版本 | `1.0.0` |

#### KnowledgeReuseEvent（知识复用事件）

| 属性 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `reuse_event_id` | String | ✅ | 唯一标识 | `REUSE-ABCD1234` |
| `source_object_type` | String | ✅ | 源对象类型 | `ClinicalCase` |
| `source_object_id` | String | ✅ | 源对象 ID | `CASE-001` |
| `target_package_id` | String | ✅ | 目标证据包 ID | `EP-ABCD1234` |
| `reuse_type` | String | ✅ | 复用类型 | `direct_reuse` / `evidence_upgrade` |
| `detection_method` | String | ✅ | 检测方式 | `cross_case_phage_overlap` |
| `status` | String | ✅ | 状态 | `detected` / `pending_review` / `confirmed` / `rejected` |
| `expert_assessment` | String | ✅ | 专家评估 | `pending` / `confirmed` / `rejected` |
| `assessment_comment` | String | ❌ | 评估备注 | |
| `retrieval_reason` | String | ❌ | 检测理由（系统生成） | |
| `created_at` | DateTime | ✅ | 创建时间 | |
| `reviewed_at` | DateTime | ❌ | 审核时间 | |
| `reviewer_id` | String | ❌ | 审核人 ID | |

---

## 2. 关系类型

### 2.1 Foundation 内部关系

| 关系 | 起点 | 终点 | 含义 |
|------|------|------|------|
| `BELONGS_TO` | `ControlledTerm` | `ControlledVocabulary` | 术语属于某词表 |

### 2.2 Scientific 内部关系

| 关系 | 起点 | 终点 | 含义 |
|------|------|------|------|
| `USED_IN` | `Phage` | `LysisAssay` | 噬菌体参与实验 |
| `TESTED_AGAINST` | `LysisAssay` | `HostStrain` | 实验测试某菌株 |
| `IS_STRAIN_OF` | `HostStrain` | `Pathogen` | 菌株属于某病原菌 |
| `INVOLVES_PATHOGEN` | `ClinicalCase` | `Pathogen` | 病例涉及某病原菌 |
| `TREATED_WITH` | `ClinicalCase` | `Phage` | 病例使用某噬菌体 |
| `HAS_ISOLATE` | `ClinicalCase` | `HostStrain` | 病例分离出某菌株 |
| `HAS_VALIDATED_RULE` | `Pathogen` | `ScientificKnowledgeRule` | 病原菌有黄金规则 |
| `RECOMMENDS_PHAGE` | `ScientificKnowledgeRule` | `Phage` | 规则推荐某噬菌体 |

### 2.3 跨层关系（Foundation ↔ Scientific）

| 关系 | 起点 | 终点 | 含义 |
|------|------|------|------|
| `DERIVED_FROM` | `LysisAssay` | `SourceArtifact` | 实验来源于某来源 |
| `DERIVED_FROM` | `ClinicalCase` | `SourceArtifact` | 病例来源于某来源 |
| `REVIEWS` | `Review` | `EvidenceUpgradeProposal` | 审核关联提案 |
| `REVIEWS` | `Review` | `ScientificEvidencePackage` | 审核关联证据包 |
| `REVIEWS` | `Review` | `KnowledgeReuseEvent` | 审核关联复用事件 |
| `REVIEWS` | `Review` | `LysisAssay` | 审核关联实验（QC 审核） |
| `USES_ASSAY` | `ScientificEvidencePackage` | `LysisAssay` | 证据包引用实验 |
| `REFERENCES_CASE` | `ScientificEvidencePackage` | `ClinicalCase` | 证据包引用病例 |
| `INCLUDES_CANDIDATE` | `ScientificEvidencePackage` | `Phage` | 证据包包含候选噬菌体 |
| `CITES_SOURCE` | `ScientificEvidencePackage` | `SourceArtifact` | 证据包引用来源 |
| `REUSES` | `KnowledgeReuseEvent` | `LysisAssay` | 复用事件涉及实验 |
| `SOURCE_CASE` | `KnowledgeReuseEvent` | `ClinicalCase` | 复用事件源病例 |
| `TARGETS_PACKAGE` | `KnowledgeReuseEvent` | `ScientificEvidencePackage` | 复用事件目标证据包 |


## 3. 约束与索引（Cypher DDL）

```cypher
// ============ Foundation 约束 ============
CREATE CONSTRAINT pathogen_id_unique IF NOT EXISTS FOR (p:Pathogen) REQUIRE p.pathogen_id IS UNIQUE;
CREATE CONSTRAINT organization_id_unique IF NOT EXISTS FOR (o:Organization) REQUIRE o.organization_id IS UNIQUE;
CREATE CONSTRAINT source_id_unique IF NOT EXISTS FOR (s:SourceArtifact) REQUIRE s.source_id IS UNIQUE;
CREATE CONSTRAINT review_id_unique IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE;
CREATE CONSTRAINT audit_event_id_unique IF NOT EXISTS FOR (ae:AuditEvent) REQUIRE ae.audit_event_id IS UNIQUE;
CREATE CONSTRAINT module_id_unique IF NOT EXISTS FOR (m:OntologyModule) REQUIRE m.module_id IS UNIQUE;
CREATE CONSTRAINT vocabulary_id_unique IF NOT EXISTS FOR (v:ControlledVocabulary) REQUIRE v.vocabulary_id IS UNIQUE;
CREATE CONSTRAINT term_id_unique IF NOT EXISTS FOR (t:ControlledTerm) REQUIRE t.term_id IS UNIQUE;

// ============ Scientific 约束 ============
CREATE CONSTRAINT phage_id_unique IF NOT EXISTS FOR (p:Phage) REQUIRE p.phage_id IS UNIQUE;
CREATE CONSTRAINT host_strain_id_unique IF NOT EXISTS FOR (h:HostStrain) REQUIRE h.host_strain_id IS UNIQUE;
CREATE CONSTRAINT assay_id_unique IF NOT EXISTS FOR (a:LysisAssay) REQUIRE a.assay_id IS UNIQUE;
CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (c:ClinicalCase) REQUIRE c.case_id IS UNIQUE;
CREATE CONSTRAINT rule_id_unique IF NOT EXISTS FOR (r:ScientificKnowledgeRule) REQUIRE r.rule_id IS UNIQUE;
CREATE CONSTRAINT proposal_id_unique IF NOT EXISTS FOR (p:EvidenceUpgradeProposal) REQUIRE p.proposal_id IS UNIQUE;
CREATE CONSTRAINT package_id_unique IF NOT EXISTS FOR (p:ScientificEvidencePackage) REQUIRE p.package_id IS UNIQUE;
CREATE CONSTRAINT reuse_event_id_unique IF NOT EXISTS FOR (k:KnowledgeReuseEvent) REQUIRE k.reuse_event_id IS UNIQUE;

// ============ 索引（加速查询） ============
CREATE INDEX IF NOT EXISTS FOR (p:Pathogen) ON (p.species);
CREATE INDEX IF NOT EXISTS FOR (p:Pathogen) ON (p.taxonomy_id);
CREATE INDEX IF NOT EXISTS FOR (h:HostStrain) ON (h.strain_label);
CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.evidence_level);
CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.qc_status);
CREATE INDEX IF NOT EXISTS FOR (c:ClinicalCase) ON (c.infection_type);
CREATE INDEX IF NOT EXISTS FOR (c:ClinicalCase) ON (c.curation_date);
CREATE INDEX IF NOT EXISTS FOR (p:EvidenceUpgradeProposal) ON (p.status);
CREATE INDEX IF NOT EXISTS FOR (p:ScientificEvidencePackage) ON (p.status);
CREATE INDEX IF NOT EXISTS FOR (k:KnowledgeReuseEvent) ON (k.status);
CREATE INDEX IF NOT EXISTS FOR (ae:AuditEvent) ON (ae.domain);
CREATE INDEX IF NOT EXISTS FOR (ae:AuditEvent) ON (ae.correlation_id);
CREATE INDEX IF NOT EXISTS FOR (r:Review) ON (r.review_type);
CREATE INDEX IF NOT EXISTS FOR (r:Review) ON (r.decision);
```

## 2.4 常用 Cypher 查询

### 1. 查询匹配的噬菌体（按证据等级排序）
cypher
MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)
MATCH (p:Pathogen {species: $species})
WHERE a.pathogen_id = p.pathogen_id
  AND ($resistance IS NULL OR p.resistance_mechanism CONTAINS $resistance)
RETURN ph.name AS phage_name,
       a.evidence_level,
       a.result_value AS probability,
       a.evidence_ref
ORDER BY 
  CASE a.evidence_level
    WHEN 'L5' THEN 1
    WHEN 'L4' THEN 2
    WHEN 'L3' THEN 3
    WHEN 'L2' THEN 4
    WHEN 'L1' THEN 5
    ELSE 6
  END,
  a.result_value DESC
LIMIT 20
### 2. 查询相似病例（同菌种，同/近感染类型）
cypher
MATCH (c:ClinicalCase)-[:INVOLVES_PATHOGEN]->(p:Pathogen {species: $species})
WHERE $infection_type IS NULL OR c.infection_type CONTAINS $infection_type
OPTIONAL MATCH (c)-[:TREATED_WITH]->(ph:Phage)
RETURN c.case_id,
       c.infection_type,
       c.clinical_outcome,
       collect(ph.name) AS phages_used
ORDER BY c.curation_date DESC
LIMIT 5
### 3. 查询病例的完整治疗链路（菌株 → 实验 → 噬菌体）
cypher
MATCH (c:ClinicalCase {case_id: $case_id})-[:HAS_ISOLATE]->(h:HostStrain)
MATCH (a:LysisAssay)-[:TESTED_AGAINST]->(h)
MATCH (ph:Phage)-[:USED_IN]->(a)
RETURN c.case_id, h.strain_label, ph.name, a.evidence_level, a.result
### 4. 获取待审核的升级提案
cypher
MATCH (p:EvidenceUpgradeProposal {status: 'pending_review'})
OPTIONAL MATCH (p)<-[:REVIEWS]-(r:Review)
RETURN p.proposal_id, p.assay_id, p.current_level, p.proposed_level, p.reason, r.decision AS last_review
### 5. 查询某个证据包引用的所有 Assay 和来源
cypher
MATCH (pkg:ScientificEvidencePackage {package_id: $package_id})
OPTIONAL MATCH (pkg)-[:USES_ASSAY]->(a:LysisAssay)
OPTIONAL MATCH (a)-[:DERIVED_FROM]->(s:SourceArtifact)
RETURN pkg.package_id, collect(DISTINCT a.assay_id) AS assays, collect(DISTINCT s.source_id) AS sources
4.6 查询菌株配型覆盖度（统计每个菌株匹配的噬菌体数）
cypher
MATCH (a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
MATCH (ph:Phage)-[:USED_IN]->(a)
RETURN h.strain_label, count(DISTINCT ph) AS phage_count
ORDER BY phage_count DESC

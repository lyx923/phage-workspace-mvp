# 一、数据文件格式

## 1.1 cases.csv

| 字段名 | 类型 | 必填 | 示例 |
|--------|------|------|------|
| case_id | string | ✅ | CASE-001 |
| pathogen_id | string | ✅ | PATH-001 |
| species | string | ✅ | Acinetobacter baumannii |
| resistance_mechanism | string | ✅ | Carbapenem-resistant |
| resistance_genes | string（逗号分隔） | ✅ | OXA-23,TEM-1 |
| infection_type | string | ✅ | VAP |
| infection_site | string | ✅ | Lung |
| specimen_type | string | ✅ | BALF |
| verification_status | string | ✅ | MICROBIOLOGY_LAB_VERIFIED |
| patient_age_group | string | 否 | 55-65 |
| comorbidities | string（逗号分隔） | 否 | COPD,DM |
| prior_antibiotics | string（逗号分隔） | 否 | Meropenem,Colistin |
| phage_treatment | string | 否 | Cocktail: φA+φB, 雾化吸入 |
| clinical_outcome | string | 否 | Clinical improvement at Day 7 |
| microbiological_outcome | string | 否 | 菌量下降3log |
| curated_by | string | 否 | FDE-01 |
| curation_date | string | 否 | 2026-08-15 |

## 1.2 phage_interactions.csv

| 字段名 | 类型 | 必填 | 示例 |
|--------|------|------|------|
| phage_id | string | ✅ | PHAGE-001 |
| phage_name | string | ✅ | vB_AbaM_AbTZI |
| family | string | 否 | Myoviridae |
| receptor_target | string | 否 | Capsular polysaccharide |
| pathogen_id | string | ✅ | PATH-001 |
| infection_result | string | 否 | Lytic |
| infection_probability | float | 否 | 0.94 |
| evidence_level | enum | ✅ | L1 |
| evidence_ref | string（逗号分隔） | 否 | PMID:12345678 |
| notes | string | 否 | — |

# 二、数据模型（Ontology）

## 2.1 实体定义（4个节点标签）

### Pathogen（病原菌）

| 属性                 | 类型         | 必填 | 说明         | 示例                      |
| -------------------- | ------------ | ---- | ------------ | ------------------------- |
| pathogen_id          | String       | ✅    | 唯一标识     | PATH-001                  |
| species              | String       | ✅    | 菌种名称     | Acinetobacter baumannii   |
| resistance_mechanism | String       | ✅    | 耐药机制大类 | Carbapenem-resistant      |
| resistance_genes     | List[String] | ✅    | 具体耐药基因 | ["OXA-23", "TEM-1"]       |
| ST_type              | String       | ❌    | MLST 分型    | ST2                       |
| verification_status  | String       | ✅    | 验证状态     | MICROBIOLOGY_LAB_VERIFIED |

---

### Phage（噬菌体）

| 属性             | 类型         | 必填 | 说明           | 示例                    |
| ---------------- | ------------ | ---- | -------------- | ----------------------- |
| phage_id         | String       | ✅    | 唯一标识       | PHAGE-001               |
| name             | String       | ✅    | 噬菌体名称     | vB_AbaM_AbTZI           |
| family           | String       | ❌    | 分类科属       | Myoviridae              |
| receptor_target  | String       | ❌    | 靶向受体       | Capsular polysaccharide |
| lifecycle        | String       | ❌    | 生命周期       | Lytic                   |
| safety_flags     | List[String] | ❌    | 安全标记       | ["no_toxin_genes"]      |
| genome_accession | String       | ❌    | GenBank 登录号 | NC_048XXX               |

---

### PhageHostInteraction（噬菌体-宿主互作）

| 属性                  | 类型         | 必填 | 说明                      | 示例                           |
| --------------------- | ------------ | ---- | ------------------------- | ------------------------------ |
| interaction_id        | String       | ✅    | 唯一标识                  | PHI-001                        |
| phage_id              | String       | ✅    | 关联 Phage.phage_id       | PHAGE-001                      |
| pathogen_id           | String       | ✅    | 关联 Pathogen.pathogen_id | PATH-001                       |
| infection_result      | String       | ❌    | 感染结果                  | Lytic / No infection / Partial |
| infection_probability | Float        | ❌    | 感染概率 0-1              | 0.94                           |
| evidence_level        | Enum         | ✅    | L1-L5                     | L2                             |
| evidence_ref          | List[String] | ❌    | 证据来源 PMID/CaseID      | ["PMID:12345678"]              |
| notes                 | String       | ❌    | 备注                      | —                              |

---

### ClinicalCase（临床病例）

| 属性                    | 类型         | 必填 | 说明                      | 示例                          |
| ----------------------- | ------------ | ---- | ------------------------- | ----------------------------- |
| case_id                 | String       | ✅    | 唯一标识（去标识化）      | CASE-001                      |
| pathogen_id             | String       | ✅    | 关联 Pathogen.pathogen_id | PATH-001                      |
| infection_type          | String       | ✅    | 感染类型                  | VAP                           |
| infection_site          | String       | ✅    | 感染部位                  | Lung                          |
| specimen_type           | String       | ✅    | 标本类型                  | BALF                          |
| patient_age_group       | String       | ❌    | 年龄段                    | 55-65                         |
| comorbidities           | List[String] | ❌    | 基础疾病                  | ["COPD", "DM"]                |
| prior_antibiotics       | List[String] | ❌    | 既往抗生素                | ["Meropenem", "Colistin"]     |
| phage_treatment         | String       | ❌    | 噬菌体治疗方案            | Cocktail: φA+φB, 雾化吸入     |
| clinical_outcome        | String       | ❌    | 临床结局                  | Clinical improvement at Day 7 |
| microbiological_outcome | String       | ❌    | 微生物学结局              | 菌量下降3log                  |
| curated_by              | String       | ❌    | 策展人标识                | FDE-01                        |
| curation_date           | Date         | ❌    | 策展日期                  | 2026-08-15                    |

---

## 2.2 关系类型（4种）

| 关系              | 方向                            | 含义                   |
| ----------------- | ------------------------------- | ---------------------- |
| HAS_INTERACTION   | Phage → PhageHostInteraction    | 噬菌体具有一条互作记录 |
| TARGETS           | PhageHostInteraction → Pathogen | 该互作记录针对某病原菌 |
| INVOLVES_PATHOGEN | ClinicalCase → Pathogen         | 病例涉及某病原菌感染   |
| TREATED_WITH      | ClinicalCase → Phage            | 病例使用了某噬菌体治疗 |

---

## 2.3 Cypher DDL（建约束和索引）

```cypher
// 约束
CREATE CONSTRAINT IF NOT EXISTS FOR (p:Pathogen) REQUIRE p.pathogen_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (p:Phage) REQUIRE p.phage_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (phi:PhageHostInteraction) REQUIRE phi.interaction_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (c:ClinicalCase) REQUIRE c.case_id IS UNIQUE;

// 索引（加速查询）
CREATE INDEX IF NOT EXISTS FOR (p:Pathogen) ON (p.species);
CREATE INDEX IF NOT EXISTS FOR (p:Pathogen) ON (p.resistance_mechanism);
CREATE INDEX IF NOT EXISTS FOR (c:ClinicalCase) ON (c.infection_type);
CREATE INDEX IF NOT EXISTS FOR (phi:PhageHostInteraction) ON (phi.evidence_level);
```

## 2.4 常用 Cypher 查询

### 1. 查询匹配的噬菌体

根据病原菌物种和耐药机制，返回评分最高的噬菌体及其互作信息（按证据等级和感染概率降序排列）。

```cypher
MATCH (ph:Phage)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)-[:TARGETS]->(p:Pathogen)
WHERE p.species = $species
  AND p.resistance_mechanism = $resistance
RETURN ph.*, phi.*
ORDER BY phi.evidence_level DESC, phi.infection_probability DESC
LIMIT 20

### 2. 查询相似病例

根据病原菌物种和感染类型，检索相关病例及其使用的噬菌体（以列表形式返回）。

```cypher
MATCH (c:ClinicalCase)-[:INVOLVES_PATHOGEN]->(p:Pathogen)
WHERE p.species = $species
  AND c.infection_type = $infection_type
OPTIONAL MATCH (c)-[:TREATED_WITH]->(ph:Phage)
RETURN c.*, collect(ph.name) AS phages_used
ORDER BY c.case_id DESC
LIMIT 5

### 3. 查询病例的所有噬菌体治疗记录

根据病例 ID，获取该病例使用过的所有噬菌体名称列表。

```cypher
MATCH (c:ClinicalCase {case_id: $case_id})
OPTIONAL MATCH (c)-[:TREATED_WITH]->(ph:Phage)
RETURN c.case_id, collect(ph.name) AS phage_names

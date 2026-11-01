# Ontology Schema 文档骨架

> 本文件由 `python scripts/generate_ontology_docs.py` 自动生成。
> 请领域专家在「定义（待补充）」列填入中文定义。

## 节点标签（Node Labels）

| 节点标签 | 定义（待补充） |
|---|---|
| Any | |
| AuditEvent | |
| BiofilmAssay | |
| ClinicalCase | |
| ClinicalIndication | |
| ClinicalTrial | |
| CompetitorAssessment | |
| ControlledTerm | |
| ControlledVocabulary | |
| DecisionBrief | |
| DecisionOption | |
| DecisionRecord | |
| DeliveryPayload | |
| DevelopmentProgram | |
| Dict | |
| Driver | |
| EngineeredPhageConstruct | |
| EngineeringModification | |
| EngineeringStrategy | |
| EnzymeGene | |
| EvalLog | |
| EvidenceUpgradeProposal | |
| ExperimentBatch | |
| HostStrain | |
| IntelligenceEvent | |
| IntelligenceProduct | |
| IntelligenceQuestion | |
| IntelligenceSignal | |
| IntelligenceUseEvent | |
| KnowledgeReuseEvent | |
| KnowledgeRule | |
| LysisAssay | |
| OntologyModule | |
| Organization | |
| PatentFamily | |
| Pathogen | |
| Patient | |
| Phage | |
| ProductAsset | |
| Review | |
| SchemaVersion | |
| ScientificEvidencePackage | |
| ScientificKnowledgeRule | |
| SourceArtifact | |
| TechnicalClaim | |
| TechnicalResult | |
| TechnologyAssessment | |
| WatchlistItem | |

## 关系类型（Relationship Types）

| 关系类型 | 定义（待补充） |
|---|---|
| ABOUT | |
| ADDRESSES | |
| AFFECTS | |
| AFFECTS_INTERNAL_PROGRAM | |
| ANSWERS | |
| ASSESSES | |
| ASSOCIATED_WITH | |
| BASED_ON | |
| BELONGS_TO | |
| BELONGS_TO_BATCH | |
| BELONGS_TO_PATIENT | |
| CARRIES_PAYLOAD | |
| CITES | |
| CITES_SOURCE | |
| CLAIMS_ABOUT | |
| CONSUMES | |
| CONTRADICTS | |
| COVERED_BY | |
| COVERS | |
| DEGRADES | |
| DEPENDS_ON | |
| DERIVED_FROM | |
| DEVELOPED_BY | |
| DEVELOPS | |
| DISPLAYS | |
| ENGINEERED_FROM | |
| EVALUATED_BY | |
| GENERATED_SIGNAL | |
| HAS_ISOLATE | |
| HAS_MODIFICATION | |
| HAS_SOURCE | |
| HAS_TRIAL | |
| HAS_VALIDATED_RULE | |
| IMPLEMENTS | |
| INCLUDES_ASSESSMENT | |
| INCLUDES_CANDIDATE | |
| INVOLVES | |
| INVOLVES_PATHOGEN | |
| IS_STRAIN_OF | |
| MAPS_TO | |
| OPTION_FOR | |
| OWNS_ASSET | |
| OWNS_OR_CONTROLS | |
| OWNS_PATENT | |
| PARTNERS_WITH | |
| PRECEDED_BY | |
| PROMOTED_TO | |
| RECOMMENDS_PHAGE | |
| REFERENCES_CASE | |
| REPORTED_IN | |
| RESULT_FOR | |
| REUSES | |
| REVIEWS | |
| SOURCE_CASE | |
| SPONSORS | |
| SUPPORTED_BY | |
| SUPPORTED_OR_CHALLENGES | |
| TARGETS | |
| TARGETS_PACKAGE | |
| TARGETS_PATHOGEN | |
| TESTED_AGAINST | |
| TREATED_WITH | |
| TRIGGERS | |
| USED_IN | |
| USES_ASSAY | |
| USES_CLAIM | |
| USES_CONSTRUCT | |
| USES_EVENT | |
| USES_RESULT | |
| USES_STRATEGY | |
| WATCHES | |

## 关系矩阵（人工补充）

| 关系类型 | 主语 | 宾语 | 说明 | 是否候选收敛 |
|---|---|---|---|---|
| TARGETS_PACKAGE | KnowledgeReuseEvent | ScientificEvidencePackage | 复用事件指向证据包 | 待 P2 评估 |
| TARGETS_PATHOGEN | DevelopmentProgram | Pathogen | 开发项目靶向病原 | 待 P2 评估 |
| TARGETS | EngineeredPhageConstruct | Pathogen | 构建体靶向病原 | 待 P2 评估 |


# v0.8 修复说明与规划中项

> 本文件替代 v0.8 PRD 中分散的 `docs/planned_nodes.md`，统一记录：
> - R-09 PhageHostInteraction 的处理
> - R-10 同义关系的处理结论
> - R-11 Graph Schema v2 的核查结论
> - 各修复项与 `scripts/v08_tools.py` 子命令的对应关系
>
> 最后更新：v0.8.0-EXP

---

## 一、修复项与工具对应表

| PRD 编号 | 修复内容 | 落地位置 |
|---|---|---|
| R-02 | 生成本体文档骨架 | `python scripts/v08_tools.py docs` → `docs/ontology_schema.md` |
| R-05 | 验证 requirements 版本 | `python scripts/v08_tools.py requirements` |
| R-07 | 验收脚本引入断言 | `tests/test_v08_acceptance.py` |
| R-08 | legacy 依赖分离 | `python scripts/v08_tools.py legacy` |
| R-09 | 移除 PhageHostInteraction | `src/foundation/schema.py` + 本文第二节 |
| R-10 | 同义关系处理 | 本文第三节（v0.8 不做破坏性合并） |
| R-11 | Graph Schema v2 核查 | `python scripts/v08_tools.py schema` + 本文第四节 |

---

## 二、R-09：PhageHostInteraction 已移除

- **原状**：`src/foundation/schema.py` 中定义 `interaction_id_unique` 唯一约束，但全仓库无任何写入代码，节点从未被创建。
- **v0.8 处理**：从 `create_schema()` 中移除该约束。
- **替代方案**：噬菌体 × 宿主互作通过 `(Phage)-[:USED_IN]->(LysisAssay)-[:TESTED_AGAINST]->(HostStrain)` 表达，不再需要独立节点。
- **如需恢复**：请在实现写入逻辑后，重新在 `create_schema()` 中添加约束，并同步更新本文件。

---

## 三、R-10：同义关系不做破坏性合并

| 关系 | 主语 | 宾语 | 说明 | 是否候选收敛 |
|---|---|---|---|---|
| `TARGETS_PACKAGE` | `KnowledgeReuseEvent` | `ScientificEvidencePackage` | 复用事件指向证据包 | 待 P2 评估 |
| `TARGETS_PATHOGEN` | `DevelopmentProgram` | `Pathogen` | 开发项目靶向病原 | 待 P2 评估 |
| `TARGETS` | `EngineeredPhageConstruct` | `Pathogen` | 构建体靶向病原 | 待 P2 评估 |

**v0.8 结论**：不合并。原因：

1. 三者主语和宾语类型不同，直接合并为 `TARGETS {target_type}` 会丢失主语类型约束；
2. `TARGETS_PATHOGEN` 在以下位置被使用，合并需要同步迁移：
   - `ai_assistant.py` 的 `SCHEMA_PROMPT` 和 `未关联` 路由
   - `knowledge_graph.py` 静态图
   - `queries.py` 的 `list_programs`
   - `program_service.py` 的 `create_development_program`
3. `TARGETS_PACKAGE` 在 `evidence_packages.py`、`retriever_service.py`、`knowledge_graph.py` 中被使用；
4. `TARGETS` 在 `construct_service.py`、`strategies.py`、`technology_brief.py` 中被使用。

**建议**：在 P2 本体分离阶段，统一迁移为 `TARGETS {target_type}`，并同步更新上述所有调用点和 `SCHEMA_PROMPT`。

---

## 四、R-11：Graph Schema v2 核查结论

### 4.1 已在本仓库落地的 v2 节点

| 节点 | 落地位置 | 状态 |
|---|---|---|
| `EnzymeGene` | `pages/scientific/enzyme_gene.py`、`ai_assistant.py`、`knowledge_graph.py`、`pages/admin/schema.py` | ✅ 已实现 |
| `BiofilmAssay` | `pages/scientific/biofilm_assay.py`、`ai_assistant.py`、`knowledge_graph.py`、`pages/admin/schema.py` | ✅ 已实现 |
| `ExperimentBatch` | `pages/admin/experiment_batch.py`、`ai_assistant.py`、`knowledge_graph.py`、`pages/admin/schema.py` | ✅ 已实现 |
| `SchemaVersion` | `pages/admin/schema_registry.py`、`src/foundation/schema.py` | ✅ 已实现 |

### 4.2 已在本仓库落地的 v2 关系

| 关系 | 落地位置 | 状态 |
|---|---|---|
| `ENGINEERED_FROM` | `phage_library.py`、`knowledge_graph.py`、`ai_assistant.py` | ✅ 已实现 |
| `DISPLAYS` | `phage_library.py`、`knowledge_graph.py`、`ai_assistant.py` | ✅ 已实现 |
| `DEGRADES` | `knowledge_graph.py`、`ai_assistant.py` | ✅ 已实现 |
| `BELONGS_TO_BATCH` | `enzyme_gene.py`、`biofilm_assay.py`、`experiment_batch.py`、`ai_assistant.py` | ✅ 已实现 |
| `PRECEDED_BY` | `biofilm_assay.py`、`schema_registry.py` | ✅ 已实现 |

### 4.3 待确认项

- 交接材料描述的 Phage 新增 9 个字段，当前仓库实际使用：`is_engineered`、`engineering_status`、`engineering_method`、`parent_phage_id`、`regulatory_status`。其余字段若在交接材料中存在但代码未实现，请在此逐条补充并标注「规划中」。
- 建议每次 schema 变更后运行 `python scripts/v08_tools.py schema`，把零命中项同步到本文件。

---

## 五、R-07 验收断言说明

`tests/test_v08_acceptance.py` 是 R-07 的**最小可用起点**，覆盖：

- LysisAssay 必填字段
- LysisAssay 证据等级合法值
- Pathogen ID 格式
- Phage 受体靶点非空
- LysisAssay result_value 范围
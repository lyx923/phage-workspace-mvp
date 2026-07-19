# 关联噬菌（测试跨病例复用分析）
// 1. 关联噬菌体到 CASE-003
MATCH (c:ClinicalCase {case_id: 'CASE-003'})
MATCH (ph1:Phage {name: 'CP-p-BC-23086'})
MATCH (ph2:Phage {name: 'CP-p-BC-23062'})
MERGE (c)-[:TREATED_WITH]->(ph1)
MERGE (c)-[:TREATED_WITH]->(ph2)

// 2. 同时更新 phage_treatment 字段
SET c.phage_treatment = 'CP-p-BC-23086, CP-p-BC-23062'

// 3. 验证是否成功
RETURN c.case_id, c.phage_treatment, [(c)-[:TREATED_WITH]->(ph) | ph.name] AS phages_used
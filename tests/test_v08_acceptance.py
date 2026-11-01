# tests/test_v08_acceptance.py
"""
R-07 最小可用起点：把 acceptance_stage2.py 中的关键检查点改写为 pytest assert。

v0.8 修正：
- PRD 示例中的 @pytest.fixure 拼写错误已改为 @pytest.fixture；
- PRD 示例中 pattern = r"\\^[A-Z]+-\\d{8}-\\d{3}$" 的转义错误已修正为 r"^[A-Z]+-\\d{8}-\\d{3}$"；
- fixture 直接放在本文件，不依赖 conftest.py，减少文件数；
- 增加 result_value 范围检查。
"""
import re

import pytest


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def mock_pathogen():
    return {
        "pathogen_id": "PATH-20241001-001",
        "species": "Klebsiella pneumoniae",
        "taxonomy_id": "573",
    }


@pytest.fixture
def mock_phage():
    return {
        "phage_id": "PHAGE-20241001-001",
        "name": "PhageK-test",
        "family": "Myoviridae",
        "receptor_target": "LPS",
    }


@pytest.fixture
def mock_lysis_assay(mock_pathogen, mock_phage):
    return {
        "assay_id": "ASSAY-20241001-001",
        "result": "positive",
        "result_value": 0.95,
        "evidence_level": "L2",
        "qc_status": "passed",
        "phage_id": mock_phage["phage_id"],
        "host_strain_id": "HOST-20241001-001",
    }


# ============================================================
# 断言
# ============================================================
def test_lysis_assay_has_required_fields(mock_lysis_assay):
    required = {"assay_id", "result", "result_value", "evidence_level", "qc_status"}
    missing = required - set(mock_lysis_assay.keys())
    assert not missing, f"LysisAssay 缺少必填字段: {missing}"


def test_lysis_assay_evidence_level_valid(mock_lysis_assay):
    valid_levels = {"L1", "L2", "L3", "L4", "L5"}
    assert mock_lysis_assay["evidence_level"] in valid_levels, (
        f"evidence_level 值 {mock_lysis_assay['evidence_level']} 不在允许范围 {valid_levels}"
    )


def test_pathogen_id_format(mock_pathogen):
    pattern = r"^[A-Z]+-\d{8}-\d{3}$"
    assert re.match(pattern, mock_pathogen["pathogen_id"]), (
        f"pathogen_id {mock_pathogen['pathogen_id']} 不符合格式 {{PREFIX}}-{{YYYYMMDD}}-{{3位}}"
    )


def test_phage_has_receptor_target(mock_phage):
    assert mock_phage.get("receptor_target"), "Phage 缺少 receptor_target 字段"


def test_lysis_assay_result_value_range(mock_lysis_assay):
    value = mock_lysis_assay.get("result_value")
    assert value is not None, "LysisAssay 缺少 result_value"
    assert 0.0 <= float(value) <= 1.0, f"result_value 应在 [0,1] 区间，当前为 {value}"
"""Query 预处理器：语言检测、医学术语标准化、同义词扩展、Multi-Query 生成。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langdetect import detect, LangDetectException

from ..utils.logging import setup_logging

logger = setup_logging("clinatlas.retrieval.preprocessor")

# ── 医学术语标准化词典 ────────────────────────────────────────────────────────
# 格式：口语/缩写 → 标准写法（中英文对照，便于多语言检索）
_TERM_NORMALIZATION: dict[str, str] = {
    # 中文缩略 → 标准
    "心梗":   "急性心肌梗死",
    "脑梗":   "脑梗死",
    "高血压": "原发性高血压",
    "糖尿病": "糖尿病",
    "感冒":   "上呼吸道感染",
    "肺炎":   "肺炎",
    "胃炎":   "胃炎",
    "肾衰":   "急性肾功能衰竭",
    # 英文缩写 → 全称
    "DM":     "Diabetes Mellitus 糖尿病",
    "HTN":    "Hypertension 高血压",
    "AMI":    "Acute Myocardial Infarction 急性心肌梗死",
    "COPD":   "Chronic Obstructive Pulmonary Disease 慢性阻塞性肺疾病",
    "CHF":    "Congestive Heart Failure 充血性心力衰竭",
    "AKI":    "Acute Kidney Injury 急性肾损伤",
    "CVA":    "Cerebrovascular Accident 脑血管意外",
    "DVT":    "Deep Vein Thrombosis 深静脉血栓",
    "PE":     "Pulmonary Embolism 肺栓塞",
    "UTI":    "Urinary Tract Infection 尿路感染",
    "CAP":    "Community-Acquired Pneumonia 社区获得性肺炎",
    "T2DM":   "Type 2 Diabetes Mellitus 2型糖尿病",
    "T1DM":   "Type 1 Diabetes Mellitus 1型糖尿病",
    "ICU":    "Intensive Care Unit 重症监护室",
}

# ── 同义词扩展词典 ────────────────────────────────────────────────────────────
_SYNONYMS: dict[str, list[str]] = {
    "用法用量":     ["给药剂量", "用药方法", "dosage", "administration"],
    "禁忌症":       ["禁忌证", "contraindications", "禁用情况"],
    "适应症":       ["适应证", "indications", "适用范围"],
    "不良反应":     ["副作用", "adverse effects", "side effects"],
    "注意事项":     ["用药须知", "precautions", "使用警告"],
    "胰岛素":       ["insulin", "胰岛素注射"],
    "抗生素":       ["抗菌药物", "antibiotics", "抗生素类药物"],
    "手术":         ["外科手术", "operation", "surgery"],
    "dosage":       ["用法用量", "给药剂量", "administration"],
    "contraindications": ["禁忌症", "禁忌证"],
}

# Multi-Query 模板：围绕原始 query 生成角度不同的变体
_MULTI_QUERY_TEMPLATES = [
    "{query}",
    "{query} 临床指南 规范",
    "{query} 注意事项 禁忌",
]


@dataclass
class ProcessedQuery:
    original: str
    normalized: str
    language: str
    expanded_terms: list[str]
    multi_queries: list[str]


def _detect_language(text: str) -> str:
    """检测文本语言，失败时返回 'unknown'。"""
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"


def _normalize_terms(text: str) -> str:
    """把口语/缩写替换为标准医学术语。"""
    result = text
    for abbr, full in _TERM_NORMALIZATION.items():
        # 全词匹配，避免误替换子串（如 PE 在 COPD 中误触发）
        result = re.sub(rf"\b{re.escape(abbr)}\b", full, result)
    return result


def _expand_synonyms(text: str) -> list[str]:
    """提取文本中出现的医学词条的同义词列表。"""
    extra: list[str] = []
    for term, synonyms in _SYNONYMS.items():
        if term.lower() in text.lower():
            extra.extend(s for s in synonyms if s.lower() not in text.lower())
    return list(dict.fromkeys(extra))  # 去重保序


def _generate_multi_queries(normalized: str) -> list[str]:
    """基于模板生成多个检索变体，扩大召回面。"""
    queries = []
    for template in _MULTI_QUERY_TEMPLATES:
        q = template.format(query=normalized).strip()
        if q not in queries:
            queries.append(q)
    return queries


def preprocess_query(raw_query: str) -> ProcessedQuery:
    """
    Query 预处理主入口。

    步骤：语言检测 → 术语标准化 → 同义词扩展 → Multi-Query 生成
    """
    raw_query = raw_query.strip()
    language = _detect_language(raw_query)
    normalized = _normalize_terms(raw_query)
    expanded_terms = _expand_synonyms(normalized)
    multi_queries = _generate_multi_queries(normalized)

    logger.info(
        "Query 预处理完成",
        extra={
            "lang": language,
            "original": raw_query,
            "multi_query_count": len(multi_queries),
            "expanded_terms": len(expanded_terms),
        },
    )
    return ProcessedQuery(
        original=raw_query,
        normalized=normalized,
        language=language,
        expanded_terms=expanded_terms,
        multi_queries=multi_queries,
    )

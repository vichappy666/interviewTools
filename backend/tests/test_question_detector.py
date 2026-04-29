"""Unit tests for :class:`app.question_detector.QuestionDetector` (M2 T7)。

覆盖：问号判定 / 特征词 / 长度门槛 / 空 / None / 前后空白。
"""
from __future__ import annotations

from app.question_detector import QuestionDetector


def _detector() -> QuestionDetector:
    """默认参数：min_chars=6。"""
    return QuestionDetector()


def test_question_mark_chinese():
    d = _detector()
    assert d.feed("什么是 React？") == "什么是 React？"


def test_question_mark_english():
    d = _detector()
    assert d.feed("what is react?") == "what is react?"


def test_keyword_what():
    d = _detector()
    # 没有问号但含"什么"
    assert d.feed("什么是 React 的 useEffect") == "什么是 React 的 useEffect"


def test_keyword_how():
    d = _detector()
    assert d.feed("怎么实现快排") == "怎么实现快排"


def test_too_short_no_match():
    d = _detector()
    # 1 个字，达不到 min_chars=6
    assert d.feed("好") is None


def test_too_short_question_mark_no_match():
    d = _detector()
    # 哪怕带 ?，长度不够也不算
    assert d.feed("好？") is None


def test_no_keyword_no_mark():
    d = _detector()
    # 普通陈述句，无问号无特征词
    assert d.feed("我今天去吃饭了") is None


def test_empty_string():
    d = _detector()
    assert d.feed("") is None


def test_none_input():
    d = _detector()
    assert d.feed(None) is None


def test_strip_whitespace():
    d = _detector()
    # 前后空白会被 strip 掉，返回去掉空白的文本
    # （注意：strip 后长度仍需 ≥ min_chars=6 才会被判定）
    assert d.feed("  什么是闭包？  ") == "什么是闭包？"

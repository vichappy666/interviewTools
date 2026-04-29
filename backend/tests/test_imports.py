"""烟雾测试：保证搬迁的模块都能 import，不抛异常。
M0 阶段只测 import 不测业务逻辑。"""


def test_asr_volcengine_imports():
    from app.asr import volcengine  # noqa: F401


def test_llm_imports():
    from app import llm  # noqa: F401


def test_question_detector_imports():
    from app import question_detector  # noqa: F401


def test_stream_parser_imports():
    from app import stream_parser  # noqa: F401

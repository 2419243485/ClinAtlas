"""ClinAtlas 在线检索侧。

对外暴露主入口 retrieve_and_answer，完整链路封装在 orchestrator 中。
"""

from .orchestrator import retrieve_and_answer, RetrievalResult

__all__ = ["retrieve_and_answer", "RetrievalResult"]

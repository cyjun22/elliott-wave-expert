"""
Elliott Wave Analysis Package
=============================
범용 엘리엇 파동 분석 시스템 (하이브리드: Algorithm + LLM + RAG)
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from .core import ElliottWaveAnalyzer, WaveAnalysis
    from .patterns import PatternType, PatternRecognizer, Wave, Pivot
    from .validation import WaveValidator
    from .targets import TargetCalculator
except ImportError:
    # 패키지 컨텍스트 없이 직접 실행/임포트 시 (예: pytest에서)
    pass

# Hybrid Expert (LLM + RAG)
try:
    from .hybrid_expert import HybridElliottExpert, HybridAnalysisResult
    from .llm_validator import LLMWaveValidator, ValidationResult, CycleEstimate
    HYBRID_AVAILABLE = True
except ImportError as e:
    _logger.warning("Hybrid/LLM modules not available: %s", e)
    HYBRID_AVAILABLE = False
    HybridElliottExpert = None
    LLMWaveValidator = None

__all__ = [
    # 기본
    'ElliottWaveAnalyzer',
    'WaveAnalysis',
    'PatternType',
    'PatternRecognizer',
    'WaveValidator',
    'TargetCalculator',
    'Wave',
    'Pivot',
    # 하이브리드
    'HybridElliottExpert',
    'HybridAnalysisResult',
    'LLMWaveValidator',
    'HYBRID_AVAILABLE',
]

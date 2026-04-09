"""
Elliott Wave Pattern Recognition Tests
=======================================
All 12 pattern types tested with synthetic data
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elliott_wave.patterns import (
    PatternRecognizer, PatternType, WaveDirection,
    Wave, Pivot, WaveDegree, PatternMatch
)
from datetime import datetime, timedelta


@pytest.fixture
def recognizer():
    return PatternRecognizer()


# ===== Helper =====

def _pivots(price_list, start_day=0, step=20):
    """가격 리스트에서 교대 피벗(high/low) 생성"""
    pivots = []
    for i, price in enumerate(price_list):
        ptype = "low" if i % 2 == 0 else "high"
        pivots.append(Pivot(
            price=price,
            timestamp=datetime(2025, 1, 1) + timedelta(days=start_day + i * step),
            pivot_type=ptype,
            index=i
        ))
    return pivots


def _has_pattern(results, pattern_type):
    """결과 리스트에서 특정 패턴 타입 존재 여부"""
    return any(r.pattern_type == pattern_type for r in results)


def _get_pattern(results, pattern_type):
    """결과 리스트에서 특정 패턴 매치 추출"""
    for r in results:
        if r.pattern_type == pattern_type:
            return r
    return None


# ===== 1. Impulse (충격파) =====

class TestImpulse:

    def test_impulse_bullish(self, recognizer, bullish_impulse_pivots):
        """교과서적 상승 충격파 인식"""
        results = recognizer.recognize(bullish_impulse_pivots, WaveDirection.UP)
        assert _has_pattern(results, PatternType.IMPULSE)
        match = _get_pattern(results, PatternType.IMPULSE)
        assert match.confidence >= 0.6
        assert len(match.violations) == 0

    def test_impulse_bearish(self, recognizer, bearish_impulse_pivots):
        """하락 충격파 인식"""
        results = recognizer.recognize(bearish_impulse_pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.IMPULSE)
        match = _get_pattern(results, PatternType.IMPULSE)
        assert match.confidence >= 0.5

    def test_impulse_w3_shortest_violation(self, recognizer, make_pivot):
        """Wave 3이 가장 짧으면 신뢰도 감소"""
        pivots = [
            make_pivot(100, 0, "low"),
            make_pivot(250, 30, "high"),   # W1: 150
            make_pivot(160, 50, "low"),
            make_pivot(220, 80, "high"),   # W3: 60 ← 가장 짧음
            make_pivot(180, 100, "low"),
            make_pivot(350, 130, "high"),  # W5: 170
        ]
        results = recognizer.recognize(pivots, WaveDirection.UP)
        match = _get_pattern(results, PatternType.IMPULSE)
        assert match is not None
        assert any("shortest" in v.lower() for v in match.violations)
        assert match.confidence < 0.6

    def test_impulse_w4_overlap_violation(self, recognizer, make_pivot):
        """Wave 4가 Wave 1 영역 침범시 impulse 신뢰도 감소"""
        pivots = [
            make_pivot(100, 0, "low"),
            make_pivot(200, 30, "high"),   # W1 고점 = 200
            make_pivot(120, 50, "low"),
            make_pivot(350, 80, "high"),
            make_pivot(180, 100, "low"),   # W4 < W1 고점(200) → 침범
            make_pivot(400, 130, "high"),
        ]
        results = recognizer.recognize(pivots, WaveDirection.UP)
        match = _get_pattern(results, PatternType.IMPULSE)
        assert match is not None
        assert any("overlap" in v.lower() for v in match.violations)


# ===== 2. Leading Diagonal (선행 대각선) =====

class TestLeadingDiagonal:

    def test_leading_diagonal_basic(self, recognizer, make_pivot):
        """선행 대각선: W4-W1 중첩, 점진 축소"""
        pivots = [
            make_pivot(100, 0, "low"),
            make_pivot(200, 20, "high"),   # W1: 100
            make_pivot(130, 40, "low"),    # W2
            make_pivot(210, 60, "high"),   # W3: 80 (< W1)
            make_pivot(160, 80, "low"),    # W4 < W1 고점 → 중첩!
            make_pivot(220, 100, "high"),  # W5: 60 (< W3)
        ]
        results = recognizer.recognize(pivots, WaveDirection.UP)
        assert _has_pattern(results, PatternType.LEADING_DIAGONAL)
        match = _get_pattern(results, PatternType.LEADING_DIAGONAL)
        assert 0.30 <= match.confidence <= 0.90


# ===== 3. Ending Diagonal (종결 대각선) =====

class TestEndingDiagonal:

    def test_ending_diagonal_contracting(self, recognizer, make_pivot):
        """종결 대각선 (수렴형): W4-W1 중첩, 크기 감소"""
        pivots = [
            make_pivot(300, 0, "low"),
            make_pivot(400, 20, "high"),   # W1: 100
            make_pivot(340, 40, "low"),    # W2
            make_pivot(410, 60, "high"),   # W3: 70
            make_pivot(370, 80, "low"),    # W4 < W1 고점(400) → 중첩
            make_pivot(420, 100, "high"),  # W5: 50 (< W3)
        ]
        results = recognizer.recognize(pivots, WaveDirection.UP)
        assert _has_pattern(results, PatternType.ENDING_DIAGONAL)
        match = _get_pattern(results, PatternType.ENDING_DIAGONAL)
        assert match.confidence >= 0.40


# ===== 4. Zigzag (지그재그) =====

class TestZigzag:

    def test_zigzag_standard(self, recognizer, zigzag_pivots):
        """표준 지그재그 ABC"""
        results = recognizer.recognize(zigzag_pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.ZIGZAG)
        match = _get_pattern(results, PatternType.ZIGZAG)
        assert match.confidence >= 0.6

    def test_zigzag_b_retrace_in_range(self, recognizer, make_pivot):
        """B파 되돌림이 38.2-78.6% 범위 내일 때 높은 신뢰도"""
        pivots = [
            make_pivot(500, 0, "high"),
            make_pivot(300, 30, "low"),    # A: 200 하락
            make_pivot(400, 50, "high"),   # B: 100 반등 (50%)
            make_pivot(150, 80, "low"),    # C: 250 하락
        ]
        results = recognizer.recognize(pivots, WaveDirection.DOWN)
        match = _get_pattern(results, PatternType.ZIGZAG)
        assert match is not None
        assert match.confidence >= 0.7


# ===== 5. Double Zigzag (이중 지그재그) =====

class TestDoubleZigzag:

    def test_double_zigzag_wxy(self, recognizer, make_pivot):
        """WXY 이중 지그재그: 8개 피벗"""
        pivots = [
            make_pivot(500, 0, "high"),    # W-A 시작
            make_pivot(350, 20, "low"),    # W-A 끝
            make_pivot(420, 35, "high"),   # W-B 끝
            make_pivot(300, 55, "low"),    # W-C 끝
            make_pivot(380, 70, "high"),   # X 끝 (되돌림)
            make_pivot(250, 90, "low"),    # Y-A 끝
            make_pivot(310, 105, "high"),  # Y-B 끝
            make_pivot(150, 130, "low"),   # Y-C 끝
        ]
        results = recognizer.recognize(pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.DOUBLE_ZIGZAG)
        match = _get_pattern(results, PatternType.DOUBLE_ZIGZAG)
        assert match.confidence >= 0.35


# ===== 6. Triple Zigzag (삼중 지그재그) =====

class TestTripleZigzag:

    def test_triple_zigzag_wxyxz(self, recognizer, make_pivot):
        """WXYXZ 삼중 지그재그: 12개 피벗"""
        pivots = [
            make_pivot(1000, 0, "high"),   # W-A start
            make_pivot(800, 15, "low"),    # W-A end
            make_pivot(900, 25, "high"),   # W-B end
            make_pivot(700, 40, "low"),    # W-C end
            make_pivot(800, 55, "high"),   # X1 end
            make_pivot(600, 70, "low"),    # Y-A end
            make_pivot(700, 85, "high"),   # Y-B end
            make_pivot(500, 100, "low"),   # Y-C end
            make_pivot(600, 115, "high"),  # X2 end
            make_pivot(400, 130, "low"),   # Z-A end
            make_pivot(480, 145, "high"),  # Z-B end
            make_pivot(300, 165, "low"),   # Z-C end
        ]
        results = recognizer.recognize(pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.TRIPLE_ZIGZAG)
        match = _get_pattern(results, PatternType.TRIPLE_ZIGZAG)
        assert 0.25 <= match.confidence <= 0.70


# ===== 7. Flat (레귤러 플랫) =====

class TestFlat:

    def test_flat_regular(self, recognizer, flat_pivots):
        """레귤러 플랫: B ≈ 90-105% of A start"""
        results = recognizer.recognize(flat_pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.FLAT)
        match = _get_pattern(results, PatternType.FLAT)
        assert match.confidence >= 0.5


# ===== 8. Expanded Flat (확장형 플랫) =====

class TestExpandedFlat:

    def test_expanded_flat(self, recognizer, make_pivot):
        """확장형 플랫: B > A start (>105%), C > A end"""
        pivots = [
            make_pivot(400, 0, "high"),    # A start
            make_pivot(300, 30, "low"),    # A end
            make_pivot(440, 60, "high"),   # B end (110% of A start → expanded)
            make_pivot(250, 90, "low"),    # C end (깊은 조정)
        ]
        results = recognizer.recognize(pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.EXPANDED_FLAT)
        match = _get_pattern(results, PatternType.EXPANDED_FLAT)
        assert match.confidence >= 0.45


# ===== 9. Running Flat (러닝 플랫) =====

class TestRunningFlat:

    def test_running_flat(self, recognizer, make_pivot):
        """러닝 플랫: B > A start, C < A (끝점 미달)"""
        pivots = [
            make_pivot(400, 0, "high"),    # A start
            make_pivot(320, 30, "low"),    # A end (80 하락)
            make_pivot(450, 60, "high"),   # B end (>105% of A start)
            make_pivot(350, 90, "low"),    # C end (C size=100 < A size=80? No→ C=100, A=80 → C>A)
        ]
        # C 크기가 A보다 크면 running flat이 아님
        # Running flat: C < A → 다시 조정
        pivots_rf = [
            make_pivot(400, 0, "high"),
            make_pivot(330, 30, "low"),    # A end (A size: 70)
            make_pivot(440, 60, "high"),   # B end (110% of A start)
            make_pivot(380, 90, "low"),    # C end (C size: 60 < A size: 70 → running)
        ]
        results = recognizer.recognize(pivots_rf, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.RUNNING_FLAT)
        match = _get_pattern(results, PatternType.RUNNING_FLAT)
        assert match.confidence >= 0.40


# ===== 10. Triangle (삼각형) =====

class TestTriangle:

    def test_triangle_converging(self, recognizer, make_pivot):
        """수렴형 삼각형: ABCDE 5파, 크기 감소, 방향 교대"""
        pivots = [
            make_pivot(300, 0, "high"),    # A start
            make_pivot(200, 20, "low"),    # A end (100)
            make_pivot(280, 40, "high"),   # B end (80)
            make_pivot(220, 60, "low"),    # C end (60)
            make_pivot(260, 80, "high"),   # D end (40)
            make_pivot(235, 100, "low"),   # E end (25)
        ]
        results = recognizer.recognize(pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.TRIANGLE)
        match = _get_pattern(results, PatternType.TRIANGLE)
        assert match.confidence >= 0.50


# ===== 11. Complex (복합 조정) =====

class TestComplex:

    def test_complex_wxy(self, recognizer, make_pivot):
        """WXY 복합 조정: 8개 피벗"""
        pivots = [
            make_pivot(500, 0, "high"),
            make_pivot(380, 15, "low"),    # W (zigzag part 1)
            make_pivot(430, 30, "high"),
            make_pivot(320, 50, "low"),    # W end
            make_pivot(400, 65, "high"),   # X (connector)
            make_pivot(280, 80, "low"),    # Y (flat part 1)
            make_pivot(340, 95, "high"),
            make_pivot(200, 120, "low"),   # Y end
        ]
        results = recognizer.recognize(pivots, WaveDirection.DOWN)
        assert _has_pattern(results, PatternType.COMPLEX)
        match = _get_pattern(results, PatternType.COMPLEX)
        assert 0.25 <= match.confidence <= 0.75


# ===== 12. Unknown (미확정) =====

class TestUnknown:

    def test_unknown_fallback(self, recognizer, make_pivot):
        """매칭 패턴 없으면 UNKNOWN 반환"""
        # 2개 피벗 — 어떤 패턴에도 불충분
        pivots = [
            make_pivot(100, 0, "low"),
            make_pivot(200, 30, "high"),
        ]
        results = recognizer.recognize(pivots, WaveDirection.UP)
        assert len(results) >= 1
        assert results[0].pattern_type == PatternType.UNKNOWN
        assert results[0].confidence == 0.20

    def test_insufficient_pivots_3(self, recognizer, make_pivot):
        """3개 피벗 — zigzag/flat 미달"""
        pivots = [
            make_pivot(100, 0, "low"),
            make_pivot(200, 20, "high"),
            make_pivot(150, 40, "low"),
        ]
        results = recognizer.recognize(pivots, WaveDirection.UP)
        # 어떤 패턴에도 미달 → UNKNOWN이 있어야 함
        assert any(r.pattern_type == PatternType.UNKNOWN for r in results)

    def test_empty_pivots(self, recognizer):
        """빈 피벗 리스트"""
        results = recognizer.recognize([], WaveDirection.UP)
        assert len(results) >= 1
        assert results[0].pattern_type == PatternType.UNKNOWN


# ===== Cross-cutting =====

class TestPatternDescription:

    def test_all_types_have_descriptions(self, recognizer):
        """모든 12개 PatternType에 설명이 존재"""
        for pt in PatternType:
            desc = recognizer.get_pattern_description(pt)
            assert isinstance(desc, str)
            assert len(desc) > 5, f"Description too short for {pt}"

    def test_recognize_returns_sorted(self, recognizer, bullish_impulse_pivots):
        """결과가 신뢰도 내림차순으로 정렬"""
        results = recognizer.recognize(bullish_impulse_pivots, WaveDirection.UP)
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

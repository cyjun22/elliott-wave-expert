"""
Elliott Wave Validation Tests
=============================
validation.py — 규칙 위반 감지, 신뢰도 패널티, 무효화 레벨 테스트
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elliott_wave.patterns import PatternType, Wave, Pivot, WaveDegree, WaveDirection
from elliott_wave.validation import ValidationResult, WaveValidator

from datetime import datetime, timedelta


@pytest.fixture
def validator():
    return WaveValidator()


# ===== Helper =====

def _wave(start_price, end_price, start_day, end_day, label="1"):
    """간단한 Wave 생성 헬퍼"""
    start_type = "low" if end_price > start_price else "high"
    end_type = "high" if end_price > start_price else "low"
    return Wave(
        start=Pivot(
            price=start_price,
            timestamp=datetime(2025, 1, 1) + timedelta(days=start_day),
            pivot_type=start_type,
            index=start_day
        ),
        end=Pivot(
            price=end_price,
            timestamp=datetime(2025, 1, 1) + timedelta(days=end_day),
            pivot_type=end_type,
            index=end_day
        ),
        label=label,
        degree=WaveDegree.INTERMEDIATE
    )


# ===== Impulse Validation =====

class TestImpulseValidation:

    def test_valid_impulse_full_confidence(self, validator):
        """규칙/가이드라인 모두 충족 → 높은 신뢰도"""
        waves = [
            _wave(100, 200, 0, 20, "1"),    # W1: 100
            _wave(200, 150, 20, 40, "2"),    # W2: 50 (50% 되돌림)
            _wave(150, 350, 40, 80, "3"),    # W3: 200 (가장 김)
            _wave(350, 250, 80, 100, "4"),   # W4: 100 (W1 영역 침범 없음: 250 > 200)
            _wave(250, 400, 100, 130, "5"),  # W5: 150
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        assert result.is_valid is True
        assert len(result.violations) == 0
        assert result.confidence >= 0.75  # 가이드라인도 대부분 충족

    def test_rule1_wave2_100pct_retrace(self, validator):
        """Rule 1: Wave 2가 Wave 1의 100% 이상 되돌림 → 위반"""
        waves = [
            _wave(100, 200, 0, 20, "1"),    # W1 시작=100
            _wave(200, 90, 20, 40, "2"),     # W2 끝=90 < W1 시작=100 → 위반
            _wave(90, 300, 40, 80, "3"),
            _wave(300, 210, 80, 100, "4"),
            _wave(210, 350, 100, 130, "5"),
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        assert any("Rule 1" in v for v in result.violations)
        assert result.confidence < 0.7

    def test_rule2_wave3_shortest(self, validator):
        """Rule 2: Wave 3이 가장 짧음 → 위반"""
        waves = [
            _wave(100, 250, 0, 20, "1"),    # W1: 150
            _wave(250, 180, 20, 40, "2"),    # W2: 70
            _wave(180, 220, 40, 80, "3"),    # W3: 40 ← 가장 짧음
            _wave(220, 200, 80, 100, "4"),   # W4: 20
            _wave(200, 300, 100, 130, "5"),  # W5: 100
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        assert any("Rule 2" in v for v in result.violations)
        assert result.confidence < 0.6

    def test_rule3_wave4_overlap(self, validator):
        """Rule 3: Wave 4가 Wave 1 영역 침범 → 위반"""
        waves = [
            _wave(100, 200, 0, 20, "1"),    # W1 끝=200
            _wave(200, 150, 20, 40, "2"),
            _wave(150, 350, 40, 80, "3"),
            _wave(350, 180, 80, 100, "4"),   # W4 끝=180 < W1 끝=200 → 침범
            _wave(180, 400, 100, 130, "5"),
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        assert any("Rule 3" in v for v in result.violations)
        assert result.confidence < 0.8

    def test_guideline_wave3_not_longest(self, validator):
        """가이드라인: Wave 3이 가장 길지 않음 → -5% 패널티"""
        waves = [
            _wave(100, 250, 0, 20, "1"),    # W1: 150
            _wave(250, 160, 20, 40, "2"),    # W2: 90 (60% retrace)
            _wave(160, 280, 40, 80, "3"),    # W3: 120 (W1보다 짧음, W5보다도 짧을 때)
            _wave(280, 260, 80, 100, "4"),   # W4: 20 (W1 위)
            _wave(260, 500, 100, 130, "5"),  # W5: 240 (가장 김)
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        # W3(120) < W1(150) and W3(120) < W5(240) → 가이드라인 경고
        assert any("not longest" in w.lower() for w in result.warnings)

    def test_guideline_wave2_retrace_outside_range(self, validator):
        """가이드라인: Wave 2 되돌림이 38.2-78.6% 밖 → -10% 패널티"""
        waves = [
            _wave(100, 200, 0, 20, "1"),    # W1: 100
            _wave(200, 195, 20, 40, "2"),    # W2: 5 → 5% 되돌림 (< 38.2%)
            _wave(195, 400, 40, 80, "3"),    # W3: 205
            _wave(400, 250, 80, 100, "4"),   # W4: 150 (250 > W1 끝 200)
            _wave(250, 450, 100, 130, "5"),  # W5: 200
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        assert any("retracement" in w.lower() for w in result.warnings)
        # 이 가이드라인 위반만 있어도 confidence < 1.0
        assert result.confidence < 1.0

    def test_guideline_wave3_weak_momentum(self, validator):
        """가이드라인: Wave 3 모멘텀이 Wave 1의 80% 미만 → -10% 패널티"""
        waves = [
            _wave(100, 300, 0, 20, "1"),    # W1: 200
            _wave(300, 200, 20, 40, "2"),    # W2: 100 (50% retrace)
            _wave(200, 330, 40, 80, "3"),    # W3: 130 (< 200*0.8=160 → 약한 모멘텀) — but W3 shortest?
            _wave(330, 310, 80, 100, "4"),   # W4: 20
            _wave(310, 500, 100, 130, "5"),  # W5: 190
        ]
        # W3(130) is shortest (W1=200, W5=190) → Rule 2 violation
        # 대신 W3가 W1의 80% 미만인 경우만 따로 테스트
        waves2 = [
            _wave(100, 200, 0, 20, "1"),    # W1: 100
            _wave(200, 140, 20, 40, "2"),    # W2: 60 (60% retrace)
            _wave(140, 210, 40, 80, "3"),    # W3: 70 (< 100*0.8=80 → 약한 모멘텀) — shortest too
            _wave(210, 205, 80, 100, "4"),   # W4: 5
            _wave(205, 350, 100, 130, "5"),  # W5: 145
        ]
        # W3(70) < W1(100) & W3(70) < W5(145) → Rule 2 triggers too
        # 모멘텀 가이드라인은 W3.size < W1.size * 0.8일 때 발동
        # W3=70, W1=100 → 70 < 80 → 모멘텀 경고 발동
        result = validator.validate(waves2, PatternType.IMPULSE)
        assert any("momentum" in w.lower() for w in result.warnings)

    def test_insufficient_waves(self, validator):
        """파동 < 5개 → 검증 실패"""
        waves = [
            _wave(100, 200, 0, 20, "1"),
            _wave(200, 150, 20, 40, "2"),
            _wave(150, 300, 40, 80, "3"),
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        assert result.is_valid is False
        assert result.confidence == 0.0

    def test_no_penalty_valid_pattern(self, validator):
        """완벽한 충격파 → 규칙 위반 0, 높은 신뢰도"""
        waves = [
            _wave(100, 200, 0, 20, "1"),    # W1: 100
            _wave(200, 140, 20, 40, "2"),    # W2: 60 (60% retrace ✓)
            _wave(140, 400, 40, 80, "3"),    # W3: 260 (가장 김 ✓, 모멘텀 강 ✓)
            _wave(400, 250, 80, 100, "4"),   # W4: 150 (250 > 200 ✓ 침범 없음)
            _wave(250, 450, 100, 130, "5"),  # W5: 200
        ]
        result = validator.validate(waves, PatternType.IMPULSE)
        assert result.is_valid is True
        assert len(result.violations) == 0
        assert result.confidence >= 0.85
        assert result.invalidation_level == 100  # W1 시작가


# ===== Zigzag Validation =====

class TestZigzagValidation:

    def test_valid_zigzag(self, validator):
        """유효한 지그재그 → 높은 신뢰도"""
        waves = [
            _wave(400, 250, 0, 30, "A"),     # A: 150 하락
            _wave(250, 330, 30, 50, "B"),     # B: 80 반등 (53% 되돌림)
            _wave(330, 150, 50, 80, "C"),     # C: 180 하락 (A와 같은 방향)
        ]
        result = validator.validate(waves, PatternType.ZIGZAG)
        assert result.is_valid is True
        assert result.confidence >= 0.6

    def test_zigzag_b_retrace_low(self, validator):
        """B파 되돌림 < 38.2% → 경고"""
        waves = [
            _wave(400, 200, 0, 30, "A"),     # A: 200 하락
            _wave(200, 240, 30, 50, "B"),     # B: 40 반등 (20% 되돌림 < 38.2%)
            _wave(240, 100, 50, 80, "C"),     # C: 140 하락
        ]
        result = validator.validate(waves, PatternType.ZIGZAG)
        assert any("38.2%" in w for w in result.warnings)

    def test_zigzag_insufficient_waves(self, validator):
        """파동 < 3개 → 검증 실패"""
        waves = [
            _wave(400, 250, 0, 30, "A"),
            _wave(250, 330, 30, 50, "B"),
        ]
        result = validator.validate(waves, PatternType.ZIGZAG)
        assert result.is_valid is False


# ===== Flat Validation =====

class TestFlatValidation:

    def test_regular_flat(self, validator):
        """레귤러 플랫 검증"""
        waves = [
            _wave(400, 300, 0, 30, "A"),     # A: 100 하락
            _wave(300, 385, 30, 60, "B"),     # B: 85 반등 (96.25% of A start)
            _wave(385, 280, 60, 90, "C"),     # C: 105 하락
        ]
        result = validator.validate(waves, PatternType.FLAT)
        assert result.is_valid is True
        assert result.confidence >= 0.5

    def test_flat_insufficient_waves(self, validator):
        """파동 < 3개 → 검증 실패"""
        waves = [_wave(400, 300, 0, 30, "A")]
        result = validator.validate(waves, PatternType.FLAT)
        assert result.is_valid is False


# ===== Invalidation Level =====

class TestInvalidationLevel:

    def test_impulse_invalidation(self, validator):
        """충격파 무효화 레벨 = Wave 1 시작가"""
        waves = [
            _wave(100, 200, 0, 20, "1"),
            _wave(200, 150, 20, 40, "2"),
            _wave(150, 350, 40, 80, "3"),
            _wave(350, 250, 80, 100, "4"),
            _wave(250, 400, 100, 130, "5"),
        ]
        level = validator.get_invalidation_level(waves, PatternType.IMPULSE)
        assert level == 100  # W1 시작가

    def test_zigzag_invalidation(self, validator):
        """지그재그 무효화 레벨 = A파 시작가"""
        waves = [
            _wave(400, 250, 0, 30, "A"),
            _wave(250, 330, 30, 50, "B"),
            _wave(330, 150, 50, 80, "C"),
        ]
        level = validator.get_invalidation_level(waves, PatternType.ZIGZAG)
        assert level == 400  # A 시작가

    def test_empty_waves_invalidation(self, validator):
        """빈 파동 → None"""
        level = validator.get_invalidation_level([], PatternType.IMPULSE)
        assert level is None


# ===== Other Pattern Types =====

class TestOtherPatterns:

    def test_unimplemented_pattern_default(self, validator):
        """미구현 패턴 → 기본 검증 결과 (valid, 0.5 confidence)"""
        waves = [_wave(100, 200, 0, 20, "1")]
        result = validator.validate(waves, PatternType.TRIANGLE)
        assert result.is_valid is True
        assert result.confidence == 0.5
        assert any("not implemented" in w.lower() for w in result.warnings)

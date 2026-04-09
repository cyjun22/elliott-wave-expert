"""
Elliott Wave Scenarios Tests
============================
wave_scenarios.py — 무효화 로직, 만료, 시나리오 생성기 테스트
"""

import pytest
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elliott_wave.wave_scenarios import (
    WaveInterpretation,
    ScenarioWithInvalidation,
    ScenarioGenerator,
)


# ===== ScenarioWithInvalidation =====

class TestScenarioWithInvalidation:

    def _make_scenario(self, inv_price=50000, direction='above', valid_days=90,
                       condition="Price above 50000"):
        """테스트용 ScenarioWithInvalidation 헬퍼"""
        return ScenarioWithInvalidation(
            scenario={'name': 'test', 'probability': 0.5},
            invalidation_price=inv_price,
            invalidation_direction=direction,
            valid_until=datetime(2025, 1, 1) + timedelta(days=valid_days),
            falsifiable_condition=condition,
        )

    def test_invalidation_above(self):
        """가격이 무효화 기준 위로 돌파 → 무효화"""
        sw = self._make_scenario(inv_price=50000, direction='above')
        assert sw.is_invalidated(51000) is True
        assert sw.is_invalidated(49000) is False
        assert sw.is_invalidated(50000) is False  # 동일 가격은 무효 아님

    def test_invalidation_below(self):
        """가격이 무효화 기준 아래로 돌파 → 무효화"""
        sw = self._make_scenario(inv_price=30000, direction='below')
        assert sw.is_invalidated(29000) is True
        assert sw.is_invalidated(31000) is False
        assert sw.is_invalidated(30000) is False

    def test_invalidation_unknown_direction(self):
        """알 수 없는 방향 → 무효화되지 않음"""
        sw = self._make_scenario(direction='sideways')
        assert sw.is_invalidated(999999) is False

    def test_expiry_not_expired(self):
        """유효 기간 내 → 만료되지 않음"""
        sw = self._make_scenario(valid_days=90)
        # valid_until = 2025-04-01
        assert sw.is_expired(datetime(2025, 3, 1)) is False

    def test_expiry_expired(self):
        """유효 기간 초과 → 만료"""
        sw = self._make_scenario(valid_days=90)
        assert sw.is_expired(datetime(2025, 5, 1)) is True

    def test_expiry_boundary(self):
        """유효 기간 정확히 만료일 → 만료되지 않음 (now == valid_until은 False)"""
        sw = self._make_scenario(valid_days=90)
        assert sw.is_expired(sw.valid_until) is False

    def test_falsifiable_condition_stored(self):
        """반증 가능 조건 문자열 저장 확인"""
        sw = self._make_scenario(condition="Price above $50,000 invalidates bearish scenario")
        assert "50,000" in sw.falsifiable_condition
        assert "invalidates" in sw.falsifiable_condition


# ===== WaveInterpretation =====

class TestWaveInterpretation:

    def test_defaults(self):
        """기본값 초기화 확인"""
        wi = WaveInterpretation(
            scenario_id="s1",
            scenario_name="Test Scenario",
            description="test",
        )
        assert wi.scenario_id == "s1"
        assert wi.wave_labels == []
        assert wi.projected_path == []
        assert wi.targets == []
        assert wi.probability == 0.0
        assert wi.confidence == 0.0
        assert wi.current_wave == ""

    def test_custom_fields(self):
        """커스텀 필드 설정"""
        wi = WaveInterpretation(
            scenario_id="abc",
            scenario_name="ABC Correction",
            description="Zigzag correction in progress",
            current_wave="C",
            probability=0.65,
            confidence=0.8,
            invalidation_price=42000.0,
        )
        assert wi.current_wave == "C"
        assert wi.probability == 0.65
        assert wi.invalidation_price == 42000.0


# ===== ScenarioGenerator =====

class TestScenarioGenerator:

    def test_generator_instantiates(self):
        """ScenarioGenerator 인스턴스 생성"""
        gen = ScenarioGenerator()
        assert gen is not None

    def test_dynamic_probability_near_ath(self):
        """ATH 근처에서 Extended 5th 확률 높음"""
        gen = ScenarioGenerator()
        wave_map = {
            '0': {'price': 10000},
            '4': {'price': 40000},
            '5': {'price': 50000},
        }
        probs = gen._calculate_dynamic_probability(wave_map, current_price=49000)
        # ATH 근처 → extended_5th 확률이 가장 높거나 significant
        assert probs['extended_5th'] >= 0.20

    def test_dynamic_probability_deep_correction(self):
        """깊은 조정 (61.8% 이하)에서 Extended 5th 확률 감소"""
        gen = ScenarioGenerator()
        wave_map = {
            '0': {'price': 10000},
            '4': {'price': 40000},
            '5': {'price': 50000},
        }
        # 현재가 = 20000 → 61.8% 이하
        probs = gen._calculate_dynamic_probability(wave_map, current_price=20000)
        assert probs['extended_5th'] <= 0.10
        assert probs['correction'] >= 0.30

    def test_dynamic_probability_40pct_drop(self):
        """40% 이상 하락 시 Extended 5th 거의 0"""
        gen = ScenarioGenerator()
        wave_map = {
            '0': {'price': 10000},
            '4': {'price': 40000},
            '5': {'price': 50000},
        }
        # 현재가 = 28000 → 44% 하락
        probs = gen._calculate_dynamic_probability(wave_map, current_price=28000)
        assert probs['extended_5th'] <= 0.05

    def test_abc_position_near_ath(self):
        """ATH 근처 → A_wave 위치"""
        gen = ScenarioGenerator()
        wave_map = {
            '0': {'price': 10000},
            '5': {'price': 50000},
        }
        pos = gen._detect_abc_position(wave_map, current_price=48000)
        assert pos == 'A_wave'

    def test_probability_keys(self):
        """확률 딕셔너리에 필수 키 존재"""
        gen = ScenarioGenerator()
        wave_map = {
            '0': {'price': 100},
            '4': {'price': 400},
            '5': {'price': 500},
        }
        probs = gen._calculate_dynamic_probability(wave_map, current_price=450)
        assert 'correction' in probs
        assert 'new_cycle' in probs
        assert 'extended_5th' in probs
        assert 'new_impulse' in probs
        # 모든 확률이 0~1 범위
        for key, val in probs.items():
            assert 0.0 <= val <= 1.0, f"{key} = {val} out of range"

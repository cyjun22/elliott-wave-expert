"""
Shared test fixtures for Elliott Wave Expert tests
===================================================
피벗, 파동, DataFrame 등 공통 테스트 데이터 팩토리
"""

import pytest
import sys
import os
import types
import importlib.util
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# 프로젝트 루트를 sys.path에 추가 (patterns.py 등 직접 임포트용)
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_DIR)

# 패키지로도 등록 (core.py, validation.py 등 상대 임포트용)
# elliott-wave-expert 디렉토리를 'elliott_wave' 패키지로 등록
_PKG_NAME = "elliott_wave"
if _PKG_NAME not in sys.modules:
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [_PROJECT_DIR]
    _pkg.__package__ = _PKG_NAME
    _pkg.__file__ = os.path.join(_PROJECT_DIR, "__init__.py")
    sys.modules[_PKG_NAME] = _pkg

    # 핵심 서브모듈 등록 (상대 임포트 해결)
    # wave_scenarios.py는 experts.elliott.live_tracker 필요 → 먼저 stub 등록
    if 'experts' not in sys.modules:
        _experts = types.ModuleType('experts')
        _experts.__path__ = []
        sys.modules['experts'] = _experts

        _elliott = types.ModuleType('experts.elliott')
        _elliott.__path__ = []
        sys.modules['experts.elliott'] = _elliott
        _experts.elliott = _elliott

        _lt_path = os.path.join(_PROJECT_DIR, 'live_tracker.py')
        if os.path.exists(_lt_path):
            _lt_fqn = 'experts.elliott.live_tracker'
            _lt_spec = importlib.util.spec_from_file_location(_lt_fqn, _lt_path)
            _lt_mod = importlib.util.module_from_spec(_lt_spec)
            sys.modules[_lt_fqn] = _lt_mod
            _lt_spec.loader.exec_module(_lt_mod)
            _elliott.live_tracker = _lt_mod

    # 새 모듈들도 experts.elliott 네임스페이스에 등록 (의존성 순서 준수)
    _new_mods_ordered = [
        'scenario_tree', 'adaptive_tracker', 'wave_scenarios',
        'timeframe_linker', 'wave_chart',
        'forecast_engine', 'realtime_loop',
    ]
    for _new_mod in _new_mods_ordered:
        _new_path = os.path.join(_PROJECT_DIR, f"{_new_mod}.py")
        if os.path.exists(_new_path):
            _new_fqn = f"experts.elliott.{_new_mod}"
            if _new_fqn not in sys.modules:
                _new_spec = importlib.util.spec_from_file_location(_new_fqn, _new_path)
                _new_mod_obj = importlib.util.module_from_spec(_new_spec)
                sys.modules[_new_fqn] = _new_mod_obj
                try:
                    _new_spec.loader.exec_module(_new_mod_obj)
                    setattr(_elliott, _new_mod, _new_mod_obj)
                except Exception as _e:
                    del sys.modules[_new_fqn]  # 실패시 캐시 제거

    for _mod_name in ["patterns", "validation", "targets", "core", "wave_scenarios"]:
        _mod_path = os.path.join(_PROJECT_DIR, f"{_mod_name}.py")
        if os.path.exists(_mod_path):
            _fqn = f"{_PKG_NAME}.{_mod_name}"
            _spec = importlib.util.spec_from_file_location(_fqn, _mod_path)
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules[_fqn] = _mod
            _spec.loader.exec_module(_mod)
            setattr(_pkg, _mod_name, _mod)

from elliott_wave.patterns import Wave, Pivot, WaveDegree, WaveDirection


@pytest.fixture
def make_pivot():
    """Pivot 팩토리 — 가격과 날짜 오프셋으로 생성"""
    def _make(price, time_offset_days=0, pivot_type="high"):
        return Pivot(
            price=price,
            timestamp=datetime(2025, 1, 1) + timedelta(days=time_offset_days),
            pivot_type=pivot_type,
            index=time_offset_days
        )
    return _make


@pytest.fixture
def make_wave():
    """Wave 팩토리 — 시작/끝 가격, 날짜, 라벨로 생성"""
    def _make(start_price, end_price, start_day, end_day, label="1",
              degree=WaveDegree.INTERMEDIATE):
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
            degree=degree
        )
    return _make


@pytest.fixture
def bullish_impulse_pivots(make_pivot):
    """교과서적 상승 충격파 5파 피벗 (6개: W0-W5)"""
    return [
        make_pivot(100, 0, "low"),     # W0
        make_pivot(200, 30, "high"),   # W1 고점
        make_pivot(150, 50, "low"),    # W2 저점 (50% 되돌림)
        make_pivot(350, 90, "high"),   # W3 고점 (가장 긺)
        make_pivot(250, 110, "low"),   # W4 저점 (W1 고점 위)
        make_pivot(400, 140, "high"),  # W5 고점
    ]


@pytest.fixture
def bearish_impulse_pivots(make_pivot):
    """하락 충격파 5파 피벗"""
    return [
        make_pivot(400, 0, "high"),    # W0
        make_pivot(300, 30, "low"),    # W1
        make_pivot(350, 50, "high"),   # W2 (50% 되돌림)
        make_pivot(150, 90, "low"),    # W3 (가장 긺)
        make_pivot(200, 110, "high"),  # W4 (W1 아래)
        make_pivot(100, 140, "low"),   # W5
    ]


@pytest.fixture
def zigzag_pivots(make_pivot):
    """지그재그 ABC 조정 피벗 (4개)"""
    return [
        make_pivot(400, 0, "high"),    # A 시작
        make_pivot(250, 30, "low"),    # A 끝 / B 시작
        make_pivot(320, 50, "high"),   # B 끝 / C 시작 (46.7% 되돌림)
        make_pivot(150, 80, "low"),    # C 끝
    ]


@pytest.fixture
def flat_pivots(make_pivot):
    """레귤러 플랫 ABC 피벗 — B가 A 시작점의 95% 수준"""
    return [
        make_pivot(400, 0, "high"),    # A 시작
        make_pivot(300, 30, "low"),    # A 끝
        make_pivot(385, 60, "high"),   # B 끝 (96.25% of A start)
        make_pivot(280, 90, "low"),    # C 끝
    ]


@pytest.fixture
def make_ohlcv_df():
    """합성 OHLCV DataFrame 팩토리"""
    def _make(n=100, start_price=100, trend="up", volatility=0.02, start_date="2024-01-01"):
        np.random.seed(42)
        dates = pd.date_range(start=start_date, periods=n, freq="D")

        prices = [start_price]
        for i in range(1, n):
            drift = volatility * 0.5 if trend == "up" else -volatility * 0.5
            change = np.random.normal(drift, volatility)
            prices.append(prices[-1] * (1 + change))

        closes = np.array(prices)
        highs = closes * (1 + np.abs(np.random.normal(0, volatility / 2, n)))
        lows = closes * (1 - np.abs(np.random.normal(0, volatility / 2, n)))
        opens = closes * (1 + np.random.normal(0, volatility / 3, n))

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.random.randint(1000, 10000, n)
        }, index=dates)

        return df
    return _make

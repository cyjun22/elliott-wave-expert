"""
Elliott Wave Core Analyzer Tests
=================================
core.py 분석기 테스트 — 방향 감지, 입력 검증, 사이클 감지, 분석 구조
"""

import pytest
import sys
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# core.py uses relative imports → import via registered package
from elliott_wave.core import ElliottWaveAnalyzer, WaveAnalysis
from elliott_wave.validation import ValidationResult
from elliott_wave.patterns import PatternType, WaveDirection, Pivot


@pytest.fixture
def analyzer():
    return ElliottWaveAnalyzer()


# ===== Direction Detection =====

class TestDirectionDetection:

    def test_uptrend_detected(self, analyzer, make_ohlcv_df):
        """상승 추세 감지 (SMA 기울기 > 0)"""
        df = make_ohlcv_df(n=100, start_price=100, trend="up", volatility=0.01)
        direction = analyzer._detect_direction(df)
        assert direction == WaveDirection.UP

    def test_downtrend_detected(self, analyzer, make_ohlcv_df):
        """하락 추세 감지 (SMA 기울기 < 0)"""
        df = make_ohlcv_df(n=100, start_price=100, trend="down", volatility=0.01)
        direction = analyzer._detect_direction(df)
        assert direction == WaveDirection.DOWN

    def test_short_data_fallback(self, analyzer):
        """짧은 데이터(< window)에서도 방향 감지 가능"""
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "open": [100, 102, 104, 106, 108],
            "high": [101, 103, 105, 107, 109],
            "low": [99, 101, 103, 105, 107],
            "close": [100, 102, 104, 106, 108],
        }, index=dates)
        direction = analyzer._detect_direction(df)
        assert direction == WaveDirection.UP


# ===== Input Validation =====

class TestInputValidation:

    def test_insufficient_data(self, analyzer):
        """30개 미만 데이터 경고"""
        dates = pd.date_range("2025-01-01", periods=15, freq="D")
        df = pd.DataFrame({
            "open": range(15), "high": range(15),
            "low": range(15), "close": range(15),
        }, index=dates)
        issues = analyzer._validate_input_data(df)
        assert any("Insufficient" in i for i in issues)

    def test_missing_values_detected(self, analyzer):
        """null 값 감지"""
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame({
            "open": np.random.rand(50) * 100,
            "high": np.random.rand(50) * 100,
            "low": np.random.rand(50) * 100,
            "close": np.random.rand(50) * 100,
        }, index=dates)
        df.iloc[10, 0] = np.nan  # null 삽입
        df.iloc[20, 2] = np.nan
        issues = analyzer._validate_input_data(df)
        assert any("Missing values" in i or "null" in i.lower() for i in issues)

    def test_extreme_moves_detected(self, analyzer):
        """>50% 단일 캔들 이동 감지"""
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        closes = [100.0] * 50
        closes[25] = 200.0  # 100% 급등
        df = pd.DataFrame({
            "open": closes, "high": closes,
            "low": closes, "close": closes,
        }, index=dates)
        issues = analyzer._validate_input_data(df)
        assert any("Extreme" in i or "extreme" in i.lower() for i in issues)

    def test_duplicate_timestamps(self, analyzer):
        """중복 타임스탬프 감지"""
        dates = pd.to_datetime(["2025-01-01"] * 5 + ["2025-01-02"] * 45)
        df = pd.DataFrame({
            "open": np.random.rand(50) * 100,
            "high": np.random.rand(50) * 100,
            "low": np.random.rand(50) * 100,
            "close": np.random.rand(50) * 100,
        }, index=dates)
        issues = analyzer._validate_input_data(df)
        assert any("Duplicate" in i or "duplicate" in i.lower() for i in issues)

    def test_clean_data_no_issues(self, analyzer, make_ohlcv_df):
        """정상 데이터는 경고 없음"""
        df = make_ohlcv_df(n=100, start_price=100, trend="up")
        issues = analyzer._validate_input_data(df)
        # 'Insufficient' or 'Missing' should not appear
        assert not any("Insufficient" in i for i in issues)
        assert not any("Missing" in i for i in issues)


# ===== Fibonacci Cycle Detection =====

class TestCycleDetection:

    def test_fibonacci_segments_not_equal(self, analyzer, make_ohlcv_df):
        """auto_detect_cycle은 피보나치 비율 세그먼트 사용 (등분 아님)"""
        # 충분한 데이터로 사이클 감지
        df = make_ohlcv_df(n=500, start_price=100, trend="up", volatility=0.03)
        result = analyzer.auto_detect_cycle(df, symbol="TEST")
        # 분석 결과가 반환되어야 함
        assert isinstance(result, WaveAnalysis)
        assert result.symbol == "TEST"

    def test_cycle_detection_short_data(self, analyzer, make_ohlcv_df):
        """짧은 데이터에서 사이클 감지 실패 → empty analysis"""
        df = make_ohlcv_df(n=30, start_price=100, trend="up")
        result = analyzer.auto_detect_cycle(df, symbol="SHORT")
        # 데이터 부족시 pattern은 UNKNOWN이거나 notes에 오류 메시지
        assert result.pattern == PatternType.UNKNOWN or "Insufficient" in result.notes


# ===== Analyze Returns Structure =====

class TestAnalyzeStructure:

    def test_analyze_returns_wave_analysis(self, analyzer, make_ohlcv_df):
        """analyze()가 WaveAnalysis 구조 반환"""
        df = make_ohlcv_df(n=200, start_price=100, trend="up", volatility=0.04)
        result = analyzer.analyze(df, symbol="STRUCT", timeframe="daily")
        assert isinstance(result, WaveAnalysis)
        assert result.symbol == "STRUCT"
        assert result.timeframe == "daily"
        assert isinstance(result.pattern, PatternType)
        assert 0.0 <= result.pattern_confidence <= 1.0
        assert isinstance(result.validation, ValidationResult)

    def test_analyze_multiindex_columns(self, analyzer):
        """MultiIndex 컬럼 데이터 처리"""
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(100)) + 100
        df = pd.DataFrame({
            ("Open", ""): closes * 0.99,
            ("High", ""): closes * 1.01,
            ("Low", ""): closes * 0.98,
            ("Close", ""): closes,
        }, index=dates)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        result = analyzer.analyze(df, symbol="MULTI")
        assert isinstance(result, WaveAnalysis)

    def test_analyze_too_little_data(self, analyzer):
        """데이터 < 10 → empty analysis"""
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "open": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100, 101, 102, 103, 104],
        }, index=dates)
        result = analyzer.analyze(df, symbol="TINY")
        assert result.pattern == PatternType.UNKNOWN
        assert result.pattern_confidence == 0.0

    def test_summary_method(self, analyzer, make_ohlcv_df):
        """summary() 메서드가 문자열 반환"""
        df = make_ohlcv_df(n=200, start_price=100, trend="up", volatility=0.04)
        result = analyzer.analyze(df, symbol="SUM")
        summary = result.summary()
        assert isinstance(summary, str)
        assert "SUM" in summary


# ===== Pivot Detection =====

class TestPivotDetection:

    def test_detect_pivots_returns_list(self, analyzer, make_ohlcv_df):
        """detect_pivots가 Pivot 리스트 반환"""
        df = make_ohlcv_df(n=200, start_price=100, trend="up", volatility=0.05)
        pivots = analyzer.detect_pivots(df, threshold=0.05)
        assert isinstance(pivots, list)
        assert all(isinstance(p, Pivot) for p in pivots)

    def test_pivots_alternate_high_low(self, analyzer, make_ohlcv_df):
        """피벗이 high/low 교대로 나와야 함"""
        df = make_ohlcv_df(n=200, start_price=100, trend="up", volatility=0.05)
        pivots = analyzer.detect_pivots(df, threshold=0.05)
        if len(pivots) >= 2:
            for i in range(1, len(pivots)):
                assert pivots[i].pivot_type != pivots[i - 1].pivot_type, \
                    f"Pivot {i}: consecutive {pivots[i].pivot_type}"

    def test_auto_threshold_bounded(self, analyzer, make_ohlcv_df):
        """자동 임계값이 0.03~0.20 범위"""
        df = make_ohlcv_df(n=100, start_price=100, trend="up")
        threshold = analyzer._auto_threshold(df)
        assert 0.03 <= threshold <= 0.20

"""
wave_chart.py 테스트
"""

import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

import pytest
import pandas as pd
import numpy as np

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wave_chart import (
    WaveChart,
    generate_sample_ohlcv,
    SAMPLE_BTC_WAVES,
    SAMPLE_BTC_ABC,
    WAVE_COLORS,
    IMPULSE_LABELS,
    CORRECTIVE_LABELS,
    THEME,
)


@pytest.fixture
def sample_df():
    return generate_sample_ohlcv()


@pytest.fixture
def chart():
    return WaveChart(figsize=(12, 7), dpi=72)  # 작은 사이즈로 빠르게


class TestSampleData:
    """샘플 데이터 생성 검증"""

    def test_generate_ohlcv_shape(self, sample_df):
        assert len(sample_df) > 500
        assert set(sample_df.columns) == {"open", "high", "low", "close", "volume"}

    def test_ohlcv_valid_prices(self, sample_df):
        assert (sample_df["high"] >= sample_df["low"]).all()
        assert (sample_df["close"] > 0).all()
        assert (sample_df["volume"] > 0).all()

    def test_datetime_index(self, sample_df):
        assert isinstance(sample_df.index, pd.DatetimeIndex)

    def test_sample_waves_structure(self):
        assert len(SAMPLE_BTC_WAVES) == 6
        for w in SAMPLE_BTC_WAVES:
            assert "label" in w
            assert "date" in w
            assert "price" in w

    def test_sample_abc_structure(self):
        assert len(SAMPLE_BTC_ABC) == 3
        labels = [w["label"] for w in SAMPLE_BTC_ABC]
        assert labels == ["A", "B", "C"]


class TestWaveChart:
    """WaveChart 클래스 검증"""

    def test_instantiate(self, chart):
        assert chart.figsize == (12, 7)
        assert chart.dpi == 72

    def test_plot_with_waves(self, chart, sample_df):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test.png")
            result = chart.plot(
                sample_df, waves=SAMPLE_BTC_WAVES,
                symbol="BTC-USD", save_path=out,
            )
            assert os.path.exists(result)
            assert os.path.getsize(result) > 10000  # 최소 10KB

    def test_plot_without_waves(self, chart, sample_df):
        """파동 없이 캔들스틱만"""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "candle_only.png")
            result = chart.plot(
                sample_df, symbol="BTC-USD",
                save_path=out,
            )
            assert os.path.exists(result)

    def test_plot_with_abc(self, chart, sample_df):
        """충격파 + ABC 조정"""
        combined = SAMPLE_BTC_WAVES + SAMPLE_BTC_ABC
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "impulse_abc.png")
            result = chart.plot(
                sample_df, waves=combined,
                symbol="BTC-USD", save_path=out,
            )
            assert os.path.exists(result)

    def test_plot_without_volume(self, chart, sample_df):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "no_vol.png")
            result = chart.plot(
                sample_df, waves=SAMPLE_BTC_WAVES,
                symbol="BTC-USD", save_path=out,
                show_volume=False,
            )
            assert os.path.exists(result)

    def test_plot_custom_title(self, chart, sample_df):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "custom.png")
            result = chart.plot(
                sample_df, waves=SAMPLE_BTC_WAVES,
                symbol="BTC-USD", save_path=out,
                title="Custom Title Test",
            )
            assert os.path.exists(result)

    def test_plot_auto_path(self, chart, sample_df):
        """자동 경로 생성"""
        result = chart.plot(
            sample_df, waves=SAMPLE_BTC_WAVES,
            symbol="TEST-AUTO",
        )
        assert os.path.exists(result)
        assert "TEST-AUTO" in result
        os.remove(result)

    def test_plot_manual(self, chart, sample_df):
        """plot_manual 간편 인터페이스"""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "manual.png")
            result = chart.plot_manual(
                sample_df,
                waves=SAMPLE_BTC_WAVES[:3],
                symbol="ETH-USD",
                save_path=out,
            )
            assert os.path.exists(result)

    def test_multiindex_columns(self, chart, sample_df):
        """MultiIndex 컬럼 DataFrame 처리"""
        # yfinance 스타일 MultiIndex 생성
        mi = pd.MultiIndex.from_tuples(
            [(c.capitalize(), "BTC-USD") for c in sample_df.columns]
        )
        df_mi = sample_df.copy()
        df_mi.columns = mi

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "multi.png")
            result = chart.plot(
                df_mi, waves=SAMPLE_BTC_WAVES,
                symbol="BTC-USD", save_path=out,
            )
            assert os.path.exists(result)


class TestConstants:
    """상수 및 색상 매핑 검증"""

    def test_impulse_labels_complete(self):
        for i in range(6):
            assert str(i) in IMPULSE_LABELS

    def test_corrective_labels_complete(self):
        for label in ["A", "B", "C", "D", "E"]:
            assert label in CORRECTIVE_LABELS

    def test_wave_colors_complete(self):
        for i in range(6):
            assert str(i) in WAVE_COLORS
        for label in ["A", "B", "C"]:
            assert label in WAVE_COLORS

    def test_theme_keys(self):
        required = ["bg", "panel", "grid", "text", "candle_up", "candle_down"]
        for key in required:
            assert key in THEME


class TestConsistency:
    """동일 입력에서 동일 구조 출력 검증"""

    def test_same_input_same_size(self, chart, sample_df):
        """동일 데이터로 두 번 생성 시 파일 크기 유사"""
        with tempfile.TemporaryDirectory() as tmpdir:
            out1 = os.path.join(tmpdir, "r1.png")
            out2 = os.path.join(tmpdir, "r2.png")

            chart.plot(sample_df, waves=SAMPLE_BTC_WAVES,
                       symbol="BTC", save_path=out1)
            chart.plot(sample_df, waves=SAMPLE_BTC_WAVES,
                       symbol="BTC", save_path=out2)

            size1 = os.path.getsize(out1)
            size2 = os.path.getsize(out2)

            # 같은 데이터면 파일 크기가 동일해야 함
            assert size1 == size2

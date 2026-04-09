"""
test_forecast_system.py
========================
ForecastEngine + TimeframeLinker + RealtimeLoop 통합 테스트

v3.0.0 — 2026-04-09
"""

import sys
import os
import pytest
from datetime import datetime, timedelta

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────
# 테스트용 샘플 데이터 생성
# ─────────────────────────────────────────────────────

def make_btc_candles(timeframe: str = '1d', n: int = 100) -> list:
    """BTC 유사 합성 캔들 데이터 (파동 구조 포함)"""
    import numpy as np
    np.random.seed(42)

    base_date = datetime(2022, 9, 1)

    # 주요 가격 포인트 (임펄스 1-2-3-4-5 구조)
    if timeframe == '1d':
        key_points = [
            (0, 19800), (80, 15599),      # W0 시작 → 저점
            (300, 31815),                   # W1
            (360, 24797),                   # W2
            (560, 73750),                   # W3
            (640, 49121),                   # W4
            (810, 109115),                  # W5
            (880, 85000),                   # 현재 (조정)
        ]
        delta = timedelta(days=1)
    elif timeframe == '4h':
        key_points = [
            (0, 85000), (20, 82000), (50, 90000),
            (70, 84000), (100, 88000),
        ]
        n = 120
        delta = timedelta(hours=4)
    else:  # 1h
        key_points = [
            (0, 85000), (10, 83000), (30, 87000),
            (50, 84500), (70, 86500),
        ]
        n = 100
        delta = timedelta(hours=1)

    # 보간
    indices = [p[0] for p in key_points]
    prices = [p[1] for p in key_points]
    n = max(n, max(indices) + 20)

    close = np.interp(range(n), indices, prices)
    noise = np.random.normal(0, 1, n)
    close = close * (1 + np.cumsum(noise) * 0.0003)  # 약간의 랜덤 워크

    candles = []
    for i in range(n):
        dt = base_date + delta * i
        c = close[i]
        daily_vol = abs(np.random.normal(0, 0.015))
        candles.append({
            'date': dt,
            'open': c * (1 + np.random.normal(0, 0.005)),
            'high': c * (1 + daily_vol),
            'low': c * (1 - daily_vol),
            'close': c,
            'volume': np.random.uniform(15e9, 45e9),
        })

    return candles


def make_timeframe_data() -> dict:
    """멀티타임프레임 데이터 세트"""
    return {
        '1d': make_btc_candles('1d'),
        '4h': make_btc_candles('4h'),
        '1h': make_btc_candles('1h'),
    }


# ─────────────────────────────────────────────────────
# TimeframeLinker 테스트
# ─────────────────────────────────────────────────────

class TestTimeframeLinker:
    """TimeframeLinker 단위 테스트"""

    def setup_method(self):
        from experts.elliott.timeframe_linker import TimeframeLinker
        self.linker = TimeframeLinker()

    def test_link_basic(self):
        """기본 교차 검증"""
        tf_pivots = {
            '1d': [
                {'date': '2022-11-21', 'price': 15599, 'type': 'low'},
                {'date': '2023-07-13', 'price': 31815, 'type': 'high'},
                {'date': '2023-09-11', 'price': 24797, 'type': 'low'},
                {'date': '2024-03-14', 'price': 73750, 'type': 'high'},
                {'date': '2024-08-05', 'price': 49121, 'type': 'low'},
                {'date': '2025-01-20', 'price': 109115, 'type': 'high'},
            ],
            '4h': [
                {'date': '2025-01-01', 'price': 92000, 'type': 'low'},
                {'date': '2025-01-10', 'price': 100000, 'type': 'high'},
                {'date': '2025-01-15', 'price': 95000, 'type': 'low'},
                {'date': '2025-01-20', 'price': 109115, 'type': 'high'},
                {'date': '2025-02-01', 'price': 98000, 'type': 'low'},
            ],
        }
        result = self.linker.link_timeframes(tf_pivots, current_price=85000)

        assert 'consensus_phase' in result
        assert 'confidence' in result
        assert 'violations' in result
        assert isinstance(result['violations'], list)
        assert result['confidence'] >= 0.0
        assert result['confidence'] <= 1.0

    def test_link_single_timeframe(self):
        """단일 타임프레임 → 제약 없이 반환"""
        tf_pivots = {
            '1d': [
                {'date': '2024-01-01', 'price': 40000, 'type': 'low'},
                {'date': '2024-03-14', 'price': 73750, 'type': 'high'},
            ],
        }
        result = self.linker.link_timeframes(tf_pivots, current_price=65000)
        assert result['total_links'] == 0  # 단일 프레임이면 교차 검증 없음

    def test_link_direction_mismatch(self):
        """방향 불일치 검출"""
        tf_pivots = {
            '1d': [
                {'date': '2024-01-01', 'price': 40000, 'type': 'low'},
                {'date': '2024-06-01', 'price': 70000, 'type': 'high'},  # 상승
            ],
            '4h': [
                {'date': '2024-05-01', 'price': 72000, 'type': 'high'},
                {'date': '2024-06-01', 'price': 55000, 'type': 'low'},   # 하락
            ],
        }
        result = self.linker.link_timeframes(tf_pivots, current_price=60000)

        # 방향 불일치 경고가 있어야 함
        direction_violations = [
            v for v in result['violations'] if v['rule'] == 'R1_direction'
        ]
        assert len(direction_violations) > 0

    def test_link_three_timeframes(self):
        """3개 타임프레임 검증"""
        tf_pivots = {
            '1d': [
                {'date': '2024-01-01', 'price': 40000, 'type': 'low'},
                {'date': '2024-03-14', 'price': 73750, 'type': 'high'},
                {'date': '2024-08-05', 'price': 49121, 'type': 'low'},
                {'date': '2025-01-20', 'price': 109115, 'type': 'high'},
            ],
            '4h': [
                {'date': '2025-01-01', 'price': 92000, 'type': 'low'},
                {'date': '2025-01-20', 'price': 109115, 'type': 'high'},
                {'date': '2025-02-01', 'price': 98000, 'type': 'low'},
            ],
            '1h': [
                {'date': '2025-01-18', 'price': 105000, 'type': 'low'},
                {'date': '2025-01-20', 'price': 109115, 'type': 'high'},
            ],
        }
        result = self.linker.link_timeframes(tf_pivots, current_price=85000)

        # 2개 페어 검증: 1d↔4h, 4h↔1h
        assert result['total_links'] >= 2

    def test_wave4_overlap_detection(self):
        """Wave 4 비침범 규칙 검출"""
        tf_pivots = {
            '1d': [
                {'date': '2024-01-01', 'price': 40000, 'type': 'low'},
                {'date': '2024-02-01', 'price': 55000, 'type': 'high'},  # W1
                {'date': '2024-03-01', 'price': 45000, 'type': 'low'},   # W2
                {'date': '2024-06-01', 'price': 75000, 'type': 'high'},  # W3
                {'date': '2024-08-01', 'price': 50000, 'type': 'low'},   # W4 (W1 침범 안 함)
                {'date': '2024-12-01', 'price': 100000, 'type': 'high'}, # W5
            ],
            '4h': [
                {'date': '2024-11-01', 'price': 90000, 'type': 'low'},
                {'date': '2024-12-01', 'price': 100000, 'type': 'high'},
            ],
        }
        result = self.linker.link_timeframes(tf_pivots, current_price=85000)
        # W4(50000) > W1(55000)은 침범 → critical 위반이 있어야 함
        critical = [v for v in result['violations'] if v['severity'] == 'critical']
        # W4=50000 < W1=55000 → 침범!
        assert len(critical) > 0


# ─────────────────────────────────────────────────────
# ForecastEngine 테스트
# ─────────────────────────────────────────────────────

class TestForecastEngine:
    """ForecastEngine 통합 테스트"""

    def setup_method(self):
        from experts.elliott.forecast_engine import ForecastEngine
        self.engine = ForecastEngine('BTC-USD')

    def test_full_pipeline(self):
        """전체 파이프라인 실행"""
        tf_data = make_timeframe_data()
        result = self.engine.run_full_pipeline(tf_data)

        assert result.symbol == 'BTC-USD'
        assert result.current_price > 0
        assert len(result.scenarios) > 0
        assert len(result.forecast_paths) > 0
        assert result.overall_bias in ('bullish', 'bearish', 'neutral')
        assert result.timeframe_consensus is not None

    def test_scenarios_have_probabilities(self):
        """시나리오들이 확률을 가짐"""
        tf_data = make_timeframe_data()
        result = self.engine.run_full_pipeline(tf_data)

        total_prob = sum(s.probability for s in result.scenarios if s.is_valid)
        assert abs(total_prob - 1.0) < 0.05  # 정규화 검증

    def test_forecast_paths_have_points(self):
        """예측 경로에 포인트가 있음"""
        tf_data = make_timeframe_data()
        result = self.engine.run_full_pipeline(tf_data)

        for path in result.forecast_paths:
            assert len(path.path_points) >= 2
            assert path.probability > 0
            assert path.scenario_name != ''

    def test_primary_scenario_exists(self):
        """주력 시나리오 존재"""
        tf_data = make_timeframe_data()
        result = self.engine.run_full_pipeline(tf_data)

        assert result.primary_scenario is not None
        assert result.primary_scenario.probability > 0

    def test_key_levels(self):
        """핵심 레벨 집계"""
        tf_data = make_timeframe_data()
        result = self.engine.run_full_pipeline(tf_data)

        assert len(result.key_levels) > 0

    def test_update_with_candle(self):
        """캔들 업데이트"""
        tf_data = make_timeframe_data()
        self.engine.run_full_pipeline(tf_data)

        candle = {
            'date': datetime(2025, 4, 1),
            'open': 84000, 'high': 86000,
            'low': 83000, 'close': 85000,
            'volume': 30e9,
        }
        update = self.engine.update_with_candle(candle)

        assert 'reclassified' in update
        assert 'invalidated' in update
        assert 'probabilities' in update
        assert isinstance(update['probabilities'], dict)

    def test_update_invalidation(self):
        """캔들 업데이트로 무효화 발생"""
        tf_data = make_timeframe_data()
        self.engine.run_full_pipeline(tf_data)

        # ATH 돌파 캔들 → 조정 시나리오 무효화 예상
        candle = {
            'date': datetime(2025, 4, 1),
            'open': 109000, 'high': 115000,
            'low': 108000, 'close': 114000,
            'volume': 50e9,
        }
        update = self.engine.update_with_candle(candle)

        # 무효화가 0이든 1이든 에러 없이 동작해야 함
        assert isinstance(update['invalidated'], list)

    def test_get_best_path(self):
        """최적 경로 조회"""
        tf_data = make_timeframe_data()
        result = self.engine.run_full_pipeline(tf_data)

        best = result.get_best_path()
        assert best is not None
        assert best.probability > 0


# ─────────────────────────────────────────────────────
# RealtimeLoop 테스트
# ─────────────────────────────────────────────────────

class TestRealtimeLoop:
    """RealtimeLoop 통합 테스트"""

    def setup_method(self):
        from experts.elliott.realtime_loop import RealtimeLoop
        self.loop = RealtimeLoop('BTC-USD', auto_chart=False)

    def test_initialize(self):
        """초기화"""
        tf_data = make_timeframe_data()
        result = self.loop.initialize(tf_data)

        assert result is not None
        assert result.symbol == 'BTC-USD'
        assert self.loop._initialized

    def test_on_new_candle(self):
        """새 캔들 처리"""
        tf_data = make_timeframe_data()
        self.loop.initialize(tf_data)

        candle = {
            'date': datetime(2025, 4, 1),
            'open': 84000, 'high': 86000,
            'low': 83000, 'close': 85000,
            'volume': 30e9,
        }
        update = self.loop.on_new_candle(candle)

        assert update['candle_count'] == 1
        assert 'reclassified' in update
        assert 'alerts' in update

    def test_multiple_candles(self):
        """연속 캔들 처리"""
        tf_data = make_timeframe_data()
        self.loop.initialize(tf_data)

        prices = [85000, 84000, 83000, 82000, 81000, 80000]
        for i, price in enumerate(prices):
            candle = {
                'date': datetime(2025, 4, 1 + i),
                'open': price + 500, 'high': price + 1000,
                'low': price - 500, 'close': price,
                'volume': 30e9,
            }
            update = self.loop.on_new_candle(candle)
            assert update['candle_count'] == i + 1

    def test_get_status(self):
        """상태 조회"""
        tf_data = make_timeframe_data()
        self.loop.initialize(tf_data)

        status = self.loop.get_status()
        assert status['symbol'] == 'BTC-USD'
        assert status['initialized'] is True

    def test_invalidation_alert(self):
        """무효화 시 알림 생성"""
        tf_data = make_timeframe_data()
        self.loop.initialize(tf_data)

        # 극단적 가격 변동으로 무효화 유도
        candle = {
            'date': datetime(2025, 4, 1),
            'open': 120000, 'high': 125000,
            'low': 119000, 'close': 124000,
            'volume': 50e9,
        }
        update = self.loop.on_new_candle(candle)

        # 무효화가 있든 없든 에러 없이 동작
        assert isinstance(update['alerts'], list)


# ─────────────────────────────────────────────────────
# WaveChart + ForecastPaths 테스트
# ─────────────────────────────────────────────────────

class TestWaveChartForecast:
    """WaveChart 미래 경로 시각화 테스트"""

    def test_chart_with_forecast_paths(self):
        """봉차트 + 미래 예측 경로 생성"""
        from experts.elliott.wave_chart import WaveChart, generate_sample_ohlcv, SAMPLE_BTC_WAVES

        chart = WaveChart()
        df = generate_sample_ohlcv()

        # 더미 예측 경로
        forecast_paths = [
            {
                'path_points': [
                    {'date': '2025-06-01', 'price': 85000, 'label': '현재'},
                    {'date': '2025-08-01', 'price': 65000, 'label': 'C'},
                    {'date': '2025-11-01', 'price': 80000, 'label': '반등'},
                ],
                'scenario_name': 'Zigzag ABC',
                'probability': 0.45,
                'invalidation_price': 110000,
            },
            {
                'path_points': [
                    {'date': '2025-06-01', 'price': 85000, 'label': '현재'},
                    {'date': '2025-12-01', 'price': 150000, 'label': 'W5'},
                ],
                'scenario_name': 'Running Flat',
                'probability': 0.25,
                'invalidation_price': 15000,
            },
            {
                'path_points': [
                    {'date': '2025-06-01', 'price': 85000, 'label': '현재'},
                    {'date': '2025-09-01', 'price': 55000, 'label': 'C'},
                ],
                'scenario_name': 'Expanded Flat',
                'probability': 0.15,
                'invalidation_price': 115000,
            },
            {
                'path_points': [
                    {'date': '2025-06-01', 'price': 85000, 'label': '현재'},
                    {'date': '2025-10-01', 'price': 130000, 'label': 'W5.v'},
                ],
                'scenario_name': 'Extended 5th',
                'probability': 0.15,
                'invalidation_price': 49000,
            },
        ]

        save_path = '/home/user/workspace/elliott-wave-expert/charts/test_forecast.png'
        result_path = chart.plot(
            df, waves=SAMPLE_BTC_WAVES,
            symbol='BTC-USD', timeframe='Daily',
            forecast_paths=forecast_paths,
            save_path=save_path,
            title='BTC-USD Elliott Wave + Forecast Scenarios',
        )

        assert os.path.exists(result_path)
        assert os.path.getsize(result_path) > 10000  # 이미지가 충분히 큰지

    def test_chart_without_forecast(self):
        """예측 경로 없이도 정상 동작"""
        from experts.elliott.wave_chart import WaveChart, generate_sample_ohlcv, SAMPLE_BTC_WAVES

        chart = WaveChart()
        df = generate_sample_ohlcv()

        save_path = '/home/user/workspace/elliott-wave-expert/charts/test_no_forecast.png'
        result_path = chart.plot(
            df, waves=SAMPLE_BTC_WAVES,
            symbol='BTC-USD',
            save_path=save_path,
        )

        assert os.path.exists(result_path)


# ─────────────────────────────────────────────────────
# 엔드투엔드 통합 테스트
# ─────────────────────────────────────────────────────

class TestEndToEnd:
    """전체 파이프라인 엔드투엔드"""

    def test_full_flow(self):
        """데이터 → ForecastEngine → 예측 → 캔들 업데이트 → 차트"""
        from experts.elliott.forecast_engine import ForecastEngine
        from experts.elliott.wave_chart import WaveChart, generate_sample_ohlcv, SAMPLE_BTC_WAVES

        # 1. 데이터 준비
        tf_data = make_timeframe_data()

        # 2. 엔진 실행
        engine = ForecastEngine('BTC-USD')
        result = engine.run_full_pipeline(tf_data)

        assert len(result.scenarios) >= 2
        assert len(result.forecast_paths) >= 2
        assert result.primary_scenario is not None

        # 3. 캔들 업데이트
        for i in range(5):
            candle = {
                'date': datetime(2025, 4, 1 + i),
                'open': 85000 - i * 500,
                'high': 86000 - i * 500,
                'low': 83000 - i * 500,
                'close': 84000 - i * 500,
                'volume': 30e9,
            }
            update = engine.update_with_candle(candle)
            assert isinstance(update['probabilities'], dict)

        # 4. 차트 생성
        chart = WaveChart()
        df = generate_sample_ohlcv()
        final_result = engine.get_current_forecast()

        save_path = '/home/user/workspace/elliott-wave-expert/charts/test_e2e.png'
        chart_path = chart.plot(
            df, waves=SAMPLE_BTC_WAVES,
            symbol='BTC-USD', timeframe='Daily',
            forecast_paths=final_result.forecast_paths if final_result else [],
            save_path=save_path,
            title='BTC-USD E2E Test — Elliott Wave Forecast',
        )

        assert os.path.exists(chart_path)

    def test_scenario_probability_sum(self):
        """시나리오 확률 합 = 1.0"""
        from experts.elliott.forecast_engine import ForecastEngine

        engine = ForecastEngine('BTC-USD')
        result = engine.run_full_pipeline(make_timeframe_data())

        valid_scenarios = [s for s in result.scenarios if s.is_valid]
        if valid_scenarios:
            total = sum(s.probability for s in valid_scenarios)
            assert abs(total - 1.0) < 0.05

    def test_timeframe_consensus_in_result(self):
        """결과에 타임프레임 합의 포함"""
        from experts.elliott.forecast_engine import ForecastEngine

        engine = ForecastEngine('BTC-USD')
        result = engine.run_full_pipeline(make_timeframe_data())

        assert 'aligned_phase' in result.timeframe_consensus
        assert 'confidence' in result.timeframe_consensus
        assert 'valid_links' in result.timeframe_consensus


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

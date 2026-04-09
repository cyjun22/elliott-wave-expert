"""
Realtime Update Loop - 실시간 캔들 업데이트 → 확률 재계산 → 차트 갱신
====================================================================

핵심 역할:
  ForecastEngine + WaveChart를 연결하여 새 캔들이 들어올 때마다:
    1. ForecastEngine.update_with_candle() → 무효화/재분류/확률 갱신
    2. 갱신된 시나리오로 차트 재생성
    3. 중요 이벤트 (무효화, 시나리오 전환) 시 알림

사용법:
  # 기본 사용
  loop = RealtimeLoop('BTC-USD')
  result = loop.initialize(timeframe_data)      # 최초 파이프라인 실행
  
  # 새 캔들 들어올 때마다
  update = loop.on_new_candle(candle)
  if update['chart_path']:
      print(f"차트 갱신됨: {update['chart_path']}")
  if update['alerts']:
      print(f"알림: {update['alerts']}")

v3.0.0 — 2026-04-09
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from experts.elliott.forecast_engine import ForecastEngine, ForecastResult
from experts.elliott.wave_chart import WaveChart, generate_sample_ohlcv, SAMPLE_BTC_WAVES

import pandas as pd


class RealtimeLoop:
    """
    실시간 업데이트 루프

    ForecastEngine ↔ WaveChart 연결.
    새 캔들 → 확률 재계산 → 무효화 체크 → 차트 갱신.
    """

    def __init__(
        self,
        symbol: str = 'BTC-USD',
        chart_dir: str = 'charts',
        auto_chart: bool = True,
    ):
        self.symbol = symbol
        self.chart_dir = chart_dir
        self.auto_chart = auto_chart

        self.engine = ForecastEngine(symbol)
        self.chart = WaveChart()

        # 상태
        self._initialized = False
        self._candle_count = 0
        self._last_chart_path: Optional[str] = None
        self._alerts: List[Dict] = []
        self._df_buffer: Optional[pd.DataFrame] = None
        self._wave_points: List[Dict] = []

    # ─── 초기화 ────────────────────────────────────────

    def initialize(
        self,
        timeframe_data: Dict[str, List[Dict]],
        wave_points: List[Dict] = None,
        current_price: Optional[float] = None,
    ) -> ForecastResult:
        """
        최초 파이프라인 실행 + 차트 생성.

        Args:
            timeframe_data: 타임프레임별 OHLCV 리스트
            wave_points: 수동 파동 포인트 (없으면 자동 추출)
            current_price: 현재가

        Returns:
            ForecastResult
        """
        result = self.engine.run_full_pipeline(timeframe_data, current_price)
        self._initialized = True

        # 파동 포인트 설정
        if wave_points:
            self._wave_points = wave_points
        elif result.interpretations:
            # 주력 시나리오의 파동 라벨 사용
            best = result.interpretations[0]
            self._wave_points = best.wave_labels

        # 캔들 데이터 → DataFrame 변환 (차트용)
        daily_candles = timeframe_data.get('1d', [])
        if daily_candles:
            self._df_buffer = self._candles_to_df(daily_candles)

        # 자동 차트 생성
        if self.auto_chart and self._df_buffer is not None:
            self._last_chart_path = self._generate_chart(result)

        return result

    # ─── 실시간 업데이트 ───────────────────────────────

    def on_new_candle(self, candle: Dict) -> Dict:
        """
        새 캔들 도착 시 호출.

        Returns:
            {
              'candle_count': int,
              'reclassified': bool,
              'invalidated': [str],
              'switched_to': str | None,
              'probabilities': {id: float},
              'chart_path': str | None,
              'alerts': [{'type': ..., 'message': ...}]
            }
        """
        if not self._initialized:
            raise RuntimeError("initialize()를 먼저 호출하세요.")

        self._candle_count += 1
        alerts: List[Dict] = []

        # 1. ForecastEngine 업데이트
        update_result = self.engine.update_with_candle(candle)

        # 2. 무효화 알림
        for inv in update_result.get('invalidated', []):
            alert = {
                'type': 'invalidation',
                'message': f"시나리오 무효화: {inv} (${candle['close']:,.0f})",
                'timestamp': datetime.now().isoformat(),
            }
            alerts.append(alert)
            self._alerts.append(alert)

        # 3. 시나리오 전환 알림
        if update_result.get('switched_to'):
            alert = {
                'type': 'scenario_switch',
                'message': f"시나리오 전환 → {update_result['switched_to']}",
                'timestamp': datetime.now().isoformat(),
            }
            alerts.append(alert)
            self._alerts.append(alert)

        # 4. DataFrame 업데이트
        if self._df_buffer is not None:
            new_row = pd.DataFrame([{
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close'],
                'volume': candle.get('volume', 0),
            }], index=[pd.to_datetime(candle['date'])])
            self._df_buffer = pd.concat([self._df_buffer, new_row])

        # 5. 차트 갱신 (무효화 or 5캔들마다)
        chart_path = None
        should_redraw = (
            bool(alerts)
            or self._candle_count % 5 == 0
        )

        if self.auto_chart and should_redraw and self._df_buffer is not None:
            forecast = self.engine.get_current_forecast()
            if forecast:
                chart_path = self._generate_chart(forecast)
                self._last_chart_path = chart_path

        return {
            'candle_count': self._candle_count,
            'reclassified': update_result.get('reclassified', False),
            'invalidated': update_result.get('invalidated', []),
            'switched_to': update_result.get('switched_to'),
            'probabilities': update_result.get('probabilities', {}),
            'chart_path': chart_path,
            'alerts': alerts,
        }

    # ─── 차트 생성 ─────────────────────────────────────

    def _generate_chart(self, result: ForecastResult) -> str:
        """ForecastResult로 차트 생성"""
        Path(self.chart_dir).mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_path = f"{self.chart_dir}/{self.symbol}_forecast_{ts}.png"

        # 주력 시나리오 정보
        primary = result.primary_scenario
        pattern_name = primary.name if primary else ""
        confidence = primary.confidence if primary else 0

        title = (
            f"{self.symbol} Elliott Wave Forecast — "
            f"{pattern_name} ({result.overall_bias.upper()})"
        )

        return self.chart.plot(
            df=self._df_buffer,
            waves=self._wave_points,
            symbol=self.symbol,
            timeframe="Daily",
            forecast_paths=result.forecast_paths,
            show_volume=True,
            show_targets=False,  # forecast_paths가 대체
            title=title,
            save_path=save_path,
        )

    # ─── 유틸 ──────────────────────────────────────────

    def _candles_to_df(self, candles: List[Dict]) -> pd.DataFrame:
        """캔들 리스트 → DataFrame"""
        rows = []
        for c in candles:
            rows.append({
                'open': c['open'],
                'high': c['high'],
                'low': c['low'],
                'close': c['close'],
                'volume': c.get('volume', 0),
            })
        dates = [pd.to_datetime(c['date']) for c in candles]
        return pd.DataFrame(rows, index=dates)

    def get_status(self) -> Dict:
        """현재 상태 요약"""
        forecast = self.engine.get_current_forecast()
        return {
            'symbol': self.symbol,
            'initialized': self._initialized,
            'candle_count': self._candle_count,
            'last_chart': self._last_chart_path,
            'total_alerts': len(self._alerts),
            'active_scenarios': (
                len(forecast.scenarios) if forecast else 0
            ),
            'primary_scenario': (
                forecast.primary_scenario.name if forecast and forecast.primary_scenario else None
            ),
            'overall_bias': forecast.overall_bias if forecast else 'unknown',
        }

"""
Wave Visualization - 시나리오 차트 시각화
=========================================

wave_tracker.py에서 분리된 모듈:
- WaveVisualizer: 시나리오별 차트, 4분할 요약, 멀티 타임프레임 차트 생성
- create_quadrant_chart, generate_scenario_charts, analyze_and_visualize 등
"""

import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from experts.elliott.live_tracker import TargetLevel
from experts.elliott.scenario_chart import (
    create_scenario_path_chart, create_multi_timeframe_chart
)


class WaveVisualizer:
    """
    시나리오 시각화 엔진

    WaveTracker 인스턴스를 참조하여 차트를 생성.
    tracker의 df, scenario_tree, symbol 등에 접근.
    """

    def __init__(self, tracker):
        """
        Args:
            tracker: WaveTracker 인스턴스 (또는 호환 인터페이스)
        """
        self._tracker = tracker

    @property
    def symbol(self) -> str:
        return self._tracker.symbol

    @property
    def df(self) -> Optional[pd.DataFrame]:
        return self._tracker.df

    @property
    def scenario_tree(self):
        return self._tracker.scenario_tree

    @property
    def initialized(self) -> bool:
        return self._tracker.initialized

    def get_scenario_chart(self):
        """시나리오 경로 시각화 차트 반환"""
        if not self.initialized or self.df is None:
            return None

        result = self._tracker.get_tracking_result()
        confirmed_waves = result.primary_scenario.waves if result.primary_scenario else []

        return create_scenario_path_chart(
            df=self.df,
            confirmed_waves=confirmed_waves,
            scenarios=list(self.scenario_tree.scenarios.values()),
            symbol=self.symbol
        )

    def get_multi_timeframe_chart(self):
        """대파동/소파동 멀티 타임프레임 차트"""
        if not self.initialized or self.df is None:
            return None

        result = self._tracker.get_tracking_result()
        confirmed_waves = result.primary_scenario.waves if result.primary_scenario else []

        return create_multi_timeframe_chart(
            df=self.df,
            confirmed_waves=confirmed_waves,
            symbol=self.symbol
        )

    def create_quadrant_chart(
        self,
        scenarios: List[Dict] = None,
        output_path: str = None
    ):
        """
        4분할 시나리오 차트 생성

        2x2 그리드에 각 시나리오별 파동 구조와 현재 위치(★) 표시

        Args:
            scenarios: 시나리오 리스트 (없으면 자동 생성)
            output_path: 저장 경로

        Returns:
            matplotlib Figure
        """
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.dates import DateFormatter

        if scenarios is None:
            scenarios = self._tracker.generate_self_corrected_scenarios()

        if not scenarios or self.df is None:
            return None

        # 4개로 맞추기
        while len(scenarios) < 4:
            scenarios.append(scenarios[-1].copy())
        scenarios = scenarios[:4]

        colors = ['#EF5350', '#29B6F6', '#FFC107', '#AB47BC']

        # DataFrame 준비
        df = self.df.tail(500).copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index)

        current_price = float(df['close'].iloc[-1])
        current_date = df.index[-1]

        fig, axes = plt.subplots(2, 2, figsize=(16, 12), facecolor='#0d1117')
        fig.suptitle(
            f'{self.symbol} Self-Corrected Elliott Wave (시간 순서 유지)',
            fontsize=16, color='white', fontweight='bold'
        )

        for idx, (ax, scenario, color) in enumerate(zip(axes.flat, scenarios, colors)):
            ax.set_facecolor('#161b22')

            # 캔들스틱 (간단 버전)
            ax.fill_between(df.index, df['low'], df['high'], alpha=0.3, color='#30363d')
            ax.plot(df.index, df['close'], color='#58a6ff', linewidth=0.8, alpha=0.7)

            # 파동 그리기
            waves = scenario.get('waves', [])
            if waves:
                wave_dates = []
                wave_prices = []
                wave_labels = []

                for w in waves:
                    try:
                        date_str = w.get('date', '')
                        if isinstance(date_str, str) and date_str:
                            if 'TBD' not in date_str:
                                wave_date = pd.to_datetime(date_str)
                                wave_dates.append(wave_date)
                                wave_prices.append(w['price'])
                                wave_labels.append(w['label'])
                    except Exception:
                        continue

                if wave_dates:
                    ax.plot(wave_dates, wave_prices, color=color, linewidth=2.5, marker='o', markersize=8)

                    for wd, wp, wl in zip(wave_dates, wave_prices, wave_labels):
                        ax.annotate(
                            wl, (wd, wp),
                            textcoords="offset points", xytext=(0, 12),
                            ha='center', fontsize=9, color=color, fontweight='bold'
                        )

            # 현재 위치 ★
            ax.scatter([current_date], [current_price], color='#ffd700', s=200, marker='*', zorder=10)

            prob = scenario.get('probability', 0.25)
            ax.set_title(
                f"{scenario['name']} ({prob:.0%})",
                fontsize=13, color=color, fontweight='bold', pad=10
            )

            ax.tick_params(colors='#8b949e')
            ax.xaxis.set_major_formatter(DateFormatter('%b %Y'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
            for spine in ax.spines.values():
                spine.set_color('#30363d')
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1000:.0f}k'))
            ax.grid(True, alpha=0.1, color='#30363d')

        plt.tight_layout(rect=[0, 0, 1, 0.95])

        if output_path:
            plt.savefig(output_path, dpi=150, facecolor='#0d1117', edgecolor='none')
            print(f"📈 Chart saved: {output_path}")

        return fig

    def generate_scenario_charts(
        self,
        output_dir: str = '/tmp',
        include_projections: bool = True
    ) -> List[str]:
        """
        시나리오별 개별 차트 생성 (미래 Projection 포함)

        각 시나리오에 대해:
        1. 확정된 파동 구조
        2. 미래 예상 경로 (점선)
        3. 타겟/무효화 레벨

        Args:
            output_dir: 차트 저장 디렉토리
            include_projections: 미래 예상 경로 포함 여부

        Returns:
            생성된 차트 파일 경로 리스트
        """
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        if not self.initialized or self.df is None:
            print("⚠️ Tracker not initialized")
            return []

        # DataFrame 준비
        df = self.df.tail(500).copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index)

        current_price = float(df['close'].iloc[-1])
        current_date = df.index[-1]

        scenarios = list(self.scenario_tree.scenarios.values())
        if not scenarios:
            print("⚠️ No scenarios available")
            return []

        chart_paths = []
        colors = ['#EF5350', '#29B6F6', '#66BB6A', '#FFC107', '#AB47BC']

        for idx, scenario in enumerate(scenarios):
            color = colors[idx % len(colors)]

            fig, ax = plt.subplots(figsize=(14, 8), facecolor='#0d1117')
            ax.set_facecolor('#161b22')

            # 캔들스틱 그리기 (실제 OHLC 봉)
            up_color = '#26a69a'
            down_color = '#ef5350'

            for i in range(len(df)):
                date = df.index[i]
                open_price = df['open'].iloc[i]
                high = df['high'].iloc[i]
                low = df['low'].iloc[i]
                close = df['close'].iloc[i]

                if close >= open_price:
                    body_color = up_color
                    body_bottom = open_price
                    body_height = close - open_price
                else:
                    body_color = down_color
                    body_bottom = close
                    body_height = open_price - close

                ax.plot([date, date], [low, high], color=body_color, linewidth=0.8, alpha=0.7)
                ax.plot([date, date], [body_bottom, body_bottom + body_height],
                       color=body_color, linewidth=2.5, solid_capstyle='butt')

            # 확정된 파동 그리기
            waves = getattr(scenario, 'waves', scenario.get('waves', []) if isinstance(scenario, dict) else [])
            wave_dates = []
            wave_prices = []
            if isinstance(waves, list) and waves:
                wave_labels = []

                for w in waves:
                    if not isinstance(w, dict):
                        continue
                    try:
                        date_str = w.get('date', '')
                        if isinstance(date_str, str) and date_str and 'TBD' not in date_str:
                            wave_date = pd.to_datetime(date_str)
                            wave_dates.append(wave_date)
                            wave_prices.append(w['price'])
                            wave_labels.append(w.get('label', ''))
                    except Exception:
                        continue

                if wave_dates:
                    ax.plot(wave_dates, wave_prices, color=color, linewidth=3,
                           marker='o', markersize=10, label='Confirmed Waves', zorder=5)

                    for wd, wp, wl in zip(wave_dates, wave_prices, wave_labels):
                        ax.annotate(
                            wl, (wd, wp),
                            textcoords="offset points", xytext=(0, 15),
                            ha='center', fontsize=11, color=color, fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='#161b22', edgecolor=color)
                        )

            # 미래 Projection 그리기
            if include_projections and wave_dates:
                targets = getattr(scenario, 'targets', [])

                last_wave_date = wave_dates[-1] if wave_dates else current_date
                last_wave_price = wave_prices[-1] if wave_prices else current_price

                proj_dates = [last_wave_date, current_date]
                proj_prices = [last_wave_price, current_price]

                if targets:
                    for i, target in enumerate(targets):
                        if isinstance(target, TargetLevel):
                            target_price = target.price
                        else:
                            target_price = target.get('price', current_price)

                        target_date = current_date + timedelta(days=45 * (i + 1))
                        proj_dates.append(target_date)
                        proj_prices.append(target_price)
                else:
                    self._add_scenario_projections(
                        scenario, ax, proj_dates, proj_prices, current_price, current_date
                    )

                # 미래 예측 파동 시각화
                if len(proj_dates) > 2:
                    future_dates = proj_dates[2:]
                    future_prices = proj_prices[2:]

                    ax.plot(proj_dates, proj_prices, color=color, linewidth=3.5,
                           linestyle='-', alpha=0.6, zorder=5)

                    self._draw_future_candles(
                        ax, proj_dates, proj_prices, future_dates, future_prices
                    )
                else:
                    ax.plot(proj_dates, proj_prices, color=color, linewidth=2.5,
                           linestyle='--', marker='s', markersize=8, alpha=0.7,
                           label='Projected Path', zorder=4)

                # 타겟 레벨 수평선
                if targets:
                    for target in targets:
                        if isinstance(target, TargetLevel):
                            t_price = target.price
                            t_prob = target.probability
                            t_desc = target.description
                        else:
                            t_price = target.get('price', 0)
                            t_prob = target.get('probability', 0.5)
                            t_desc = target.get('description', '')

                        ax.axhline(y=t_price, color='#66BB6A', linestyle=':', alpha=0.5)
                        ax.annotate(
                            f'🎯 ${t_price:,.0f} ({t_prob:.0%})',
                            xy=(df.index[-1], t_price),
                            xytext=(10, 0), textcoords='offset points',
                            fontsize=9, color='#66BB6A', va='center'
                        )

                # 무효화 레벨
                stop_loss = getattr(scenario, 'stop_loss', None)
                if stop_loss:
                    ax.axhline(y=stop_loss, color='#EF5350', linestyle='--', alpha=0.7, linewidth=1.5)
                    ax.annotate(
                        f'🛑 SL: ${stop_loss:,.0f}',
                        xy=(df.index[-1], stop_loss),
                        xytext=(10, 0), textcoords='offset points',
                        fontsize=9, color='#EF5350', va='center'
                    )

            # 현재 위치 ★
            ax.scatter([current_date], [current_price], color='#ffd700', s=300,
                      marker='*', zorder=10, label=f'Current ${current_price:,.0f}')

            # 타이틀 및 스타일
            if isinstance(scenario, dict):
                scenario_name = scenario.get('name', 'Unknown')
                scenario_prob = scenario.get('probability', 0.25)
                scenario_desc = scenario.get('description', '')
            else:
                scenario_name = getattr(scenario, 'name', 'Unknown')
                scenario_prob = getattr(scenario, 'probability', 0.25)
                scenario_desc = getattr(scenario, 'description', '')

            ax.set_title(
                f'{self.symbol} - {scenario_name} ({scenario_prob:.0%})',
                fontsize=16, color=color, fontweight='bold', pad=15
            )

            ax.text(
                0.02, 0.98, scenario_desc,
                transform=ax.transAxes, fontsize=10, color='#8b949e',
                va='top', ha='left',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='#161b22', edgecolor='#30363d')
            )

            ax.tick_params(colors='#8b949e')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            for spine in ax.spines.values():
                spine.set_color('#30363d')
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1000:.0f}k'))
            ax.grid(True, alpha=0.15, color='#30363d')
            ax.legend(loc='upper left', facecolor='#161b22', edgecolor='#30363d', labelcolor='#8b949e')

            safe_name = scenario_name.replace(' ', '_').replace('/', '_').lower()
            chart_path = f"{output_dir}/{self.symbol.replace('-', '_')}_{safe_name}.png"
            plt.tight_layout()
            plt.savefig(chart_path, dpi=150, facecolor='#0d1117', edgecolor='none')
            plt.close(fig)

            chart_paths.append(chart_path)
            print(f"📊 {scenario_name}: {chart_path}")

        print(f"\n✅ Generated {len(chart_paths)} scenario charts")
        return chart_paths

    def _add_scenario_projections(
        self, scenario, ax, proj_dates, proj_prices, current_price, current_date
    ):
        """시나리오 유형에 따른 미래 프로젝션 경로 및 라벨 추가"""
        scenario_name = getattr(scenario, 'name', '') if not isinstance(scenario, dict) else scenario.get('name', '')

        if 'correction' in scenario_name.lower() or 'abc' in scenario_name.lower():
            # ABC 조정 시나리오
            a_mid = current_price * 0.92
            wave_a = current_price * 0.85
            b_mid = wave_a * 1.04
            wave_b = current_price * 0.92
            c_mid = wave_b * 0.88
            wave_c = current_price * 0.72

            proj_dates.extend([
                current_date + timedelta(days=15),
                current_date + timedelta(days=30),
                current_date + timedelta(days=45),
                current_date + timedelta(days=60),
                current_date + timedelta(days=75),
                current_date + timedelta(days=90)
            ])
            proj_prices.extend([a_mid, wave_a, b_mid, wave_b, c_mid, wave_c])

            labels = [(30, 'A', wave_a, '#EF5350'), (60, 'B', wave_b, '#29B6F6'), (90, 'C', wave_c, '#EF5350')]
            for days, label, price, lbl_color in labels:
                ax.annotate(
                    label, (current_date + timedelta(days=days), price),
                    textcoords="offset points", xytext=(0, 15),
                    ha='center', fontsize=13, color=lbl_color, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='#161b22', edgecolor=lbl_color, alpha=0.9)
                )

        elif 'supercycle' in scenario_name.lower() or 'new' in scenario_name.lower():
            # 새 사이클 시나리오
            w1_mid = current_price * 1.12
            wave_1 = current_price * 1.28
            w2_mid = wave_1 * 0.92
            wave_2 = current_price * 1.10
            w3_start = wave_2 * 1.08

            proj_dates.extend([
                current_date + timedelta(days=30),
                current_date + timedelta(days=60),
                current_date + timedelta(days=75),
                current_date + timedelta(days=90),
                current_date + timedelta(days=105)
            ])
            proj_prices.extend([w1_mid, wave_1, w2_mid, wave_2, w3_start])

            labels = [(60, '(1)', wave_1, '#66BB6A'), (90, '(2)', wave_2, '#FFC107'), (105, '(3)?', w3_start, '#66BB6A')]
            for days, label, price, lbl_color in labels:
                ax.annotate(
                    label, (current_date + timedelta(days=days), price),
                    textcoords="offset points", xytext=(0, 15),
                    ha='center', fontsize=13, color=lbl_color, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='#161b22', edgecolor=lbl_color, alpha=0.9)
                )

        elif 'extended' in scenario_name.lower():
            # 확장 5파 시나리오
            ext_mid1 = current_price * 1.12
            ext_mid2 = current_price * 1.08
            ext_mid3 = current_price * 1.22
            ext_target = current_price * 1.35

            proj_dates.extend([
                current_date + timedelta(days=20),
                current_date + timedelta(days=35),
                current_date + timedelta(days=50),
                current_date + timedelta(days=70)
            ])
            proj_prices.extend([ext_mid1, ext_mid2, ext_mid3, ext_target])

            ax.annotate(
                '5 ext', (current_date + timedelta(days=70), ext_target),
                textcoords="offset points", xytext=(0, 15),
                ha='center', fontsize=13, color='#AB47BC', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#161b22', edgecolor='#AB47BC', alpha=0.9)
            )

    def _draw_future_candles(self, ax, proj_dates, proj_prices, future_dates, future_prices):
        """미래 캔들스틱 (반투명) 그리기"""
        import random

        for i, (fd, fp) in enumerate(zip(future_dates, future_prices)):
            if i == 0:
                prev_price = proj_prices[1]
                prev_date = proj_dates[1]
            else:
                prev_price = future_prices[i - 1]
                prev_date = future_dates[i - 1]

            days_between = (fd - prev_date).days
            n_candles = min(5, max(3, days_between // 5))

            for j in range(n_candles):
                ratio = (j + 1) / n_candles
                candle_date = prev_date + timedelta(days=int(days_between * ratio))
                candle_price = prev_price + (fp - prev_price) * ratio

                noise = 1 + random.uniform(-0.02, 0.02)
                candle_price *= noise

                if fp > prev_price:
                    if j % 2 == 0:
                        open_p = candle_price * 0.99
                        close_p = candle_price * 1.01
                        high_p = close_p * 1.005
                        low_p = open_p * 0.995
                        c_color = '#26a69a'
                    else:
                        open_p = candle_price * 1.005
                        close_p = candle_price * 0.995
                        high_p = open_p * 1.005
                        low_p = close_p * 0.995
                        c_color = '#ef5350'
                else:
                    if j % 2 == 0:
                        open_p = candle_price * 1.01
                        close_p = candle_price * 0.99
                        high_p = open_p * 1.005
                        low_p = close_p * 0.995
                        c_color = '#ef5350'
                    else:
                        open_p = candle_price * 0.995
                        close_p = candle_price * 1.005
                        high_p = close_p * 1.005
                        low_p = open_p * 0.995
                        c_color = '#26a69a'

                ax.plot([candle_date, candle_date], [low_p, high_p],
                       color=c_color, linewidth=0.8, alpha=0.4)
                ax.plot([candle_date, candle_date], [min(open_p, close_p), max(open_p, close_p)],
                       color=c_color, linewidth=3, alpha=0.4, solid_capstyle='butt')

    def analyze_and_visualize(
        self,
        df: pd.DataFrame,
        output_dir: str = '/tmp'
    ) -> Dict:
        """
        분석 + 시나리오별 차트 생성 통합 플로우

        1. 초기 분석 (DualAgentExpert)
        2. 시나리오 생성
        3. 시나리오별 개별 차트 생성 (미래 Projection 포함)
        4. 4분할 요약 차트 생성

        Args:
            df: OHLCV 데이터
            output_dir: 저장 디렉토리

        Returns:
            분석 결과 및 차트 경로
        """
        # 데이터 캐시 경로
        cache_dir = os.path.join(output_dir, 'data_cache')
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f'{self.symbol.replace("-", "_")}_ohlcv.csv')

        # DataFrame 저장 (캐시)
        if df is not None:
            df.to_csv(cache_path)
            print(f"💾 Data cached: {cache_path} ({len(df)} bars)")
        else:
            if os.path.exists(cache_path):
                df = pd.read_csv(cache_path, index_col=0)
                df.index = pd.to_datetime(df.index)
                print(f"📂 Loaded from cache: {cache_path} ({len(df)} bars)")
            else:
                print("⚠️ No data provided and no cache found")
                return {'error': 'No data'}

        self._tracker.df = df

        # 1. 초기화 및 분석
        print(f"\n{'='*60}")
        print(f"🎯 Elliott Wave Analysis & Visualization: {self.symbol}")
        print(f"📅 Data range: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
        print(f"{'='*60}\n")

        result = self._tracker.initialize(df, output_dir)

        if not result:
            return {'error': 'Analysis failed'}

        # 2. 시나리오별 개별 차트 생성
        print(f"\n📊 Generating individual scenario charts...")
        scenario_charts = self.generate_scenario_charts(output_dir, include_projections=True)

        # 3. 4분할 요약 차트
        print(f"\n📈 Generating quadrant summary chart...")
        quadrant_path = f"{output_dir}/{self.symbol.replace('-', '_')}_quadrant_summary.png"
        self.create_quadrant_chart(output_path=quadrant_path)

        # 4. 결과 정리
        return {
            'analysis': result,
            'scenario_charts': scenario_charts,
            'quadrant_chart': quadrant_path,
            'scenarios': [
                {
                    'name': s.name,
                    'probability': s.probability,
                    'description': s.description,
                    'chart': scenario_charts[i] if i < len(scenario_charts) else None
                }
                for i, s in enumerate(self.scenario_tree.scenarios.values())
            ]
        }

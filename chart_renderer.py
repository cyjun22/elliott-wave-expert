"""
Chart Renderer - Elliott Wave 시각화
====================================
잠정 결과를 차트로 렌더링하여 사용자에게 보여줌
"""

import io
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from experts.elliott.rag_expert import WaveScenario

# Unified styles
try:
    from utils.chart_styles import WAVE_COLORS, DARK_THEME
except ImportError:
    # Fallback if styles not available
    WAVE_COLORS = {
        '0': '#808080', '1': '#4CAF50', '2': '#F44336',
        '3': '#2196F3', '4': '#FF9800', '5': '#9C27B0',
    }
    DARK_THEME = {'background': '#1a1a2e', 'panel': '#16213e'}


class ChartRenderer:
    """
    Elliott Wave 차트 렌더러
    
    역할:
    1. OHLCV 데이터 + 파동 오버레이
    2. 잠정 결과 시각화
    3. 사용자 확인용 이미지 생성
    """
    
    def __init__(self):
        self.available = MATPLOTLIB_AVAILABLE
    
    def render_scenario(
        self,
        df: pd.DataFrame,
        scenario: WaveScenario,
        symbol: str,
        round_num: int = 1,
        save_path: Optional[str] = None,
        show: bool = False
    ) -> Optional[str]:
        """
        시나리오를 차트로 렌더링
        
        Args:
            df: OHLCV 데이터프레임
            scenario: 파동 시나리오
            symbol: 자산 심볼
            round_num: 현재 라운드 번호
            save_path: 저장 경로 (없으면 임시 파일)
            show: plt.show() 호출 여부
        
        Returns:
            저장된 파일 경로
        """
        if not self.available:
            print("⚠️ Matplotlib not available")
            return None
        
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df_work = df.copy()
            df_work.columns = [c[0].lower() for c in df_work.columns]
        else:
            df_work = df.copy()
            df_work.columns = [c.lower() for c in df_work.columns]
        
        # 그래프 생성
        fig, ax = plt.subplots(figsize=(14, 8))
        
        # 배경 스타일
        ax.set_facecolor('#1a1a2e')
        fig.patch.set_facecolor('#16213e')
        
        # 캔들스틱 차트
        self._draw_candlestick(ax, df_work)
        
        # 파동 포인트 및 라인
        if scenario and scenario.waves:
            self._draw_waves(ax, scenario.waves, df_work)
        
        # 타이틀
        confidence = scenario.confidence if scenario else 0
        ax.set_title(
            f'{symbol} - Elliott Wave Analysis (Round {round_num})\n'
            f'Confidence: {confidence:.0%}',
            fontsize=14,
            fontweight='bold',
            color='white',
            pad=15
        )
        
        # 축 스타일
        ax.set_xlabel('Date', fontsize=11, color='white')
        ax.set_ylabel('Price ($)', fontsize=11, color='white')
        ax.tick_params(colors='white')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.xticks(rotation=45)
        
        # 그리드
        ax.grid(True, alpha=0.2, color='white')
        
        # Y축 포맷
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        # 범례
        ax.legend(loc='upper left', facecolor='#1a1a2e', labelcolor='white')
        
        plt.tight_layout()
        
        # 저장
        if save_path is None:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            save_path = tmp.name
            tmp.close()

        plt.savefig(save_path, dpi=150, facecolor=fig.get_facecolor())

        if show:
            plt.show()
        else:
            plt.close()

        return save_path
    
    def _draw_candlestick(self, ax, df: pd.DataFrame):
        """캔들스틱 차트 그리기"""
        # 색상 설정 (원래 라인 차트와 유사한 톤)
        up_color = '#26a69a'    # 상승: 청록
        down_color = '#ef5350'  # 하락: 빨강
        
        # 날짜를 숫자로 변환
        dates = mdates.date2num(df.index)
        
        # 봉 너비 계산 (데이터 간격에 따라)
        if len(dates) > 1:
            width = 0.6 * (dates[1] - dates[0])
        else:
            width = 0.6
        
        for i in range(len(df)):
            date = dates[i]
            open_price = df['open'].iloc[i]
            high = df['high'].iloc[i]
            low = df['low'].iloc[i]
            close = df['close'].iloc[i]
            
            # 색상 결정
            if close >= open_price:
                color = up_color
                body_bottom = open_price
                body_height = close - open_price
            else:
                color = down_color
                body_bottom = close
                body_height = open_price - close
            
            # 심지 (wick)
            ax.plot([date, date], [low, high], color=color, linewidth=0.5, alpha=0.8)
            
            # 몸통 (body)
            if body_height > 0:
                ax.bar(date, body_height, width, bottom=body_bottom, 
                       color=color, edgecolor=color, alpha=0.9)
            else:
                # 도지 (doji)
                ax.plot([date - width/2, date + width/2], [close, close], 
                        color=color, linewidth=1)
    
    def _draw_waves(self, ax, waves: List[Dict], df: pd.DataFrame):
        """파동 포인트 및 연결선 그리기"""
        # 날짜순 정렬
        sorted_waves = sorted(waves, key=lambda x: x['date'])
        
        # 좌표 추출
        dates = []
        prices = []
        labels = []
        
        for w in sorted_waves:
            try:
                date = pd.to_datetime(w['date'])
                dates.append(date)
                prices.append(w['price'])
                labels.append(w['label'])
            except:
                continue
        
        if not dates:
            return
        
        # 연결선
        ax.plot(
            dates, prices,
            color='#00d4ff',
            linewidth=2.5,
            linestyle='--',
            alpha=0.9,
            zorder=5
        )
        
        # 포인트 및 라벨
        for i, (date, price, label) in enumerate(zip(dates, prices, labels)):
            color = WAVE_COLORS.get(label, '#ffffff')
            
            # 포인트
            ax.scatter(
                date, price,
                s=120,
                c=color,
                edgecolors='white',
                linewidth=2,
                zorder=10
            )
            
            # 라벨
            offset = 0.03 * (max(prices) - min(prices))
            y_offset = offset if i % 2 == 0 else -offset
            
            ax.annotate(
                f'W{label}\n${price:,.0f}',
                (date, price),
                textcoords="offset points",
                xytext=(0, 15 if y_offset > 0 else -25),
                ha='center',
                fontsize=9,
                fontweight='bold',
                color=color,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', edgecolor=color, alpha=0.8),
                zorder=15
            )
    
    def render_comparison(
        self,
        df: pd.DataFrame,
        scenarios: List[WaveScenario],
        symbol: str,
        save_path: Optional[str] = None
    ) -> Optional[str]:
        """여러 시나리오 비교 차트"""
        if not self.available or not scenarios:
            return None
        
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df_work = df.copy()
            df_work.columns = [c[0].lower() for c in df_work.columns]
        else:
            df_work = df.copy()
            df_work.columns = [c.lower() for c in df_work.columns]
        
        fig, axes = plt.subplots(1, len(scenarios), figsize=(7 * len(scenarios), 6))
        
        if len(scenarios) == 1:
            axes = [axes]
        
        for i, (ax, scenario) in enumerate(zip(axes, scenarios)):
            ax.set_facecolor('#1a1a2e')
            ax.plot(df_work.index, df_work['close'], color='#e8e8e8', linewidth=1)
            
            if scenario.waves:
                self._draw_waves(ax, scenario.waves, df_work)
            
            ax.set_title(f'Scenario {i+1} ({scenario.confidence:.0%})', color='white')
            ax.tick_params(colors='white')
        
        fig.patch.set_facecolor('#16213e')
        fig.suptitle(f'{symbol} - Scenario Comparison', fontsize=14, color='white')
        plt.tight_layout()
        
        if save_path is None:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            save_path = tmp.name
            tmp.close()

        plt.savefig(save_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close()

        return save_path


# === 테스트 ===
if __name__ == "__main__":
    print("=== Chart Renderer Test ===\n")
    
    renderer = ChartRenderer()
    
    if not renderer.available:
        print("❌ Matplotlib not available")
    else:
        print("✅ Matplotlib available")
        
        # 테스트 데이터
        import yfinance as yf
        df = yf.download('BTC-USD', start='2022-01-01', progress=False)
        
        # 테스트 시나리오
        test_scenario = WaveScenario(
            waves=[
                {'label': '0', 'price': 15599, 'date': '2022-11-21', 'type': 'low'},
                {'label': '1', 'price': 31815, 'date': '2023-07-13', 'type': 'high'},
                {'label': '2', 'price': 24797, 'date': '2023-09-11', 'type': 'low'},
                {'label': '3', 'price': 73750, 'date': '2024-03-14', 'type': 'high'},
                {'label': '4', 'price': 49121, 'date': '2024-08-05', 'type': 'low'},
                {'label': '5', 'price': 109115, 'date': '2025-01-20', 'type': 'high'},
            ],
            confidence=0.85,
            reasoning="Test",
            rag_sources=[]
        )
        
        path = renderer.render_scenario(
            df=df,
            scenario=test_scenario,
            symbol='BTC-USD',
            round_num=1,
            save_path='/tmp/elliott_test.png'
        )
        
        print(f"✅ Chart saved to: {path}")

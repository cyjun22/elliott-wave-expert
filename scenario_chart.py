"""
시나리오 경로 시각화 - 개선된 버전
================================
- 파동 분석 결과 완전 표시
- 예측 경로 현재가에서 시작
- 무효화 라인 라벨 개선
- 확률 바 정확도 향상
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import numpy as np

from experts.elliott.live_tracker import WaveScenarioLive, WaveType


def create_scenario_path_chart(
    df: pd.DataFrame,
    confirmed_waves: List[Dict],
    scenarios: List[WaveScenarioLive],
    symbol: str = "BTC-USD",
    current_price: float = None
) -> go.Figure:
    """
    시나리오별 예측 경로 차트, 개선된 버전
    
    - 확정된 파동: 굵은 주황색 실선
    - 각 시나리오 예측 경로: 점선 (확률별 투명도)
    - 무효화 레벨: 깔끔한 수평선
    - 확률 바: 정확한 값 표시
    """
    # 서브플롯 생성 - 높이 비율 조정
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,  # x축 분리
        row_heights=[0.72, 0.28],  # 확률 바 더 크게
        vertical_spacing=0.1,
        subplot_titles=[f"{symbol} - Elliott Wave Scenarios", "Scenario Probabilities"]
    )
    
    # 컬럼 처리
    if isinstance(df.columns, pd.MultiIndex):
        close = df['Close'].iloc[:, 0]
    else:
        close = df['Close']
    
    last_date = df.index[-1]
    last_price = current_price or float(close.iloc[-1])
    
    # ========== 1. 가격 라인 (더 굵게) ==========
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=close,
            mode='lines',
            name='Price',
            line=dict(color='#64B5F6', width=1.5),  # 더 밝은 파란색
            opacity=0.8
        ),
        row=1, col=1
    )
    
    # ========== 2. 확정된 파동 포인트 ==========
    if confirmed_waves:
        wave_dates = [w['date'] for w in confirmed_waves]
        wave_prices = [w['price'] for w in confirmed_waves]
        wave_labels = [w['label'] for w in confirmed_waves]
        
        # 파동 연결선
        fig.add_trace(
            go.Scatter(
                x=wave_dates,
                y=wave_prices,
                mode='lines+markers',
                name='Confirmed Waves',
                line=dict(color='#FF9800', width=3),
                marker=dict(size=14, color='#FF9800', symbol='diamond',
                           line=dict(color='white', width=2)),
            ),
            row=1, col=1
        )
        
        # 파동 라벨 - 별도 annotation으로 (더 보기 좋게)
        for i, (dt, price, label) in enumerate(zip(wave_dates, wave_prices, wave_labels)):
            fig.add_annotation(
                x=dt,
                y=price,
                text=f"<b>W{label}</b>",
                showarrow=False,
                yshift=25,
                font=dict(size=12, color='#FFB74D'),
                row=1, col=1
            )
    
    # 현재가 표시
    fig.add_annotation(
        x=last_date,
        y=last_price,
        text=f"<b>Now: ${last_price:,.0f}</b>",
        showarrow=True,
        arrowhead=2,
        arrowcolor='#4CAF50',
        font=dict(size=11, color='#4CAF50'),
        ax=60,
        ay=-30,
        row=1, col=1
    )
    
    # ========== 3. 시나리오별 예측 경로 ==========
    colors = {
        'ABC Correction': '#EF5350',      # Red
        'Extended 5th Wave': '#66BB6A',   # Green
        'New Supercycle Wave 1': '#AB47BC',  # Purple
        'Wave 5 In Progress': '#42A5F5'   # Blue
    }
    
    valid_scenarios = [s for s in scenarios if s.is_valid]
    
    for scenario in valid_scenarios:
        color = colors.get(scenario.name, '#888888')
        opacity = min(0.95, 0.5 + scenario.probability * 0.5)  # 확률 기반 투명도
        
        # 예측 경로 생성
        path_dates, path_prices = _generate_projection_path(
            scenario, last_date, last_price
        )
        
        if path_dates and path_prices:
            fig.add_trace(
                go.Scatter(
                    x=path_dates,
                    y=path_prices,
                    mode='lines+markers',
                    name=f"{scenario.name} ({scenario.probability:.0%})",
                    line=dict(color=color, width=3, dash='dash'),
                    marker=dict(size=10, color=color, symbol='circle',
                               line=dict(color='white', width=1)),
                    opacity=opacity,
                    hovertemplate=f"<b>{scenario.name}</b><br>Price: $%{{y:,.0f}}<br>Date: %{{x}}<extra></extra>"
                ),
                row=1, col=1
            )
            
            # 목표가 라벨 (마지막 포인트에)
            if scenario.targets and len(path_prices) > 1:
                target = scenario.targets[0]
                fig.add_annotation(
                    x=path_dates[-1],
                    y=path_prices[-1],
                    text=f"<b>${target.price:,.0f}</b>",
                    showarrow=True,
                    arrowhead=2,
                    arrowcolor=color,
                    font=dict(size=11, color=color),
                    ax=40,
                    ay=-20,
                    row=1, col=1
                )
    
    # ========== 4. 무효화 라인 (개선) ==========
    invalidation_levels = []
    for scenario in valid_scenarios:
        if scenario.invalidation_rules:
            inv_price = scenario.invalidation_rules[0].threshold
            color = colors.get(scenario.name, '#888888')
            
            # 중복 방지
            if inv_price not in [x[0] for x in invalidation_levels]:
                invalidation_levels.append((inv_price, scenario.name, color))
    
    for inv_price, name, color in invalidation_levels:
        fig.add_hline(
            y=inv_price,
            line_dash="dot",
            line_color=color,
            line_width=1.5,
            opacity=0.6,
            row=1, col=1
        )
        # 오른쪽에 간결한 라벨 표시
        short_name = name.replace('Correction', 'Corr').replace('Extended', 'Ext').replace('Supercycle', 'SC')
        fig.add_annotation(
            x=last_date + timedelta(days=60),
            y=inv_price,
            text=f"✕ {short_name[:12]}",
            showarrow=False,
            font=dict(size=9, color=color),
            xanchor='left',
            row=1, col=1
        )
    
    # ========== 5. 확률 바 차트 (가로형) ==========
    scenario_names = [s.name for s in valid_scenarios]
    probabilities = [s.probability * 100 for s in valid_scenarios]
    bar_colors = [colors.get(s.name, '#888888') for s in valid_scenarios]
    
    fig.add_trace(
        go.Bar(
            y=scenario_names,
            x=probabilities,
            orientation='h',
            marker_color=bar_colors,
            text=[f"{p:.0f}%" for p in probabilities],
            textposition='outside',
            textfont=dict(size=12, color='white'),
            showlegend=False,
            hovertemplate="<b>%{y}</b><br>Probability: %{x:.1f}%<extra></extra>"
        ),
        row=2, col=1
    )
    
    # ========== 레이아웃 ==========
    fig.update_layout(
        title=dict(
            text=f"📊 {symbol} Elliott Wave Scenario Analysis",
            font=dict(size=22, color='white'),
            x=0.5,
            xanchor='center'
        ),
        template="plotly_dark",
        height=1000,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(30,30,50,0.8)",
            bordercolor="rgba(100,100,100,0.5)",
            borderwidth=1
        ),
        hovermode='x unified',
        margin=dict(l=80, r=150, t=80, b=80)  # 여백 확대
    )
    
    # X축 설정
    fig.update_xaxes(title_text="", row=1, col=1)
    fig.update_xaxes(title_text="Probability (%)", range=[0, 110], row=2, col=1)
    
    # Y축 설정
    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="", row=2, col=1)
    
    return fig


def _generate_projection_path(
    scenario: WaveScenarioLive,
    last_date: datetime,
    last_price: float
) -> tuple:
    """시나리오별 예측 경로 생성 - 개선"""
    dates = [last_date]
    prices = [last_price]
    
    if not scenario.targets:
        return dates, prices
    
    target = scenario.targets[0].price
    
    # 시나리오 유형에 따라 경로 생성
    if scenario.wave_type == WaveType.CORRECTIVE:
        # ABC 조정: A-B-C 지그재그 패턴
        wave_a_date = last_date + timedelta(days=25)
        wave_a_price = last_price - (last_price - target) * 0.6
        
        wave_b_date = last_date + timedelta(days=40)
        wave_b_price = wave_a_price + (last_price - target) * 0.3  # B파 반등
        
        wave_c_date = last_date + timedelta(days=75)
        wave_c_price = target
        
        dates.extend([wave_a_date, wave_b_date, wave_c_date])
        prices.extend([wave_a_price, wave_b_price, wave_c_price])
    
    elif scenario.wave_type == WaveType.IMPULSE:
        if scenario.current_position.value == 'wave_5':
            # Wave 5 확장: 조정 후 상승
            dip_date = last_date + timedelta(days=20)
            dip_price = last_price * 0.92  # 작은 조정
            
            mid_date = last_date + timedelta(days=60)
            mid_price = target * 0.92
            
            end_date = last_date + timedelta(days=100)
            
            dates.extend([dip_date, mid_date, end_date])
            prices.extend([dip_price, mid_price, target])
        
        elif scenario.current_position.value == 'wave_1':
            # 새 사이클: 5파 임펄스 구조
            steps = [
                (30, 0.25),   # Wave 1
                (50, 0.15),   # Wave 2 조정
                (90, 0.70),   # Wave 3
                (110, 0.55),  # Wave 4 조정
                (150, 1.0),   # Wave 5 목표
            ]
            for days, progress in steps:
                future_date = last_date + timedelta(days=days)
                step_price = last_price + (target - last_price) * progress
                dates.append(future_date)
                prices.append(step_price)
    
    return dates, prices


def create_multi_timeframe_chart(
    df: pd.DataFrame,
    confirmed_waves: List[Dict],
    symbol: str = "BTC-USD"
) -> go.Figure:
    """대파동/소파동 멀티 타임프레임 차트"""
    fig = go.Figure()
    
    if isinstance(df.columns, pd.MultiIndex):
        close = df['Close'].iloc[:, 0]
    else:
        close = df['Close']
    
    # 가격
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=close,
            mode='lines',
            name='Price',
            line=dict(color='#64B5F6', width=1.5)
        )
    )
    
    # 대파동
    major_waves = [w for w in confirmed_waves if w.get('degree', 'primary') in ['primary', 'cycle']]
    if major_waves:
        fig.add_trace(
            go.Scatter(
                x=[w['date'] for w in major_waves],
                y=[w['price'] for w in major_waves],
                mode='lines+markers+text',
                name='Major Waves',
                line=dict(color='#FF9800', width=4),
                marker=dict(size=14, symbol='diamond', line=dict(color='white', width=2)),
                text=[f"({w['label']})" for w in major_waves],
                textposition='top center',
                textfont=dict(size=14, color='#FF9800')
            )
        )
    
    # 소파동
    minor_waves = [w for w in confirmed_waves if w.get('degree', 'minor') == 'minor']
    if minor_waves:
        fig.add_trace(
            go.Scatter(
                x=[w['date'] for w in minor_waves],
                y=[w['price'] for w in minor_waves],
                mode='lines+markers+text',
                name='Minor Waves',
                line=dict(color='#66BB6A', width=2, dash='dot'),
                marker=dict(size=8, symbol='circle'),
                text=[f"{w['label']}" for w in minor_waves],
                textposition='bottom center',
                textfont=dict(size=10, color='#66BB6A')
            )
        )
    
    fig.update_layout(
        title=f"{symbol} - Multi-Degree Wave Structure",
        template="plotly_dark",
        height=650,
        xaxis_title="Date",
        yaxis_title="Price ($)"
    )
    
    return fig

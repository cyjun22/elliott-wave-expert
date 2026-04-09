"""
Elliott Wave Candlestick Chart
==============================
봉차트(캔들스틱) 위에 파동 카운트를 시각적으로 표시하는 모듈.

핵심 기능:
- OHLCV 캔들스틱 차트 (다크 테마)
- 파동 번호 라벨 (① ② ③ ④ ⑤, Ⓐ Ⓑ Ⓒ)
- 파동 간 연결선 (지그재그)
- 무효화 레벨 수평선
- 목표가 영역 (피보나치)
- 거래량 서브플롯
- 대안 시나리오 오버레이 (선택)

Usage:
    # core.py 분석 결과에서
    from wave_chart import WaveChart
    chart = WaveChart()
    chart.plot(df, analysis, save_path="btc_waves.png")

    # 직접 파동 포인트 지정
    chart.plot_manual(df, waves=[
        {"label": "0", "date": "2022-11-21", "price": 15599},
        {"label": "1", "date": "2023-07-13", "price": 31815},
        ...
    ], symbol="BTC-USD", save_path="btc_waves.png")

    # CLI
    python wave_chart.py --sample              # 내장 BTC 샘플로 데모
    python wave_chart.py --csv data.csv        # CSV 파일에서
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
MATLIB_AVAILABLE = True


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

# 파동 라벨 매핑 — 봉차트 위에 표시되는 텍스트
IMPULSE_LABELS = {
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
}
CORRECTIVE_LABELS = {
    "A": "A", "B": "B", "C": "C", "D": "D", "E": "E",
    "W": "W", "X": "X", "Y": "Y", "Z": "Z",
}
MINOR_LABELS = {
    "i": "i", "ii": "ii", "iii": "iii", "iv": "iv", "v": "v",
}

# 파동별 색상
WAVE_COLORS = {
    # Impulse
    "0": "#78909C",  # 시작점 — 회색
    "1": "#66BB6A",  # W1 — 초록
    "2": "#EF5350",  # W2 — 빨강
    "3": "#42A5F5",  # W3 — 파랑 (가장 강한 파동)
    "4": "#FFA726",  # W4 — 주황
    "5": "#AB47BC",  # W5 — 보라
    # Corrective
    "A": "#EF5350",  # A파 — 빨강
    "B": "#66BB6A",  # B파 — 초록 (반등)
    "C": "#F44336",  # C파 — 진한 빨강
    "D": "#FF7043",  # D파
    "E": "#FF5722",  # E파
    # Minor
    "i": "#81C784", "ii": "#E57373", "iii": "#64B5F6",
    "iv": "#FFB74D", "v": "#CE93D8",
}

# 다크 테마 색상
THEME = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "grid": "#21262d",
    "text": "#c9d1d9",
    "text_dim": "#7d8590",
    "candle_up": "#3fb950",
    "candle_down": "#f85149",
    "volume_up": "#3fb95044",
    "volume_down": "#f8514944",
    "wave_line": "#58a6ff",
    "invalidation": "#f85149",
    "target_zone": "#3fb95022",
    "target_line": "#3fb950",
}


# ─────────────────────────────────────────────
# WaveChart — 메인 클래스
# ─────────────────────────────────────────────

class WaveChart:
    """
    봉차트 + 파동 카운트 시각화

    매번 동일한 포맷으로 출력되어 결과를 일관되게 비교 가능.
    """

    def __init__(self, figsize: Tuple[int, int] = (18, 10), dpi: int = 150):
        if not MATLIB_AVAILABLE:
            raise ImportError("matplotlib 필요: pip install matplotlib")
        self.figsize = figsize
        self.dpi = dpi

    # ── Public API ──────────────────────────

    def plot(
        self,
        df: pd.DataFrame,
        analysis: Any = None,
        waves: List[Dict] = None,
        symbol: str = "UNKNOWN",
        timeframe: str = "",
        save_path: str = None,
        show_volume: bool = True,
        show_targets: bool = True,
        show_invalidation: bool = True,
        show_alternatives: bool = False,
        title: str = None,
    ) -> str:
        """
        봉차트 + 파동 카운트 차트 생성

        Args:
            df: OHLCV DataFrame (columns: open/high/low/close/volume, DatetimeIndex)
            analysis: core.py의 WaveAnalysis 객체 (있으면 자동 추출)
            waves: 수동 파동 포인트 [{label, date, price}, ...]
            symbol: 심볼명
            timeframe: 타임프레임 문자열
            save_path: 저장 경로 (None이면 자동 생성)
            show_volume: 거래량 서브플롯 표시
            show_targets: 목표가 영역 표시
            show_invalidation: 무효화 레벨 표시
            show_alternatives: 대안 시나리오 오버레이
            title: 커스텀 타이틀

        Returns:
            저장된 파일 경로
        """
        # 데이터 정규화
        df_work = self._normalize_df(df)

        # WaveAnalysis에서 파동 정보 추출
        wave_points = []
        targets = {}
        invalidation = None
        pattern_name = ""
        confidence = 0.0
        alt_wave_sets = []

        if analysis is not None:
            wave_points = self._extract_waves_from_analysis(analysis)
            targets = getattr(analysis, "targets", {}) or {}
            invalidation = getattr(analysis, "invalidation_level", None)
            pattern_name = getattr(analysis, "pattern", None)
            if pattern_name and hasattr(pattern_name, "value"):
                pattern_name = pattern_name.value
            confidence = getattr(analysis, "pattern_confidence", 0)
            symbol = getattr(analysis, "symbol", symbol) or symbol
            timeframe = getattr(analysis, "timeframe", timeframe) or timeframe

            if show_alternatives and hasattr(analysis, "alternatives"):
                for alt in (analysis.alternatives or []):
                    alt_wave_sets.append(self._extract_waves_from_analysis(alt))

        if waves:
            wave_points = self._normalize_wave_points(waves, df_work)

        # 그리기
        fig, axes = self._create_figure(show_volume)
        ax_price = axes[0]
        ax_volume = axes[1] if show_volume and len(axes) > 1 else None

        self._draw_candlesticks(ax_price, df_work)

        if ax_volume is not None:
            self._draw_volume(ax_volume, df_work)

        if wave_points:
            self._draw_wave_count(ax_price, wave_points, df_work)

        if show_targets and targets:
            self._draw_targets(ax_price, targets, df_work)

        if show_invalidation and invalidation:
            self._draw_invalidation(ax_price, invalidation, df_work)

        for i, alt_waves in enumerate(alt_wave_sets):
            self._draw_alternative_waves(ax_price, alt_waves, alpha=0.3)

        # 타이틀
        self._draw_title(ax_price, symbol, timeframe, pattern_name, confidence, title)

        # Y축 여백 확보 (파동 라벨이 잘리지 않도록)
        if wave_points:
            all_prices = [w["price"] for w in wave_points]
            price_range = max(all_prices) - min(all_prices)
            y_min = min(all_prices) - price_range * 0.12
            y_max = max(all_prices) + price_range * 0.12
            ax_price.set_ylim(max(0, y_min), y_max)

        # 축 포맷팅
        self._format_axes(ax_price, ax_volume, df_work)

        # 범례
        self._draw_legend(ax_price, wave_points, pattern_name, confidence)

        # 저장
        if save_path is None:
            os.makedirs("charts", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = f"charts/{symbol}_{ts}.png"

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=self.dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        return save_path

    def plot_manual(
        self,
        df: pd.DataFrame,
        waves: List[Dict],
        symbol: str = "BTC-USD",
        **kwargs,
    ) -> str:
        """간편 인터페이스 — 수동 파동 포인트로 차트 생성"""
        return self.plot(df, waves=waves, symbol=symbol, **kwargs)

    # ── Figure Setup ────────────────────────

    def _create_figure(self, show_volume: bool) -> Tuple[plt.Figure, list]:
        if show_volume:
            fig, (ax_price, ax_vol) = plt.subplots(
                2, 1, figsize=self.figsize,
                gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05},
                sharex=True,
            )
            fig.patch.set_facecolor(THEME["bg"])
            ax_price.set_facecolor(THEME["panel"])
            ax_vol.set_facecolor(THEME["panel"])
            return fig, [ax_price, ax_vol]
        else:
            fig, ax_price = plt.subplots(figsize=self.figsize)
            fig.patch.set_facecolor(THEME["bg"])
            ax_price.set_facecolor(THEME["panel"])
            return fig, [ax_price]

    # ── Candlesticks ────────────────────────

    def _draw_candlesticks(self, ax: plt.Axes, df: pd.DataFrame):
        """캔들스틱 그리기"""
        dates = mdates.date2num(df.index)

        if len(dates) > 1:
            width = 0.6 * np.median(np.diff(dates))
        else:
            width = 0.6

        up = df["close"] >= df["open"]
        down = ~up

        # 상승 봉
        if up.any():
            ax.bar(dates[up], (df["close"] - df["open"])[up], width,
                   bottom=df["open"][up],
                   color=THEME["candle_up"], edgecolor=THEME["candle_up"],
                   linewidth=0.5, zorder=3)
            ax.vlines(dates[up], df["low"][up], df["high"][up],
                      color=THEME["candle_up"], linewidth=0.6, zorder=2)

        # 하락 봉
        if down.any():
            ax.bar(dates[down], (df["open"] - df["close"])[down], width,
                   bottom=df["close"][down],
                   color=THEME["candle_down"], edgecolor=THEME["candle_down"],
                   linewidth=0.5, zorder=3)
            ax.vlines(dates[down], df["low"][down], df["high"][down],
                      color=THEME["candle_down"], linewidth=0.6, zorder=2)

    # ── Volume ──────────────────────────────

    def _draw_volume(self, ax: plt.Axes, df: pd.DataFrame):
        """거래량 바 그리기"""
        if "volume" not in df.columns:
            return

        dates = mdates.date2num(df.index)
        width = 0.6 * np.median(np.diff(dates)) if len(dates) > 1 else 0.6

        up = df["close"] >= df["open"]
        down = ~up

        if up.any():
            ax.bar(dates[up], df["volume"][up], width,
                   color=THEME["volume_up"], edgecolor="none", zorder=2)
        if down.any():
            ax.bar(dates[down], df["volume"][down], width,
                   color=THEME["volume_down"], edgecolor="none", zorder=2)

    # ── Wave Count ──────────────────────────

    def _draw_wave_count(
        self, ax: plt.Axes, wave_points: List[Dict], df: pd.DataFrame
    ):
        """파동 카운트 라벨 + 연결선"""

        if not wave_points:
            return

        # 1. 연결선 (지그재그)
        xs = [mdates.date2num(w["date"]) for w in wave_points]
        ys = [w["price"] for w in wave_points]

        # 그라데이션 라인 — 각 세그먼트마다 파동 색상
        for i in range(len(wave_points) - 1):
            label = wave_points[i + 1]["label"]
            color = WAVE_COLORS.get(label, THEME["wave_line"])
            ax.plot(
                [xs[i], xs[i + 1]], [ys[i], ys[i + 1]],
                color=color, linewidth=3, alpha=0.9,
                solid_capstyle="round", zorder=6,
            )

        # 2. 포인트 + 라벨
        price_range = max(ys) - min(ys) if len(ys) > 1 else ys[0] * 0.1

        for wp in wave_points:
            x = mdates.date2num(wp["date"])
            y = wp["price"]
            label = wp["label"]
            color = WAVE_COLORS.get(label, "#ffffff")

            # 원형 라벨 텍스트
            display_label = (
                IMPULSE_LABELS.get(label)
                or CORRECTIVE_LABELS.get(label)
                or MINOR_LABELS.get(label)
                or label
            )

            # 포인트 마커
            ax.scatter(
                x, y, s=100, c=color,
                edgecolors="white", linewidths=1.5,
                zorder=10,
            )

            # 고점이면 위에, 저점이면 아래에 라벨
            is_high = wp.get("type") == "high"
            if wp.get("type") is None:
                # 타입 정보 없으면 전후 비교로 추정
                idx = wave_points.index(wp)
                prev_y = wave_points[idx - 1]["price"] if idx > 0 else y
                next_y = wave_points[idx + 1]["price"] if idx < len(wave_points) - 1 else y
                is_high = y >= max(prev_y, next_y)

            y_offset = price_range * 0.04 if is_high else -price_range * 0.04
            va = "bottom" if is_high else "top"

            ax.annotate(
                display_label,
                (x, y),
                xytext=(0, 20 if is_high else -20),
                textcoords="offset points",
                ha="center", va=va,
                fontsize=13, fontweight="bold",
                color="white",
                bbox=dict(
                    boxstyle="circle,pad=0.3",
                    facecolor=color,
                    edgecolor="white",
                    alpha=0.95,
                    linewidth=1.5,
                ),
                zorder=15,
            )

            # 가격 태그 (작은 글씨)
            price_text = f"${y:,.0f}" if y >= 100 else f"${y:,.2f}"
            ax.annotate(
                price_text,
                (x, y),
                xytext=(0, 36 if is_high else -36),
                textcoords="offset points",
                ha="center", va=va,
                fontsize=8, color=THEME["text_dim"],
                zorder=14,
            )

    # ── Targets ─────────────────────────────

    def _draw_targets(self, ax: plt.Axes, targets: Dict, df: pd.DataFrame):
        """목표가 영역 표시"""
        last_date = mdates.date2num(df.index[-1])
        extend_date = last_date + (last_date - mdates.date2num(df.index[0])) * 0.15

        for i, (name, target) in enumerate(list(targets.items())[:3]):
            price = target.price if hasattr(target, "price") else target
            label_text = target.name if hasattr(target, "name") else name

            ax.axhline(
                y=price, linestyle="--", color=THEME["target_line"],
                linewidth=1, alpha=0.5, zorder=4,
            )
            ax.annotate(
                f"🎯 {label_text}: ${price:,.0f}",
                (extend_date, price),
                fontsize=8, color=THEME["target_line"],
                va="bottom", ha="left",
                zorder=14,
            )

    # ── Invalidation ────────────────────────

    def _draw_invalidation(self, ax: plt.Axes, level: float, df: pd.DataFrame):
        """무효화 레벨 수평선"""
        ax.axhline(
            y=level, linestyle=":", color=THEME["invalidation"],
            linewidth=1.5, alpha=0.7, zorder=5,
        )
        last_date = mdates.date2num(df.index[-1])
        ax.annotate(
            f"✕ Invalidation: ${level:,.0f}",
            (last_date, level),
            xytext=(10, 0), textcoords="offset points",
            fontsize=9, color=THEME["invalidation"],
            fontweight="bold", va="center",
            zorder=14,
        )

    # ── Alternative Waves ───────────────────

    def _draw_alternative_waves(
        self, ax: plt.Axes, wave_points: List[Dict], alpha: float = 0.3
    ):
        """대안 시나리오 파동 (반투명)"""
        if not wave_points:
            return

        xs = [mdates.date2num(w["date"]) for w in wave_points]
        ys = [w["price"] for w in wave_points]

        ax.plot(xs, ys, color="#888888", linewidth=1.5, alpha=alpha,
                linestyle="--", zorder=4)

        for wp in wave_points:
            x = mdates.date2num(wp["date"])
            label = wp["label"]
            display = (
                IMPULSE_LABELS.get(label)
                or CORRECTIVE_LABELS.get(label)
                or label
            )
            ax.annotate(
                display, (x, wp["price"]),
                xytext=(0, 10), textcoords="offset points",
                ha="center", fontsize=9, color="#888888", alpha=alpha,
                zorder=12,
            )

    # ── Title & Legend ──────────────────────

    def _draw_title(
        self, ax: plt.Axes,
        symbol: str, timeframe: str,
        pattern_name: str, confidence: float,
        custom_title: str,
    ):
        """차트 상단 타이틀"""
        if custom_title:
            title = custom_title
        else:
            parts = [f"{symbol}"]
            if timeframe:
                parts[0] += f" ({timeframe})"
            parts.append("Elliott Wave Count")
            if pattern_name:
                parts.append(f"— {pattern_name}")
            if confidence:
                parts.append(f"({confidence:.0%})")
            title = " ".join(parts)

        ax.set_title(
            title,
            fontsize=15, fontweight="bold",
            color=THEME["text"], pad=16,
            loc="left",
        )

    def _draw_legend(
        self, ax: plt.Axes,
        wave_points: List[Dict],
        pattern_name: str,
        confidence: float,
    ):
        """우측 상단 범례"""
        handles = []

        # 패턴 정보
        if pattern_name:
            conf_text = f" ({confidence:.0%})" if confidence else ""
            handles.append(mpatches.Patch(
                color=THEME["wave_line"], alpha=0.8,
                label=f"Pattern: {pattern_name}{conf_text}",
            ))

        # 파동 색상 범례
        seen_labels = set()
        for wp in wave_points:
            label = wp["label"]
            if label in seen_labels:
                continue
            seen_labels.add(label)
            color = WAVE_COLORS.get(label, "#ffffff")
            display = (
                IMPULSE_LABELS.get(label)
                or CORRECTIVE_LABELS.get(label)
                or MINOR_LABELS.get(label)
                or label
            )
            handles.append(mpatches.Patch(
                color=color, label=f"Wave {display}",
            ))

        if handles:
            ax.legend(
                handles=handles,
                loc="upper left",
                fontsize=8,
                facecolor=THEME["panel"],
                edgecolor=THEME["grid"],
                labelcolor=THEME["text"],
                framealpha=0.9,
            )

    # ── Axis Formatting ─────────────────────

    def _format_axes(
        self, ax_price: plt.Axes, ax_volume: Optional[plt.Axes],
        df: pd.DataFrame,
    ):
        """축 포맷팅"""
        # X축
        ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax_price.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax_price.xaxis.get_majorticklabels(), rotation=45, ha="right")

        # Y축 — 달러 포맷
        max_price = df["high"].max()
        if max_price >= 1000:
            ax_price.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, _: f"${x:,.0f}")
            )
        else:
            ax_price.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, _: f"${x:,.2f}")
            )

        # 그리드
        ax_price.grid(True, alpha=0.15, color=THEME["grid"], linewidth=0.5)
        ax_price.tick_params(colors=THEME["text_dim"], labelsize=9)

        for spine in ax_price.spines.values():
            spine.set_color(THEME["grid"])

        if ax_volume:
            ax_volume.grid(True, alpha=0.1, color=THEME["grid"])
            ax_volume.tick_params(colors=THEME["text_dim"], labelsize=8)
            ax_volume.set_ylabel("Volume", fontsize=9, color=THEME["text_dim"])
            ax_volume.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, _: f"{x / 1e9:.1f}B" if x >= 1e9 else f"{x / 1e6:.0f}M")
            )
            for spine in ax_volume.spines.values():
                spine.set_color(THEME["grid"])

    # ── Data Helpers ────────────────────────

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame 컬럼 정규화"""
        df = df.copy()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        return df

    def _extract_waves_from_analysis(self, analysis: Any) -> List[Dict]:
        """WaveAnalysis 객체에서 파동 포인트 추출"""
        wave_points = []
        waves = getattr(analysis, "waves", []) or []

        for wave in waves:
            # Wave 객체 (start + end Pivot)
            if hasattr(wave, "start") and hasattr(wave, "end"):
                label = wave.label
                # 시작점 (첫 파동만)
                if not wave_points:
                    wave_points.append({
                        "label": "0",
                        "date": wave.start.timestamp,
                        "price": wave.start.price,
                        "type": wave.start.pivot_type,
                    })
                # 끝점
                wave_points.append({
                    "label": label,
                    "date": wave.end.timestamp,
                    "price": wave.end.price,
                    "type": wave.end.pivot_type,
                })
            # Dict 형태 {label, date, price}
            elif isinstance(wave, dict):
                wp = {
                    "label": str(wave.get("label", "")),
                    "date": pd.to_datetime(wave.get("date")),
                    "price": float(wave.get("price", 0)),
                }
                if "type" in wave:
                    wp["type"] = wave["type"]
                wave_points.append(wp)

        return wave_points

    def _normalize_wave_points(
        self, waves: List[Dict], df: pd.DataFrame
    ) -> List[Dict]:
        """수동 파동 포인트 정규화"""
        result = []
        for w in waves:
            wp = {
                "label": str(w.get("label", "")),
                "date": pd.to_datetime(w.get("date")),
                "price": float(w.get("price", 0)),
            }
            if "type" in w:
                wp["type"] = w["type"]
            result.append(wp)
        return sorted(result, key=lambda x: x["date"])


# ─────────────────────────────────────────────
# CLI + 내장 샘플 데모
# ─────────────────────────────────────────────

# BTC 실제 주요 피벗 포인트 (2022-11 ~ 2025-01)
SAMPLE_BTC_WAVES = [
    {"label": "0", "date": "2022-11-21", "price": 15599, "type": "low"},
    {"label": "1", "date": "2023-07-13", "price": 31815, "type": "high"},
    {"label": "2", "date": "2023-09-11", "price": 24797, "type": "low"},
    {"label": "3", "date": "2024-03-14", "price": 73750, "type": "high"},
    {"label": "4", "date": "2024-08-05", "price": 49121, "type": "low"},
    {"label": "5", "date": "2025-01-20", "price": 109115, "type": "high"},
]

# ABC 조정 시나리오
SAMPLE_BTC_ABC = [
    {"label": "A", "date": "2025-04-07", "price": 75000, "type": "low"},
    {"label": "B", "date": "2025-06-15", "price": 92000, "type": "high"},
    {"label": "C", "date": "2025-09-30", "price": 62000, "type": "low"},
]


def generate_sample_ohlcv() -> pd.DataFrame:
    """
    BTC 유사 샘플 OHLCV 데이터 생성 (외부 의존성 없음)

    실제 BTC 가격 궤적을 근사하는 합성 데이터
    """
    np.random.seed(42)

    dates = pd.date_range("2022-09-01", "2025-06-30", freq="D")
    n = len(dates)

    # 주요 피벗 가격 기반 보간
    key_points = [
        ("2022-09-01", 19800),
        ("2022-11-21", 15599),
        ("2023-07-13", 31815),
        ("2023-09-11", 24797),
        ("2024-03-14", 73750),
        ("2024-08-05", 49121),
        ("2025-01-20", 109115),
        ("2025-06-30", 85000),
    ]

    # 날짜 → 인덱스 매핑
    key_indices = []
    key_prices = []
    for date_str, price in key_points:
        dt = pd.to_datetime(date_str)
        idx = (dt - dates[0]).days
        idx = min(max(0, idx), n - 1)
        key_indices.append(idx)
        key_prices.append(price)

    # 선형 보간 + 노이즈
    close = np.interp(range(n), key_indices, key_prices)

    # 약간의 노이즈 추가 (이동평균으로 스무딩)
    noise = np.random.normal(0, 1, n)
    smooth_noise = pd.Series(noise).rolling(10, min_periods=1).mean().values
    close = close * (1 + smooth_noise * 0.015)

    # OHLCV 생성
    daily_vol = np.abs(np.random.normal(0, 0.02, n))
    high = close * (1 + daily_vol)
    low = close * (1 - daily_vol)
    open_price = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.uniform(15e9, 45e9, n)

    df = pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)

    return df


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Elliott Wave Candlestick Chart")
    parser.add_argument("--sample", action="store_true", help="내장 BTC 샘플 데모 생성")
    parser.add_argument("--csv", help="OHLCV CSV 파일 경로")
    parser.add_argument("-o", "--output", help="출력 경로")
    parser.add_argument("--symbol", default="BTC-USD", help="심볼명")
    parser.add_argument("--no-volume", action="store_true", help="거래량 숨기기")
    args = parser.parse_args()

    chart = WaveChart()

    if args.sample or (not args.csv):
        print("Generating sample BTC chart...")
        df = generate_sample_ohlcv()
        output = args.output or "charts/btc_wave_sample.png"
        path = chart.plot(
            df, waves=SAMPLE_BTC_WAVES,
            symbol="BTC-USD", timeframe="Daily",
            save_path=output,
            show_volume=not args.no_volume,
            title="BTC-USD (Daily) Elliott Wave Count — Impulse 1-2-3-4-5",
        )
        print(f"Chart saved: {path}")

    elif args.csv:
        df = pd.read_csv(args.csv, index_col=0, parse_dates=True)
        output = args.output or f"charts/{args.symbol}_waves.png"
        path = chart.plot(
            df, symbol=args.symbol,
            save_path=output,
            show_volume=not args.no_volume,
        )
        print(f"Chart saved: {path}")


if __name__ == "__main__":
    main()

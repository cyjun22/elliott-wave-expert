"""
Elliott Wave Core Analyzer
==========================
범용 엘리엇 파동 분석 엔진
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from .patterns import (
    Pivot, Wave, PatternType, PatternMatch, 
    PatternRecognizer, WaveDirection, WaveDegree
)
from .validation import WaveValidator, ValidationResult
from .targets import TargetCalculator, TargetLevel


@dataclass
class WaveAnalysis:
    """분석 결과"""
    symbol: str
    timeframe: str
    pivots: List[Pivot]
    waves: List[Wave]
    pattern: PatternType
    pattern_confidence: float
    current_position: str
    targets: Dict[str, TargetLevel]
    invalidation_level: Optional[float]
    validation: ValidationResult
    alternatives: List["WaveAnalysis"] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    notes: str = ""
    
    def summary(self) -> str:
        """분석 요약"""
        lines = [
            f"=== {self.symbol} ({self.timeframe}) Wave Analysis ===",
            f"Pattern: {self.pattern.value} ({self.pattern_confidence:.0%})",
            f"Current: {self.current_position}",
            f"Invalidation: ${self.invalidation_level:,.0f}" if self.invalidation_level else "",
        ]
        
        if self.targets:
            lines.append("\nTargets:")
            for name, target in list(self.targets.items())[:5]:
                lines.append(f"  {target.name}: ${target.price:,.0f}")
        
        return "\n".join(lines)


class ElliottWaveAnalyzer:
    """
    범용 엘리엇 파동 분석기
    
    어떤 심볼, 어떤 타임프레임에서도 동일한 분석 수행
    
    Usage:
        analyzer = ElliottWaveAnalyzer()
        result = analyzer.analyze(df, symbol="BTC-USD")
    """
    
    def __init__(
        self, 
        threshold: float = None,
        min_waves: int = 5
    ):
        """
        Args:
            threshold: Zigzag 임계값 (None = 자동 계산)
            min_waves: 최소 파동 수
        """
        self.threshold = threshold
        self.min_waves = min_waves
        
        # 컴포넌트
        self.pattern_recognizer = PatternRecognizer()
        self.validator = WaveValidator()
        self.target_calculator = TargetCalculator()
    
    def analyze(
        self, 
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        timeframe: str = "daily",
        start_date: str = None,
        direction: WaveDirection = None
    ) -> WaveAnalysis:
        """
        메인 분석 엔트리포인트
        
        Args:
            df: OHLCV 데이터 (columns: open, high, low, close)
            symbol: 심볼명
            timeframe: 타임프레임
            start_date: 분석 시작일 (optional)
            direction: 주요 추세 방향 (None = 자동 감지)
            
        Returns:
            WaveAnalysis: 구조화된 분석 결과
        """
        # 데이터 정규화
        df = self._normalize_df(df)

        # 시작일 필터
        if start_date:
            df = df[df.index >= pd.to_datetime(start_date)]

        if len(df) < 10:
            return self._empty_analysis(symbol, timeframe, "Insufficient data")

        # 입력 데이터 품질 검증
        data_issues = self._validate_input_data(df)
        if data_issues:
            for issue in data_issues:
                if "Insufficient data" in issue:
                    return self._empty_analysis(symbol, timeframe, issue)
        
        # 1. 피벗 감지
        threshold = self.threshold or self._auto_threshold(df)
        pivots = self.detect_pivots(df, threshold)
        
        if len(pivots) < self.min_waves:
            return self._empty_analysis(symbol, timeframe, f"Found {len(pivots)} pivots, need {self.min_waves}")
        
        # 2. 추세 방향 결정
        if direction is None:
            direction = self._detect_direction(df)
        
        # 3. 패턴 인식
        matches = self.pattern_recognizer.recognize(pivots, direction)
        
        if not matches:
            return self._empty_analysis(symbol, timeframe, "No pattern recognized")
        
        best_match = matches[0]
        
        # 4. 규칙 검증
        validation = self.validator.validate(best_match.waves, best_match.pattern_type)
        
        # 5. 목표가 계산
        targets = self._calculate_targets(best_match.waves, best_match.pattern_type)
        
        # 6. 무효화 레벨
        invalidation = self.validator.get_invalidation_level(
            best_match.waves, best_match.pattern_type
        )
        
        # 7. 현재 위치 판단
        current_position = self._determine_position(best_match.waves, df)
        
        # 8. 대안 시나리오
        alternatives = []
        for alt_match in matches[1:3]:  # 상위 2개 대안
            alt_validation = self.validator.validate(alt_match.waves, alt_match.pattern_type)
            alt_targets = self._calculate_targets(alt_match.waves, alt_match.pattern_type)
            alternatives.append(WaveAnalysis(
                symbol=symbol,
                timeframe=timeframe,
                pivots=pivots,
                waves=alt_match.waves,
                pattern=alt_match.pattern_type,
                pattern_confidence=alt_match.confidence,
                current_position=self._determine_position(alt_match.waves, df),
                targets=alt_targets,
                invalidation_level=self.validator.get_invalidation_level(
                    alt_match.waves, alt_match.pattern_type
                ),
                validation=alt_validation
            ))
        
        return WaveAnalysis(
            symbol=symbol,
            timeframe=timeframe,
            pivots=pivots,
            waves=best_match.waves,
            pattern=best_match.pattern_type,
            pattern_confidence=best_match.confidence,
            current_position=current_position,
            targets=targets,
            invalidation_level=invalidation,
            validation=validation,
            alternatives=alternatives
        )
    
    def auto_detect_cycle(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        timeframe: str = "daily"
    ) -> WaveAnalysis:
        """
        자동 사이클 감지 - 구간 분할 알고리즘
        
        핵심: ATL~W5 구간을 5등분하고 각 구간에서 최적 피벗 선택
        
        Args:
            df: OHLCV 데이터
            symbol: 심볼명
            timeframe: 타임프레임
            
        Returns:
            WaveAnalysis: Impulse 파동 분석 결과
        """
        df = self._normalize_df(df)
        
        if len(df) < 50:
            return self._empty_analysis(symbol, timeframe, "Insufficient data for cycle detection")
        
        # 1. ATL (Wave 0) 찾기
        atl_idx = df['low'].idxmin()
        atl = df['low'].min()
        
        # 2. ATL 이후 데이터에서 W5 후보 찾기 (최고점)
        after_atl = df[atl_idx:]
        
        # W5 = 첫 번째 주요 사이클 고점 (ATL + 약 2~2.5년 이내)
        # ATH가 조정 중 B파일 수 있으므로 시간 제한 필요
        # 일반적인 사이클: 4년 반감기 기준 약 2년 정도
        cycle_end_limit = atl_idx + pd.DateOffset(years=2, months=3)
        w5_region = after_atl[after_atl.index <= cycle_end_limit]
        
        if len(w5_region) < 10:
            w5_region = after_atl
        
        w5_idx = w5_region['high'].idxmax()
        w5 = w5_region.loc[w5_idx, 'high']
        
        # 3. W0~W5 구간을 5등분 (W5 포함)
        cycle_df = df[atl_idx:w5_idx]
        # w5_idx도 포함되도록 수정
        cycle_df = df.loc[atl_idx:w5_idx]
        total_days = len(cycle_df)
        
        if total_days < 25:
            return self._empty_analysis(symbol, timeframe, "Cycle too short for segmentation")

        # Fibonacci-proportioned segments: 1 : 0.618 : 1.618 : 0.618 : 1
        fib_ratios = [1.0, 0.618, 1.618, 0.618, 1.0]
        total_ratio = sum(fib_ratios)  # 4.854
        fib_sizes = [int(total_days * r / total_ratio) for r in fib_ratios]
        # Ensure segments sum to total_days
        fib_sizes[-1] = total_days - sum(fib_sizes[:-1])

        segments = []
        offset = 0
        for seg_size in fib_sizes:
            seg_size = max(seg_size, 1)  # at least 1 bar
            segment = cycle_df.iloc[offset:offset + seg_size]
            if len(segment) == 0:
                segment = cycle_df.iloc[offset:offset + 1]

            segments.append({
                'high': segment['high'].max(),
                'high_date': segment['high'].idxmax(),
                'low': segment['low'].min(),
                'low_date': segment['low'].idxmin()
            })
            offset += seg_size
        
        # 4. 파동 할당 (원래 테스트 로직 그대로)
        # (label, pivot_type, price, date)
        wave_list = [
            ('0', 'L', atl, atl_idx),
            ('1', 'H', max(segments[0]['high'], segments[1]['high']),
             segments[0]['high_date'] if segments[0]['high'] > segments[1]['high'] else segments[1]['high_date']),
            ('2', 'L', segments[1]['low'], segments[1]['low_date']),
            ('3', 'H', max(segments[2]['high'], segments[3]['high']),
             segments[2]['high_date'] if segments[2]['high'] > segments[3]['high'] else segments[3]['high_date']),
            ('4', 'L', segments[3]['low'], segments[3]['low_date']),
            ('5', 'H', w5, w5_idx),
        ]
        
        # 시간순 정렬 (원래 라벨 유지) - 검증용
        wave_list_sorted = sorted(wave_list, key=lambda x: x[3])
        
        # Pivot 객체 생성 (라벨 순서대로, 0→1→2→3→4→5)
        # 라벨 기반 딕셔너리
        wave_map = {w[0]: w for w in wave_list}
        
        pivots = {}
        for label in ['0', '1', '2', '3', '4', '5']:
            w = wave_map[label]
            pivots[label] = Pivot(
                timestamp=w[3].to_pydatetime() if hasattr(w[3], 'to_pydatetime') else w[3],
                price=w[2],
                pivot_type='low' if w[1] == 'L' else 'high',
                index=df.index.get_loc(w[3]) if w[3] in df.index else 0
            )
        
        # Wave 객체 생성 (라벨 순서: 0→1, 1→2, 2→3, 3→4, 4→5)
        waves = []
        for i, label in enumerate(['0', '1', '2', '3', '4']):
            start_pivot = pivots[label]
            end_label = str(int(label) + 1)
            end_pivot = pivots[end_label]
            
            direction = WaveDirection.UP if end_pivot.price > start_pivot.price else WaveDirection.DOWN
            
            waves.append(Wave(
                label=label,
                start=start_pivot,
                end=end_pivot,
                direction=direction,
                degree=WaveDegree.CYCLE
            ))
        
        # 7. 규칙 검증
        validation = self.validator.validate(waves, PatternType.IMPULSE)
        
        # 8. 목표가 계산
        targets = self._calculate_targets(waves, PatternType.IMPULSE)
        
        # 9. 무효화 레벨
        invalidation = self.validator.get_invalidation_level(waves, PatternType.IMPULSE)
        
        # 10. 현재 위치
        current_position = self._determine_position(waves, df)
        
        return WaveAnalysis(
            symbol=symbol,
            timeframe=timeframe,
            pivots=pivots,
            waves=waves,
            pattern=PatternType.IMPULSE,
            pattern_confidence=validation.confidence,
            current_position=current_position,
            targets=targets,
            invalidation_level=invalidation,
            validation=validation,
            notes="Auto-detected cycle using segment division algorithm"
        )
    
    def detect_pivots(
        self, 
        df: pd.DataFrame, 
        threshold: float = 0.05
    ) -> List[Pivot]:
        """
        Zigzag 알고리즘으로 피벗 감지
        
        Args:
            df: OHLCV 데이터
            threshold: 변동폭 임계값 (0.05 = 5%)
            
        Returns:
            Pivot 목록
        """
        df = self._normalize_df(df)
        
        highs = df['high'].values
        lows = df['low'].values
        timestamps = df.index.to_pydatetime()
        
        pivots = []
        last_pivot_type = None
        last_pivot_price = None
        last_pivot_idx = 0
        
        # 첫 피벗 설정
        if highs[0] >= lows[0]:
            last_pivot_type = "high"
            last_pivot_price = highs[0]
        else:
            last_pivot_type = "low"
            last_pivot_price = lows[0]
        
        pivots.append(Pivot(
            timestamp=timestamps[0],
            price=last_pivot_price,
            pivot_type=last_pivot_type,
            index=0
        ))
        
        for i in range(1, len(df)):
            current_high = highs[i]
            current_low = lows[i]
            
            if last_pivot_type == "high":
                # 고점 갱신
                if current_high > last_pivot_price:
                    last_pivot_price = current_high
                    last_pivot_idx = i
                    pivots[-1] = Pivot(
                        timestamp=timestamps[i],
                        price=current_high,
                        pivot_type="high",
                        index=i
                    )
                # 저점 전환
                elif (last_pivot_price - current_low) / last_pivot_price >= threshold:
                    pivots.append(Pivot(
                        timestamp=timestamps[i],
                        price=current_low,
                        pivot_type="low",
                        index=i
                    ))
                    last_pivot_type = "low"
                    last_pivot_price = current_low
                    last_pivot_idx = i
            else:
                # 저점 갱신
                if current_low < last_pivot_price:
                    last_pivot_price = current_low
                    last_pivot_idx = i
                    pivots[-1] = Pivot(
                        timestamp=timestamps[i],
                        price=current_low,
                        pivot_type="low",
                        index=i
                    )
                # 고점 전환
                elif (current_high - last_pivot_price) / last_pivot_price >= threshold:
                    pivots.append(Pivot(
                        timestamp=timestamps[i],
                        price=current_high,
                        pivot_type="high",
                        index=i
                    ))
                    last_pivot_type = "high"
                    last_pivot_price = current_high
                    last_pivot_idx = i
        
        return pivots
    
    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """데이터프레임 정규화"""
        df = df.copy()
        
        # MultiIndex 처리
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        
        return df
    
    def _auto_threshold(self, df: pd.DataFrame) -> float:
        """
        Enhanced volatility-adaptive threshold with regime detection.
        
        Uses both recent (14-period) and historical (50-period) ATR to detect
        volatility regimes and adjust thresholds accordingly.
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range calculation
        tr = pd.concat([
            high - low,
            abs(high - close.shift()),
            abs(low - close.shift())
        ], axis=1).max(axis=1)
        
        # Recent volatility (fast)
        atr_fast = tr.rolling(14).mean().iloc[-1]
        
        # Historical volatility (slow baseline)
        atr_slow = tr.rolling(50).mean().iloc[-1] if len(df) >= 50 else atr_fast
        
        avg_price = close.mean()
        
        # Volatility regime detection
        if atr_slow > 0:
            volatility_ratio = atr_fast / atr_slow
        else:
            volatility_ratio = 1.0
        
        # Base threshold from recent ATR
        base_threshold = (atr_fast / avg_price) * 2
        
        # Regime-based adjustment
        if volatility_ratio > 1.5:
            # High volatility regime: increase threshold to capture larger moves
            adjusted_threshold = base_threshold * 1.3
        elif volatility_ratio < 0.7:
            # Low volatility regime: decrease threshold for finer pivots
            adjusted_threshold = base_threshold * 0.8
        else:
            # Normal regime
            adjusted_threshold = base_threshold
        
        # Clamp to reasonable bounds
        return max(0.03, min(0.20, adjusted_threshold))
    
    def _validate_input_data(self, df: pd.DataFrame) -> List[str]:
        """Validate OHLCV data quality before analysis"""
        issues = []
        if len(df) < 30:
            issues.append(f"Insufficient data: {len(df)} candles (minimum 30)")
        # Check for missing values
        null_count = df.isnull().sum().sum()
        if null_count > 0:
            issues.append(f"Missing values detected: {null_count} null entries")
        # Check for duplicate timestamps
        if hasattr(df.index, 'duplicated'):
            dup_count = df.index.duplicated().sum()
            if dup_count > 0:
                issues.append(f"Duplicate timestamps: {dup_count}")
        # Check for price anomalies (>50% single-candle moves)
        closes = df['close'].values
        pct_changes = pd.Series(closes).pct_change().abs()
        extreme_moves = (pct_changes > 0.5).sum()
        if extreme_moves > 0:
            issues.append(f"Extreme price moves detected: {extreme_moves} candles with >50% change")
        return issues

    def _detect_direction(self, df: pd.DataFrame) -> WaveDirection:
        """Multi-period trend detection using SMA slope"""
        closes = df['close'].values
        window = min(20, len(closes) // 3)
        if window < 3:
            return WaveDirection.UP if closes[-1] > closes[0] else WaveDirection.DOWN
        sma = pd.Series(closes).rolling(window).mean().dropna().values
        if len(sma) < 2:
            return WaveDirection.UP if closes[-1] > closes[0] else WaveDirection.DOWN
        slope = (sma[-1] - sma[0]) / len(sma)
        return WaveDirection.UP if slope > 0 else WaveDirection.DOWN
    
    def _calculate_targets(
        self, 
        waves: List[Wave],
        pattern_type: PatternType
    ) -> Dict[str, TargetLevel]:
        """패턴별 목표가 계산"""
        
        if pattern_type == PatternType.IMPULSE:
            all_targets = self.target_calculator.calculate_impulse_targets(waves)
            # Flatten
            targets = {}
            for category, levels in all_targets.items():
                for name, level in levels.items():
                    targets[f"{category}_{name}"] = level
            return targets
        
        elif pattern_type in [PatternType.ZIGZAG, PatternType.FLAT, 
                              PatternType.EXPANDED_FLAT, PatternType.RUNNING_FLAT]:
            return self.target_calculator.calculate_correction_targets(
                waves, pattern_type
            )
        
        return {}
    
    def _determine_position(
        self, 
        waves: List[Wave],
        df: pd.DataFrame
    ) -> str:
        """현재 파동 위치 판단"""
        if not waves:
            return "Unknown"
        
        last_wave = waves[-1]
        current_price = df['close'].iloc[-1]
        
        # 마지막 파동 이후 진행 판단
        if current_price > last_wave.end.price:
            return f"After {last_wave.label}, moving higher"
        elif current_price < last_wave.end.price:
            return f"After {last_wave.label}, moving lower"
        else:
            return f"At {last_wave.label} end"
    
    def _empty_analysis(
        self, 
        symbol: str, 
        timeframe: str,
        reason: str
    ) -> WaveAnalysis:
        """빈 분석 결과 반환"""
        return WaveAnalysis(
            symbol=symbol,
            timeframe=timeframe,
            pivots=[],
            waves=[],
            pattern=PatternType.UNKNOWN,
            pattern_confidence=0.0,
            current_position="Unknown",
            targets={},
            invalidation_level=None,
            validation=ValidationResult(
                is_valid=False,
                violations=[reason],
                warnings=[],
                confidence=0.0
            ),
            notes=reason
        )
    
    # ===== Convenience Methods =====
    
    def quick_analyze(
        self, 
        symbol: str = "BTC-USD",
        period: str = "1y",
        interval: str = "1d"
    ) -> WaveAnalysis:
        """
        빠른 분석 (yfinance 사용)
        
        Usage:
            result = analyzer.quick_analyze("BTC-USD")
        """
        try:
            import yfinance as yf
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            return self.analyze(df, symbol=symbol, timeframe=interval)
        except ImportError:
            raise ImportError("yfinance required: pip install yfinance")
    
    def get_targets_summary(
        self, 
        analysis: WaveAnalysis,
        current_price: float = None
    ) -> str:
        """목표가 요약 텍스트"""
        lines = [f"=== {analysis.pattern.value} Targets ==="]
        
        for name, target in analysis.targets.items():
            marker = "→" if target.is_primary else " "
            status = ""
            if current_price:
                if current_price < target.price:
                    status = "(above)"
                else:
                    status = "(below ✓)"
            lines.append(f"{marker} {target.name}: ${target.price:,.0f} {status}")
        
        if analysis.invalidation_level:
            lines.append(f"\n⚠️ Invalidation: ${analysis.invalidation_level:,.0f}")
        
        return "\n".join(lines)

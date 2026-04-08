"""
Multi-Timeframe Validation for Elliott Wave Analysis
=====================================================

Daily/4H/1H 타임프레임 교차 검증으로 파동 분석 신뢰도 향상

핵심 원리:
- Daily Wave 3 = 4H Wave (3) = 1H Wave ((3))
- 3개 타임프레임 중 2개 이상 일치하면 신뢰

Based on: WaveBasis, EWAVES, ElliottAgents research
"""

import pandas as pd
import yfinance as yf
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class WaveCount:
    """단일 타임프레임 파동 카운트"""
    timeframe: str
    waves: Dict[str, dict]  # {'0': {...}, '1': {...}, ...}
    current_phase: str  # 'impulse_3', 'correction_B', etc.
    confidence: float
    

@dataclass 
class ConsensusResult:
    """다중 타임프레임 합의 결과"""
    is_valid: bool
    confidence: float
    aligned_phase: str  # 가장 일치하는 현재 단계
    timeframe_agreement: Dict[str, bool]
    warnings: List[str]


class MultiTimeframeValidator:
    """
    다중 타임프레임 Elliott Wave 검증기
    
    Daily/4H/1H 파동 카운트를 교차 검증하여 신뢰도 향상
    """
    
    # 타임프레임 → Degree 매핑
    DEGREE_MAP = {
        '1d': 'Cycle',      # Daily = Cycle degree
        '4h': 'Primary',    # 4H = Primary degree  
        '1h': 'Intermediate' # 1H = Intermediate degree
    }
    
    # Degree 계층
    DEGREE_HIERARCHY = ['Supercycle', 'Cycle', 'Primary', 'Intermediate', 'Minor']
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.wave_counts: Dict[str, WaveCount] = {}
        
    def fetch_multi_timeframe_data(
        self, 
        timeframes: List[str] = ['1d', '4h', '1h'],
        period: str = '2y'
    ) -> Dict[str, pd.DataFrame]:
        """여러 타임프레임 데이터 가져오기"""
        data = {}
        
        for tf in timeframes:
            try:
                if tf == '1d':
                    df = yf.download(self.symbol, period=period, interval='1d', progress=False)
                elif tf == '4h':
                    # 4시간 데이터는 60일 제한
                    df = yf.download(self.symbol, period='60d', interval='1h', progress=False)
                    
                    # MultiIndex 컬럼 처리
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    
                    # 대소문자 정규화
                    df.columns = [c.title() for c in df.columns]
                    
                    # 4시간으로 리샘플
                    df = df.resample('4h').agg({
                        'Open': 'first', 'High': 'max', 'Low': 'min', 
                        'Close': 'last', 'Volume': 'sum'
                    }).dropna()
                elif tf == '1h':
                    df = yf.download(self.symbol, period='30d', interval='1h', progress=False)
                else:
                    continue
                
                # MultiIndex 컬럼 정규화
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [c.title() for c in df.columns]
                    
                data[tf] = df
                print(f"📊 {tf}: {len(df)} bars loaded")
                
            except Exception as e:
                print(f"⚠️ {tf} 데이터 로드 실패: {e}")
                
        return data
    
    def analyze_timeframe(
        self, 
        df: pd.DataFrame, 
        timeframe: str
    ) -> WaveCount:
        """단일 타임프레임 파동 분석"""
        from experts.elliott.wave_tracker import WaveTracker
        
        tracker = WaveTracker(self.symbol)
        
        # 분석 실행
        close_col = 'Close' if 'Close' in df.columns else 'close'
        
        # 피벗 감지 (간단 버전)
        waves = self._detect_waves_simplified(df)
        
        # 현재 단계 판단
        current_phase = self._determine_current_phase(waves, df[close_col].iloc[-1])
        
        # 신뢰도 계산
        confidence = self._calculate_wave_confidence(waves, df)
        
        return WaveCount(
            timeframe=timeframe,
            waves=waves,
            current_phase=current_phase,
            confidence=confidence
        )
    
    def _detect_waves_simplified(self, df: pd.DataFrame) -> Dict[str, dict]:
        """간단한 피벗 기반 파동 감지"""
        close_col = 'Close' if 'Close' in df.columns else 'close'
        high_col = 'High' if 'High' in df.columns else 'high'
        low_col = 'Low' if 'Low' in df.columns else 'low'
        
        # 주요 저점/고점 찾기
        window = max(10, len(df) // 20)
        
        # rolling max/min과 비교
        rolling_high = df[high_col].rolling(window, center=True, min_periods=1).max()
        rolling_low = df[low_col].rolling(window, center=True, min_periods=1).min()
        
        pivots = []
        for i in range(len(df)):
            date = df.index[i]
            high_val = df[high_col].iloc[i]
            low_val = df[low_col].iloc[i]
            
            # MultiIndex 처리
            if hasattr(high_val, 'values'):
                high_val = high_val.values[0] if len(high_val.values) > 0 else high_val
            if hasattr(low_val, 'values'):
                low_val = low_val.values[0] if len(low_val.values) > 0 else low_val
            
            rolling_h = rolling_high.iloc[i]
            rolling_l = rolling_low.iloc[i]
            
            if hasattr(rolling_h, 'values'):
                rolling_h = rolling_h.values[0] if len(rolling_h.values) > 0 else rolling_h
            if hasattr(rolling_l, 'values'):
                rolling_l = rolling_l.values[0] if len(rolling_l.values) > 0 else rolling_l
            
            if high_val == rolling_h:
                pivots.append({'date': date, 'price': float(high_val), 'type': 'high'})
            elif low_val == rolling_l:
                pivots.append({'date': date, 'price': float(low_val), 'type': 'low'})
        
        # 상위 N개 피벗만 사용
        pivots = self._filter_significant_pivots(pivots, n=10)
        
        # 파동 라벨링 (0-1-2-3-4-5 시도)
        waves = self._label_waves(pivots)
        
        return waves
    
    def _filter_significant_pivots(
        self, 
        pivots: List[dict], 
        n: int = 10
    ) -> List[dict]:
        """중요도가 높은 피벗만 필터링"""
        if len(pivots) <= n:
            return pivots
            
        # 가격 변동폭으로 중요도 정렬
        for i, p in enumerate(pivots):
            if i == 0:
                p['significance'] = 0
            else:
                p['significance'] = abs(p['price'] - pivots[i-1]['price'])
        
        pivots.sort(key=lambda x: x['significance'], reverse=True)
        return sorted(pivots[:n], key=lambda x: x['date'])
    
    def _label_waves(self, pivots: List[dict]) -> Dict[str, dict]:
        """피벗에 파동 라벨 부여"""
        waves = {}
        
        if len(pivots) < 2:
            return waves
            
        # 시작점이 저점인지 확인
        start_type = pivots[0]['type']
        
        labels = ['0', '1', '2', '3', '4', '5', 'A', 'B', 'C']
        label_idx = 0
        
        for p in pivots:
            if label_idx >= len(labels):
                break
            waves[labels[label_idx]] = {
                'price': p['price'],
                'date': p['date'],
                'type': p['type']
            }
            label_idx += 1
            
        return waves
    
    def _determine_current_phase(
        self, 
        waves: Dict[str, dict], 
        current_price: float
    ) -> str:
        """현재 파동 단계 판단"""
        if not waves:
            return 'unknown'
            
        labels = list(waves.keys())
        last_wave = labels[-1]
        
        if last_wave in ['0', '1', '2', '3', '4']:
            return f'impulse_{last_wave}'
        elif last_wave == '5':
            return 'impulse_complete'
        elif last_wave in ['A', 'B', 'C']:
            return f'correction_{last_wave}'
        else:
            return 'unknown'
    
    def _calculate_wave_confidence(
        self, 
        waves: Dict[str, dict], 
        df: pd.DataFrame
    ) -> float:
        """파동 카운트 신뢰도 계산"""
        confidence = 0.5  # 기본값
        
        if len(waves) >= 6:  # 0-5 완료
            confidence += 0.2
            
            # Wave 3 > Wave 1 검증
            w3_move = 0
            if '3' in waves and '1' in waves and '0' in waves:
                w1_move = waves['1']['price'] - waves['0']['price']
                w3_move = waves['3']['price'] - waves['2']['price']

                if abs(w3_move) > abs(w1_move):
                    confidence += 0.15

            # Wave 3이 가장 짧지 않음 검증
            if '5' in waves and w3_move != 0:
                w5_move = waves['5']['price'] - waves['4']['price']
                if abs(w3_move) > abs(w5_move):
                    confidence += 0.1
                    
        return min(confidence, 1.0)
    
    def align_wave_degrees(
        self, 
        counts: Dict[str, WaveCount]
    ) -> Dict[str, WaveCount]:
        """
        타임프레임별 Degree 정렬
        
        Daily Wave 3 진행 중이면:
        - 4H에서는 Wave (3) 내부 구조 확인
        - 1H에서는 Wave ((3)) 내부 구조 확인
        """
        # 가장 높은 타임프레임 기준
        if '1d' not in counts:
            return counts
            
        daily_phase = counts['1d'].current_phase
        
        # Degree 라벨 조정
        for tf, count in counts.items():
            degree = self.DEGREE_MAP.get(tf, 'Intermediate')
            
            # 파동 라벨에 degree 접두사 추가
            for label, wave in count.waves.items():
                wave['degree'] = degree
                
        return counts
    
    def find_consensus(
        self, 
        counts: Dict[str, WaveCount],
        threshold: int = 2
    ) -> ConsensusResult:
        """
        다중 타임프레임 합의 찾기
        
        Args:
            counts: 타임프레임별 파동 카운트
            threshold: 최소 일치 타임프레임 수 (기본 2)
            
        Returns:
            ConsensusResult with confidence and alignment info
        """
        if len(counts) < 2:
            return ConsensusResult(
                is_valid=False,
                confidence=0.0,
                aligned_phase='unknown',
                timeframe_agreement={},
                warnings=['Insufficient timeframes for consensus']
            )
        
        # 현재 단계별 카운트
        phase_votes = {}
        for tf, count in counts.items():
            phase = count.current_phase
            if phase not in phase_votes:
                phase_votes[phase] = []
            phase_votes[phase].append(tf)
        
        # 가장 많은 투표 받은 단계
        best_phase = max(phase_votes.keys(), key=lambda x: len(phase_votes[x]))
        agreement_count = len(phase_votes[best_phase])
        
        # 일치 여부
        timeframe_agreement = {
            tf: (counts[tf].current_phase == best_phase) 
            for tf in counts
        }
        
        # 평균 신뢰도
        avg_confidence = sum(c.confidence for c in counts.values()) / len(counts)
        
        # 합의 여부
        is_valid = agreement_count >= threshold
        
        # 경고 메시지
        warnings = []
        if not is_valid:
            warnings.append(f"Only {agreement_count}/{len(counts)} timeframes agree")
        
        for tf, agreed in timeframe_agreement.items():
            if not agreed:
                warnings.append(f"{tf} shows {counts[tf].current_phase} (disagrees)")
        
        return ConsensusResult(
            is_valid=is_valid,
            confidence=avg_confidence if is_valid else avg_confidence * 0.5,
            aligned_phase=best_phase,
            timeframe_agreement=timeframe_agreement,
            warnings=warnings
        )
    
    def validate(
        self, 
        timeframes: List[str] = ['1d', '4h', '1h']
    ) -> ConsensusResult:
        """
        전체 검증 파이프라인 실행
        
        Returns:
            ConsensusResult with validation outcome
        """
        print(f"\n{'='*60}")
        print(f"🔍 Multi-Timeframe Validation: {self.symbol}")
        print(f"{'='*60}\n")
        
        # 1. 데이터 가져오기
        data = self.fetch_multi_timeframe_data(timeframes)
        
        if len(data) < 2:
            return ConsensusResult(
                is_valid=False, confidence=0, aligned_phase='unknown',
                timeframe_agreement={}, warnings=['Insufficient data']
            )
        
        # 2. 각 타임프레임 분석
        print("\n📊 Analyzing each timeframe...")
        for tf, df in data.items():
            self.wave_counts[tf] = self.analyze_timeframe(df, tf)
            print(f"   {tf}: {self.wave_counts[tf].current_phase} "
                  f"(confidence: {self.wave_counts[tf].confidence:.1%})")
        
        # 3. Degree 정렬
        aligned = self.align_wave_degrees(self.wave_counts)
        
        # 4. 합의 찾기
        consensus = self.find_consensus(aligned)
        
        # 5. 결과 출력
        print(f"\n{'='*60}")
        print(f"📋 Consensus Result:")
        print(f"   Valid: {'✅' if consensus.is_valid else '❌'}")
        print(f"   Confidence: {consensus.confidence:.1%}")
        print(f"   Aligned Phase: {consensus.aligned_phase}")
        
        if consensus.warnings:
            print(f"\n⚠️ Warnings:")
            for w in consensus.warnings:
                print(f"   - {w}")
        
        print(f"{'='*60}\n")
        
        return consensus


# 테스트 함수
def test_multi_timeframe():
    """테스트 실행"""
    validator = MultiTimeframeValidator('BTC-USD')
    result = validator.validate()
    return result


if __name__ == '__main__':
    test_multi_timeframe()

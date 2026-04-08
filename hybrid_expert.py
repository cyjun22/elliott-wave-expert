"""
Hybrid Elliott Wave Expert - 알고리즘 + LLM + RAG 통합
======================================================
최고의 엘리엇 전문가 역량을 구현하는 하이브리드 시스템
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

# 알고리즘 엔진
from experts.elliott.core import ElliottWaveAnalyzer, WaveAnalysis
from experts.elliott.patterns import Wave, Pivot, PatternType, WaveDegree, WaveDirection

# LLM 검증기
try:
    from experts.elliott.llm_validator import LLMWaveValidator, ValidationResult, CycleEstimate
    LLM_VALIDATOR_AVAILABLE = True
except ImportError:
    LLM_VALIDATOR_AVAILABLE = False


@dataclass
class HybridAnalysisResult:
    """하이브리드 분석 결과"""
    # 알고리즘 결과
    algorithm_result: WaveAnalysis
    
    # LLM 검증 결과
    llm_validation: Optional[ValidationResult]
    cycle_estimate: Optional[CycleEstimate]
    
    # 최종 결과
    final_waves: List[Wave]
    final_confidence: float
    is_llm_enhanced: bool
    
    # 메타정보
    processing_info: Dict


class HybridElliottExpert:
    """
    하이브리드 Elliott Wave 전문가
    
    3-레이어 아키텍처:
    1. Algorithm Layer: 빠른 후보 생성 (auto_detect_cycle)
    2. RAG Layer: Elliott Wave 지식 검색
    3. LLM Layer: 검증 및 교정
    
    비용 최적화:
    - 고신뢰도 알고리즘 결과 → LLM 스킵
    - 불확실한 결과 → Flash 2.0 사용
    """
    
    def __init__(
        self,
        enable_llm: bool = True,
        enable_rag: bool = True,
        confidence_threshold: float = 0.85
    ):
        """
        Args:
            enable_llm: LLM 검증 활성화
            enable_rag: RAG 지식 검색 활성화
            confidence_threshold: 이 값 이상이면 LLM 스킵 (비용 최적화)
        """
        # 알고리즘 엔진
        self.analyzer = ElliottWaveAnalyzer()
        
        # LLM 검증기
        if enable_llm and LLM_VALIDATOR_AVAILABLE:
            self.validator = LLMWaveValidator(enable_rag=enable_rag)
            self.llm_enabled = self.validator.available
        else:
            self.validator = None
            self.llm_enabled = False
        
        self.confidence_threshold = confidence_threshold
    
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str = "1d",
        force_llm: bool = False
    ) -> HybridAnalysisResult:
        """
        하이브리드 분석 실행
        
        Args:
            df: OHLCV 데이터프레임
            symbol: 자산 심볼
            timeframe: 타임프레임
            force_llm: True면 신뢰도와 관계없이 LLM 사용
        
        Returns:
            HybridAnalysisResult: 하이브리드 분석 결과
        """
        processing_info = {
            'algorithm_used': True,
            'llm_used': False,
            'rag_used': False,
            'skipped_reason': None
        }
        
        # === 1. Algorithm Layer: 빠른 후보 생성 ===
        algo_result = self.analyzer.auto_detect_cycle(df, symbol, timeframe)
        
        # 알고리즘 신뢰도
        algo_confidence = algo_result.pattern_confidence
        
        # === 2. LLM 필요 여부 결정 ===
        need_llm = (
            force_llm or 
            algo_confidence < self.confidence_threshold or
            not algo_result.validation.is_valid
        )
        
        if not need_llm:
            processing_info['skipped_reason'] = f"High confidence ({algo_confidence:.0%})"
            return HybridAnalysisResult(
                algorithm_result=algo_result,
                llm_validation=None,
                cycle_estimate=None,
                final_waves=algo_result.waves,
                final_confidence=algo_confidence,
                is_llm_enhanced=False,
                processing_info=processing_info
            )
        
        # LLM 없으면 알고리즘 결과 반환
        if not self.llm_enabled:
            processing_info['skipped_reason'] = "LLM not available"
            return HybridAnalysisResult(
                algorithm_result=algo_result,
                llm_validation=None,
                cycle_estimate=None,
                final_waves=algo_result.waves,
                final_confidence=algo_confidence,
                is_llm_enhanced=False,
                processing_info=processing_info
            )
        
        # === 3. LLM Layer: 검증 및 교정 ===
        processing_info['llm_used'] = True
        
        # 3.1 사이클 기간 추정
        cycle_estimate = self._get_cycle_estimate(df, symbol)
        
        # 3.2 사용 가능한 피벗 포인트 추출
        available_pivots = self._extract_available_pivots(df)
        
        # 3.3 파동 구조 검증 (피벗 리스트 포함)
        wave_dicts = self._waves_to_dicts(algo_result.waves)
        llm_validation = self.validator.validate_wave_structure(
            waves=wave_dicts,
            symbol=symbol,
            timeframe=timeframe,
            available_pivots=available_pivots
        )
        
        if self.validator.rag is not None:
            processing_info['rag_used'] = True
        
        # === 4. Self-Correction: LLM 교정 적용 ===
        final_waves = algo_result.waves
        corrections_applied = []
        
        if llm_validation.corrections and len(llm_validation.corrections) > 0:
            # LLM 교정 적용
            final_waves, corrections_applied = self._apply_corrections(
                waves=algo_result.waves,
                corrections=llm_validation.corrections,
                df=df
            )
            processing_info['corrections_applied'] = corrections_applied
        
        # 신뢰도 조정
        final_confidence = self._combine_confidence(
            algo_confidence=algo_confidence,
            llm_validation=llm_validation
        )
        
        # 교정 적용 시 신뢰도 보정
        if corrections_applied:
            # 교정이 적용되면 LLM 신뢰도 기준으로 보정
            final_confidence = min(1.0, final_confidence + 0.1)
        
        return HybridAnalysisResult(
            algorithm_result=algo_result,
            llm_validation=llm_validation,
            cycle_estimate=cycle_estimate,
            final_waves=final_waves,
            final_confidence=final_confidence,
            is_llm_enhanced=True,
            processing_info=processing_info
        )
    
    def _get_cycle_estimate(self, df: pd.DataFrame, symbol: str) -> CycleEstimate:
        """사이클 기간 추정"""
        df = df.copy()
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]

        atl_idx = df['low'].idxmin()
        atl_price = df['low'].min()
        ath_idx = df['high'].idxmax()
        ath_price = df['high'].max()
        
        return self.validator.estimate_cycle_duration(
            symbol=symbol,
            atl_price=atl_price,
            atl_date=atl_idx.to_pydatetime() if hasattr(atl_idx, 'to_pydatetime') else atl_idx,
            ath_price=ath_price,
            ath_date=ath_idx.to_pydatetime() if hasattr(ath_idx, 'to_pydatetime') else ath_idx,
            data_start=df.index[0].to_pydatetime() if hasattr(df.index[0], 'to_pydatetime') else df.index[0],
            data_end=df.index[-1].to_pydatetime() if hasattr(df.index[-1], 'to_pydatetime') else df.index[-1]
        )
    
    def _waves_to_dicts(self, waves: List[Wave]) -> List[Dict]:
        """Wave 객체를 딕셔너리로 변환"""
        result = []
        
        # Wave 0의 시작점
        if waves:
            first_wave = waves[0]
            result.append({
                'label': '0',
                'price': first_wave.start.price,
                'date': first_wave.start.timestamp.strftime('%Y-%m-%d') if hasattr(first_wave.start.timestamp, 'strftime') else str(first_wave.start.timestamp),
                'type': first_wave.start.pivot_type
            })
        
        # 각 Wave의 끝점
        for i, w in enumerate(waves):
            result.append({
                'label': str(i + 1),
                'price': w.end.price,
                'date': w.end.timestamp.strftime('%Y-%m-%d') if hasattr(w.end.timestamp, 'strftime') else str(w.end.timestamp),
                'type': w.end.pivot_type
            })
        
        return result
    
    def _extract_available_pivots(self, df: pd.DataFrame, window: int = 20, max_pivots: int = 30) -> List[Dict]:
        """
        데이터에서 주요 피벗 포인트 추출
        
        Args:
            df: OHLCV 데이터프레임
            window: 피벗 탐지 윈도우 (일)
            max_pivots: 최대 반환 피벗 수
        
        Returns:
            피벗 리스트 [{'date': '2023-06-15', 'price': 24797, 'type': 'low'}, ...]
        """
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df_work = df.copy()
            df_work.columns = [c[0].lower() for c in df_work.columns]
        else:
            df_work = df
        
        pivots = []
        
        # Rolling window로 로컬 high/low 찾기
        high_col = df_work['high']
        low_col = df_work['low']
        
        # 로컬 고점: window 내 최대값
        rolling_max = high_col.rolling(window=window, center=True).max()
        local_highs = df_work[high_col == rolling_max].copy()
        
        # 로컬 저점: window 내 최소값  
        rolling_min = low_col.rolling(window=window, center=True).min()
        local_lows = df_work[low_col == rolling_min].copy()
        
        # 고점 추가
        for idx, row in local_highs.iterrows():
            pivots.append({
                'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                'price': float(row['high']),
                'type': 'high'
            })
        
        # 저점 추가
        for idx, row in local_lows.iterrows():
            pivots.append({
                'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                'price': float(row['low']),
                'type': 'low'
            })
        
        # 중복 제거 (날짜+타입 기준)
        seen = set()
        unique_pivots = []
        for p in pivots:
            key = (p['date'], p['type'])
            if key not in seen:
                seen.add(key)
                unique_pivots.append(p)
        
        # 날짜순 정렬
        unique_pivots.sort(key=lambda x: x['date'])
        
        # 최대 개수 제한
        return unique_pivots[:max_pivots]
    
    def _apply_corrections(
        self,
        waves: List[Wave],
        corrections: List[Dict],
        df: pd.DataFrame
    ) -> tuple:
        """
        LLM 교정을 Wave 객체에 적용
        
        Args:
            waves: 원본 Wave 리스트
            corrections: LLM이 제안한 교정 리스트
                [{"wave": "4", "current_price": 49121, "suggested_price": 52000, "reason": "..."}]
            df: 원본 OHLCV 데이터 (교정된 가격의 날짜 찾기용)
        
        Returns:
            (corrected_waves, applied_corrections)
        """
        import copy
        
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df_copy = df.copy()
            df_copy.columns = [c[0].lower() for c in df_copy.columns]
        else:
            df_copy = df
        
        corrected_waves = copy.deepcopy(waves)
        applied = []
        
        for correction in corrections:
            try:
                wave_label_raw = str(correction.get('wave', ''))
                suggested_price = correction.get('suggested_price')
                reason = correction.get('reason', '')
                
                if not wave_label_raw or not suggested_price:
                    continue
                
                # "Wave 4" → "4" 정규화
                import re
                wave_match = re.search(r'(\d+)', wave_label_raw)
                if not wave_match:
                    continue
                wave_label = wave_match.group(1)
                
                # Wave 라벨에 해당하는 Wave 찾기
                wave_idx = int(wave_label) - 1  # Wave 1 → index 0
                
                if wave_idx < 0 or wave_idx >= len(corrected_waves):
                    continue
                
                target_wave = corrected_waves[wave_idx]
                old_price = target_wave.end.price
                
                # 새로운 가격에 가까운 날짜 찾기
                price_col = 'high' if target_wave.end.pivot_type == 'high' else 'low'
                
                # 가장 가까운 가격의 날짜 찾기 (원본 Wave 날짜 근처에서)
                original_date = target_wave.end.timestamp
                search_window = 90  # 90일 범위 (확장)
                
                if hasattr(original_date, 'strftime'):
                    start_search = original_date - pd.Timedelta(days=search_window)
                    end_search = original_date + pd.Timedelta(days=search_window)
                    window_df = df_copy[start_search:end_search]
                else:
                    window_df = df_copy
                
                if len(window_df) > 0:
                    # 제안된 가격에 가장 가까운 날짜 찾기
                    price_diff = abs(window_df[price_col] - suggested_price)
                    best_date = price_diff.idxmin()
                    best_price = float(window_df.loc[best_date, price_col])
                    
                    # 가격 허용치: 제안 가격의 ±10% 이내여야 적용
                    tolerance = suggested_price * 0.1
                    if abs(best_price - suggested_price) > tolerance:
                        print(f"⚠️ No suitable price found for Wave {wave_label}")
                        print(f"   Suggested: ${suggested_price:,.0f}, Best found: ${best_price:,.0f}")
                        continue
                    
                    # Pivot 업데이트
                    new_pivot = Pivot(
                        timestamp=best_date.to_pydatetime() if hasattr(best_date, 'to_pydatetime') else best_date,
                        price=best_price,
                        pivot_type=target_wave.end.pivot_type,
                        index=df_copy.index.get_loc(best_date) if best_date in df_copy.index else target_wave.end.index
                    )
                    
                    # Wave 객체의 end 업데이트
                    corrected_waves[wave_idx] = Wave(
                        label=target_wave.label,
                        start=target_wave.start,
                        end=new_pivot,
                        direction=target_wave.direction,
                        degree=target_wave.degree
                    )
                    
                    # 다음 Wave의 start도 업데이트 (연결)
                    if wave_idx + 1 < len(corrected_waves):
                        next_wave = corrected_waves[wave_idx + 1]
                        corrected_waves[wave_idx + 1] = Wave(
                            label=next_wave.label,
                            start=new_pivot,
                            end=next_wave.end,
                            direction=next_wave.direction,
                            degree=next_wave.degree
                        )
                    
                    applied.append({
                        'wave': wave_label,
                        'old_price': old_price,
                        'new_price': float(best_price),
                        'new_date': str(best_date.date()) if hasattr(best_date, 'date') else str(best_date),
                        'reason': reason
                    })
                    
            except Exception as e:
                print(f"⚠️ Correction failed for wave {wave_label}: {e}")
                continue
        
        return corrected_waves, applied
    
    def _combine_confidence(
        self,
        algo_confidence: float,
        llm_validation: ValidationResult
    ) -> float:
        """알고리즘과 LLM 신뢰도 결합"""
        if not llm_validation.llm_used:
            return algo_confidence
        
        # 가중 평균 (알고리즘 60%, LLM 40%)
        combined = (algo_confidence * 0.6) + (llm_validation.confidence * 0.4)
        
        # LLM이 유효하지 않다고 판단하면 페널티
        if not llm_validation.is_valid:
            combined *= 0.7
        
        return min(1.0, combined)


# === 테스트 ===
if __name__ == "__main__":
    print("=== Hybrid Elliott Expert Test ===\n")
    
    import yfinance as yf
    
    # 데이터 로드
    df = yf.download('BTC-USD', start='2022-01-01', progress=False)
    
    # 하이브리드 Expert 생성
    expert = HybridElliottExpert(
        enable_llm=True,
        enable_rag=True,
        confidence_threshold=0.85
    )
    
    print(f"LLM enabled: {expert.llm_enabled}")
    
    # 분석 실행
    print("\n--- Hybrid Analysis ---")
    result = expert.analyze(df, symbol="BTC-USD", force_llm=True)
    
    print(f"\n=== Results ===")
    print(f"Algorithm confidence: {result.algorithm_result.pattern_confidence:.0%}")
    print(f"Final confidence: {result.final_confidence:.0%}")
    print(f"LLM enhanced: {result.is_llm_enhanced}")
    print(f"Processing: {result.processing_info}")
    
    if result.cycle_estimate:
        print(f"\nCycle estimate: {result.cycle_estimate.cycle_months} months")
        print(f"  Reasoning: {result.cycle_estimate.reasoning}")
    
    if result.llm_validation:
        print(f"\nLLM validation: {'✅ Valid' if result.llm_validation.is_valid else '❌ Invalid'}")
        print(f"  Confidence: {result.llm_validation.confidence:.0%}")
        print(f"  Reasoning: {result.llm_validation.reasoning}")
    
    print(f"\n=== Final Waves ===")
    for w in result.final_waves:
        print(f"Wave {w.label}: ${w.start.price:,.0f} → ${w.end.price:,.0f}")

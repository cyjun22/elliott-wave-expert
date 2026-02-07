"""
Sub-Wave Analyzer - 프랙탈 파동 분석
====================================

핵심 기능:
- Wave 3 내부의 1-2-3-4-5 서브파동 감지
- 최적 진입점 (Sub-wave 3) 식별
- 재귀적 파동 분석
- 거래량 검증 (Wave 3 > Wave 1, 5)
- 시간 비율 검증 (피보나치 시간)

Based on: Elliott Wave Principle, ElliottAgents research
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class SubWave:
    """서브파동 구조"""
    parent_wave: str  # '3' = Wave 3 내부
    sub_label: str    # '(1)', '(2)', ...
    price: float
    date: datetime
    volume: float = 0.0
    is_strongest: bool = False  # 가장 강력한 서브파동 여부


@dataclass
class VolumeProfile:
    """거래량 프로파일"""
    wave_label: str
    avg_volume: float
    peak_volume: float
    volume_ratio: float  # 전체 평균 대비
    is_valid: bool = True  # Wave 3 검증 여부


@dataclass
class TimeRatio:
    """시간 비율 분석"""
    wave_pair: str  # 'W2/W1', 'W4/W2', etc.
    ratio: float
    fibonacci_match: str  # '0.618', '1.0', '1.618', 'none'
    is_valid: bool = True


class SubWaveAnalyzer:
    """
    서브파동 분석기
    
    주파동 내부의 세부 구조 분석
    """
    
    # 피보나치 시간 비율
    FIB_TIME_RATIOS = [0.382, 0.5, 0.618, 1.0, 1.618, 2.618]
    RATIO_TOLERANCE = 0.15  # 15% 허용 오차
    
    def __init__(self, df: pd.DataFrame, waves: Dict[str, Dict]):
        """
        Args:
            df: OHLCV 데이터프레임
            waves: 주파동 데이터 {'0': {...}, '1': {...}, ...}
        """
        self.df = df
        self.waves = waves
        self.sub_waves: Dict[str, List[SubWave]] = {}
        self.volume_profiles: Dict[str, VolumeProfile] = {}
        self.time_ratios: List[TimeRatio] = []
        
    def analyze_all(self) -> Dict:
        """전체 분석 실행"""
        results = {
            'sub_waves': {},
            'volume_validation': {},
            'time_validation': {},
            'entry_zones': [],
            'warnings': []
        }
        
        # 1. 서브파동 분석 (Wave 1, 3, 5에 대해)
        for wave_label in ['1', '3', '5']:
            if wave_label in self.waves:
                sub_waves = self.detect_sub_waves(wave_label)
                results['sub_waves'][wave_label] = sub_waves
        
        # 2. 거래량 검증
        volume_result = self.validate_volume()
        results['volume_validation'] = volume_result
        
        # 3. 시간 비율 검증
        time_result = self.validate_time_ratios()
        results['time_validation'] = time_result
        
        # 4. 진입 구간 식별
        if '3' in results['sub_waves'] and results['sub_waves']['3']:
            entry_zones = self.find_entry_zones(results['sub_waves']['3'])
            results['entry_zones'] = entry_zones
        
        # 5. 경고사항
        results['warnings'] = self._generate_warnings(results)
        
        return results
    
    def detect_sub_waves(self, parent_wave: str) -> List[SubWave]:
        """주파동 내 서브파동 감지"""
        if parent_wave not in self.waves:
            return []
        
        # 이전 파동과 현재 파동 사이의 데이터
        prev_label = str(int(parent_wave) - 1) if parent_wave != '0' else '0'
        
        if prev_label not in self.waves:
            return []
        
        start_date = self.waves[prev_label].get('date')
        end_date = self.waves[parent_wave].get('date')
        
        if not start_date or not end_date:
            return []
        
        # 날짜 변환
        if isinstance(start_date, str):
            start_date = pd.to_datetime(start_date)
        if isinstance(end_date, str):
            end_date = pd.to_datetime(end_date)
        
        # 해당 구간 데이터 추출
        mask = (self.df.index >= start_date) & (self.df.index <= end_date)
        segment = self.df[mask]
        
        if len(segment) < 10:
            return []
        
        # 피벗 포인트 감지
        sub_waves = self._detect_pivots_in_segment(segment, parent_wave)
        
        # 가장 강한 서브파동 표시
        if sub_waves:
            self._mark_strongest_subwave(sub_waves, parent_wave)
        
        self.sub_waves[parent_wave] = sub_waves
        return sub_waves
    
    def _detect_pivots_in_segment(
        self, 
        segment: pd.DataFrame, 
        parent_wave: str
    ) -> List[SubWave]:
        """세그먼트 내 피벗 감지"""
        # 컬럼 정규화
        high_col = 'High' if 'High' in segment.columns else 'high'
        low_col = 'Low' if 'Low' in segment.columns else 'low'
        close_col = 'Close' if 'Close' in segment.columns else 'close'
        vol_col = 'Volume' if 'Volume' in segment.columns else 'volume'
        
        window = max(3, len(segment) // 10)
        
        pivots = []
        sub_labels = ['(1)', '(2)', '(3)', '(4)', '(5)']
        label_idx = 0
        
        # 상승파인지 하락파인지 확인
        is_upward = parent_wave in ['1', '3', '5']
        
        for i in range(window, len(segment) - window):
            date = segment.index[i]
            
            # High/Low 값 추출
            high_val = segment[high_col].iloc[i]
            low_val = segment[low_col].iloc[i]
            vol_val = segment[vol_col].iloc[i] if vol_col in segment.columns else 0
            
            # 스칼라로 변환
            if hasattr(high_val, 'item'):
                high_val = high_val.item()
            if hasattr(low_val, 'item'):
                low_val = low_val.item()
            if hasattr(vol_val, 'item'):
                vol_val = vol_val.item()
            
            # 로컬 최고점/최저점
            local_high = segment[high_col].iloc[i-window:i+window+1].max()
            local_low = segment[low_col].iloc[i-window:i+window+1].min()
            
            if hasattr(local_high, 'item'):
                local_high = local_high.item()
            if hasattr(local_low, 'item'):
                local_low = local_low.item()
            
            is_high = high_val >= local_high * 0.999
            is_low = low_val <= local_low * 1.001
            
            if label_idx >= len(sub_labels):
                break
            
            if is_upward:
                # 상승파: 홀수번 서브는 고점, 짝수번 서브는 저점
                if label_idx % 2 == 0 and is_high:
                    pivots.append(SubWave(
                        parent_wave=parent_wave,
                        sub_label=sub_labels[label_idx],
                        price=float(high_val),
                        date=date,
                        volume=float(vol_val)
                    ))
                    label_idx += 1
                elif label_idx % 2 == 1 and is_low:
                    pivots.append(SubWave(
                        parent_wave=parent_wave,
                        sub_label=sub_labels[label_idx],
                        price=float(low_val),
                        date=date,
                        volume=float(vol_val)
                    ))
                    label_idx += 1
        
        return pivots
    
    def _mark_strongest_subwave(self, sub_waves: List[SubWave], parent_wave: str):
        """가장 강한 서브파동 표시 (보통 Sub-wave 3)"""
        if len(sub_waves) < 3:
            return
        
        # 가격 변동폭 계산
        max_move = 0
        strongest_idx = 0
        
        for i in range(1, len(sub_waves)):
            move = abs(sub_waves[i].price - sub_waves[i-1].price)
            if move > max_move:
                max_move = move
                strongest_idx = i
        
        if strongest_idx < len(sub_waves):
            sub_waves[strongest_idx].is_strongest = True
    
    def validate_volume(self) -> Dict[str, VolumeProfile]:
        """거래량 검증 - Wave 3 > Wave 1, 5"""
        vol_col = 'Volume' if 'Volume' in self.df.columns else 'volume'
        
        if vol_col not in self.df.columns:
            return {}
        
        profiles = {}
        
        for label, wave in self.waves.items():
            if label not in ['1', '3', '5']:
                continue
            
            # 파동 구간 거래량
            prev_label = str(int(label) - 1)
            if prev_label not in self.waves:
                continue
            
            start_date = pd.to_datetime(self.waves[prev_label].get('date'))
            end_date = pd.to_datetime(wave.get('date'))
            
            mask = (self.df.index >= start_date) & (self.df.index <= end_date)
            segment_volume = self.df.loc[mask, vol_col]
            
            if len(segment_volume) == 0:
                continue
            
            avg_vol = float(segment_volume.mean())
            peak_vol = float(segment_volume.max())
            overall_avg = float(self.df[vol_col].mean())
            
            profiles[label] = VolumeProfile(
                wave_label=label,
                avg_volume=avg_vol,
                peak_volume=peak_vol,
                volume_ratio=avg_vol / overall_avg if overall_avg > 0 else 1.0
            )
        
        # Wave 3 검증
        if '3' in profiles and '1' in profiles:
            profiles['3'].is_valid = profiles['3'].avg_volume >= profiles['1'].avg_volume * 0.8
        
        if '3' in profiles and '5' in profiles:
            valid_vs_5 = profiles['3'].avg_volume >= profiles['5'].avg_volume * 0.7
            profiles['3'].is_valid = profiles['3'].is_valid and valid_vs_5
        
        self.volume_profiles = profiles
        return profiles
    
    def validate_time_ratios(self) -> List[TimeRatio]:
        """시간 비율 검증 - 피보나치 시간"""
        ratios = []
        
        # Wave 2/Wave 1 시간 비율
        if '0' in self.waves and '1' in self.waves and '2' in self.waves:
            w1_duration = self._get_duration('0', '1')
            w2_duration = self._get_duration('1', '2')
            
            if w1_duration > 0:
                ratio_value = w2_duration / w1_duration
                fib_match = self._match_fibonacci(ratio_value)
                
                ratios.append(TimeRatio(
                    wave_pair='W2/W1',
                    ratio=ratio_value,
                    fibonacci_match=fib_match,
                    is_valid=fib_match != 'none'
                ))
        
        # Wave 4/Wave 2 시간 비율
        if '2' in self.waves and '3' in self.waves and '4' in self.waves:
            w2_duration = self._get_duration('1', '2')
            w4_duration = self._get_duration('3', '4')
            
            if w2_duration > 0:
                ratio_value = w4_duration / w2_duration
                fib_match = self._match_fibonacci(ratio_value)
                
                ratios.append(TimeRatio(
                    wave_pair='W4/W2',
                    ratio=ratio_value,
                    fibonacci_match=fib_match,
                    is_valid=fib_match != 'none'
                ))
        
        self.time_ratios = ratios
        return ratios
    
    def _get_duration(self, start_label: str, end_label: str) -> float:
        """두 파동 사이의 기간 (일)"""
        if start_label not in self.waves or end_label not in self.waves:
            return 0
        
        start = pd.to_datetime(self.waves[start_label].get('date'))
        end = pd.to_datetime(self.waves[end_label].get('date'))
        
        return (end - start).days
    
    def _match_fibonacci(self, ratio: float) -> str:
        """피보나치 비율 매칭"""
        for fib in self.FIB_TIME_RATIOS:
            if abs(ratio - fib) <= fib * self.RATIO_TOLERANCE:
                return str(fib)
        return 'none'
    
    def find_entry_zones(self, sub_waves: List[SubWave]) -> List[Dict]:
        """진입 구간 식별"""
        zones = []
        
        for sw in sub_waves:
            if sw.is_strongest:  # Sub-wave 3 = 최적 진입
                zones.append({
                    'type': 'optimal_entry',
                    'wave': sw.sub_label,
                    'price': sw.price,
                    'date': sw.date.isoformat() if hasattr(sw.date, 'isoformat') else str(sw.date),
                    'description': f"Sub-wave {sw.sub_label} (가장 강한 움직임)"
                })
            elif sw.sub_label == '(2)':  # Sub-wave 2 = 눌림 진입
                zones.append({
                    'type': 'pullback_entry',
                    'wave': sw.sub_label,
                    'price': sw.price,
                    'date': sw.date.isoformat() if hasattr(sw.date, 'isoformat') else str(sw.date),
                    'description': f"Sub-wave {sw.sub_label} (눌림목 진입)"
                })
        
        return zones
    
    def _generate_warnings(self, results: Dict) -> List[str]:
        """경고 메시지 생성"""
        warnings = []
        
        # 거래량 경고
        vol = results.get('volume_validation', {})
        if '3' in vol and not vol['3'].is_valid:
            warnings.append("⚠️ Wave 3 거래량이 Wave 1/5보다 낮음 - 파동 구조 재검토 필요")
        
        # 시간 비율 경고
        for tr in results.get('time_validation', []):
            if not tr.is_valid:
                warnings.append(f"⚠️ {tr.wave_pair} 시간 비율 ({tr.ratio:.2f})이 피보나치 비율과 불일치")
        
        return warnings


# 테스트
def test_subwave_analyzer():
    """서브파동 분석 테스트"""
    import yfinance as yf
    
    print("=== 서브파동 분석 테스트 ===\n")
    
    # 데이터 로드
    df = yf.download('BTC-USD', period='2y', interval='1d', progress=False)
    
    # 컬럼 정규화
    if hasattr(df.columns, 'get_level_values'):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.title() for c in df.columns]
    
    # 테스트 파동 데이터
    waves = {
        '0': {'price': 15000, 'date': '2022-11-01'},
        '1': {'price': 31000, 'date': '2023-04-01'},
        '2': {'price': 25000, 'date': '2023-06-01'},
        '3': {'price': 73000, 'date': '2024-03-01'},
        '4': {'price': 56000, 'date': '2024-07-01'},
        '5': {'price': 109000, 'date': '2025-01-20'},
    }
    
    analyzer = SubWaveAnalyzer(df, waves)
    results = analyzer.analyze_all()
    
    print("📊 서브파동 분석 결과:")
    for label, subs in results['sub_waves'].items():
        print(f"\n  Wave {label} 내부:")
        for sw in subs:
            marker = "⭐" if sw.is_strongest else "  "
            print(f"    {marker} {sw.sub_label}: ${sw.price:,.0f}")
    
    print("\n📈 거래량 검증:")
    for label, vp in results['volume_validation'].items():
        status = "✅" if vp.is_valid else "❌"
        print(f"  Wave {label}: {status} (비율: {vp.volume_ratio:.2f})")
    
    print("\n⏱️ 시간 비율 검증:")
    for tr in results['time_validation']:
        status = "✅" if tr.is_valid else "❌"
        print(f"  {tr.wave_pair}: {status} (비율: {tr.ratio:.2f}, 피보: {tr.fibonacci_match})")
    
    print("\n🎯 진입 구간:")
    for ez in results['entry_zones']:
        print(f"  {ez['type']}: {ez['wave']} @ ${ez['price']:,.0f}")
    
    if results['warnings']:
        print("\n⚠️ 경고:")
        for w in results['warnings']:
            print(f"  {w}")
    
    return results


if __name__ == '__main__':
    test_subwave_analyzer()

"""
Elliott Wave Pattern RAG (Retrieval-Augmented Generation)
=========================================================

핵심 기능:
- 과거 Elliott Wave 패턴 저장/검색
- 현재 패턴과 유사한 과거 사례 찾기
- 성공률 기반 가중치 계산
- LLM 통합 분석

Based on: ElliottAgents RAG approach
"""

import json
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np


@dataclass
class WavePattern:
    """파동 패턴 구조"""
    id: str
    symbol: str
    start_date: str
    end_date: str
    waves: Dict[str, float]  # {'0': price, '1': price, ...}
    outcome: str  # 'abc_correction', 'extended_5th', 'new_supercycle'
    success: bool
    target_hit: float = 0.0  # 목표 달성률
    metadata: Dict = field(default_factory=dict)


class PatternDatabase:
    """패턴 데이터베이스"""
    
    def __init__(self, db_path: str = "data/patterns/elliott_patterns.json"):
        self.db_path = db_path
        self.patterns: List[WavePattern] = []
        self._ensure_dir()
        self._load()
    
    def _ensure_dir(self):
        """디렉토리 생성"""
        dir_path = os.path.dirname(self.db_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
    
    def _load(self):
        """패턴 로드"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.patterns = [WavePattern(**p) for p in data]
            except Exception:
                self.patterns = []
        else:
            # 기본 패턴 생성
            self._init_default_patterns()
    
    def _init_default_patterns(self):
        """기본 패턴 초기화 — 12종 패턴 유형별 다양한 자산/시기 커버"""
        default_patterns = [
            # ===== 1. Impulse (충격파) — 5파 완성 후 ABC 조정 =====
            {
                "id": "btc_2017_2018",
                "symbol": "BTC-USD",
                "start_date": "2015-01-01",
                "end_date": "2018-12-15",
                "waves": {"0": 200, "1": 1200, "2": 150, "3": 5000, "4": 1800, "5": 20000},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.85,
                "metadata": {
                    "pattern_type": "impulse",
                    "decline_depth": 0.84,
                    "correction_duration_days": 365,
                    "fib_ratios": {"w2_retrace": 0.875, "w3_to_w1": 3.8, "w4_retrace": 0.38, "w5_to_w1": 4.58},
                    "volume": "w3_highest_volume",
                    "market_condition": "early_crypto_bull",
                    "failure_mode": None,
                    "notes": "교과서적 5파 충격파. W3이 가장 길고 거래량 최대."
                }
            },
            {
                "id": "btc_2020_2021",
                "symbol": "BTC-USD",
                "start_date": "2018-12-15",
                "end_date": "2021-11-10",
                "waves": {"0": 3200, "1": 14000, "2": 3800, "3": 42000, "4": 29000, "5": 69000},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.78,
                "metadata": {
                    "pattern_type": "impulse",
                    "decline_depth": 0.77,
                    "correction_duration_days": 400,
                    "fib_ratios": {"w2_retrace": 0.944, "w3_to_w1": 3.537, "w4_retrace": 0.325, "w5_to_w1": 3.704},
                    "volume": "w3_highest_volume_w5_divergence",
                    "market_condition": "institutional_adoption",
                    "failure_mode": None,
                    "notes": "W5에서 거래량 다이버전스 (W3 대비 감소). 전형적 천장 신호."
                }
            },
            {
                "id": "btc_2023_2024",
                "symbol": "BTC-USD",
                "start_date": "2022-11-21",
                "end_date": "2024-03-14",
                "waves": {"0": 15500, "1": 31000, "2": 25000, "3": 73000, "4": 56000, "5": 109000},
                "outcome": "abc_correction",
                "success": False,
                "target_hit": 0.0,
                "metadata": {
                    "pattern_type": "impulse",
                    "decline_depth": 0.36,
                    "is_ongoing": True,
                    "fib_ratios": {"w2_retrace": 0.387, "w3_to_w1": 3.097, "w4_retrace": 0.354, "w5_to_w1": 3.419},
                    "volume": "etf_driven_w5",
                    "market_condition": "etf_approval_cycle",
                    "notes": "ETF 승인으로 W5 확장. 진행 중."
                }
            },
            {
                "id": "eth_2017_2018",
                "symbol": "ETH-USD",
                "start_date": "2017-01-01",
                "end_date": "2018-01-13",
                "waves": {"0": 8, "1": 400, "2": 130, "3": 750, "4": 500, "5": 1400},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.94,
                "metadata": {
                    "pattern_type": "impulse",
                    "decline_depth": 0.94,
                    "fib_ratios": {"w2_retrace": 0.689, "w3_to_w1": 1.581, "w4_retrace": 0.357, "w5_to_w1": 2.296},
                    "volume": "parabolic_w5",
                    "market_condition": "ico_bubble",
                    "failure_mode": None,
                    "notes": "ICO 버블로 W5 급등. 94% 하락 후 장기 조정."
                }
            },
            {
                "id": "spx_2007_2009",
                "symbol": "SPX",
                "start_date": "2007-10-01",
                "end_date": "2009-03-06",
                "waves": {"0": 700, "1": 1200, "2": 770, "3": 1400, "4": 1200, "5": 1565},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.57,
                "metadata": {
                    "pattern_type": "impulse",
                    "decline_depth": 0.57,
                    "asset_type": "index",
                    "fib_ratios": {"w2_retrace": 0.86, "w3_to_w1": 1.26, "w5_to_w1": 0.73},
                    "volume": "declining_in_w5",
                    "market_condition": "housing_bubble_peak",
                    "notes": "GFC 전 5파 완성. W5 절단(truncation) 가능성 있었음."
                }
            },
            # ===== 2. Extended 5th Wave (5파 확장) =====
            {
                "id": "gold_2001_2011",
                "symbol": "GOLD",
                "start_date": "2001-04-02",
                "end_date": "2011-09-06",
                "waves": {"0": 255, "1": 730, "2": 540, "3": 1033, "4": 680, "5": 1921},
                "outcome": "extended_5th",
                "success": True,
                "target_hit": 0.72,
                "metadata": {
                    "pattern_type": "impulse_extended_5th",
                    "decline_depth": 0.45,
                    "correction_duration_days": 1500,
                    "fib_ratios": {"w5_to_w1_w3": 2.62, "w5_extension": 1.618},
                    "volume": "w5_volume_surge_commodity",
                    "market_condition": "qe_era_safe_haven",
                    "notes": "W5가 W1-W3 합계의 1.618배 확장. 양적완화 시대 안전자산 수요."
                }
            },
            {
                "id": "tsla_2020_2021",
                "symbol": "TSLA",
                "start_date": "2020-03-18",
                "end_date": "2021-11-04",
                "waves": {"0": 72, "1": 502, "2": 330, "3": 900, "4": 563, "5": 1243},
                "outcome": "extended_5th",
                "success": True,
                "target_hit": 0.65,
                "metadata": {
                    "pattern_type": "impulse_extended_5th",
                    "decline_depth": 0.73,
                    "fib_ratios": {"w5_to_w1": 1.58, "w5_to_w3": 1.19},
                    "volume": "retail_fomo_w5",
                    "market_condition": "pandemic_stimulus_growth",
                    "failure_mode": None,
                    "notes": "팬데믹 유동성 + 개인투자자 FOMO로 W5 확장. 73% 하락."
                }
            },
            # ===== 3. Ending Diagonal (종결 대각선) =====
            {
                "id": "spx_2018_ending_diag",
                "symbol": "SPX",
                "start_date": "2016-02-11",
                "end_date": "2018-01-26",
                "waves": {"0": 1810, "1": 2400, "2": 2325, "3": 2490, "4": 2420, "5": 2872},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.52,
                "metadata": {
                    "pattern_type": "ending_diagonal",
                    "decline_depth": 0.20,
                    "correction_duration_days": 30,
                    "fib_ratios": {"overlap_w4_w1": True, "contracting": True},
                    "volume": "declining_each_wave",
                    "market_condition": "late_cycle_low_vol",
                    "failure_mode": None,
                    "notes": "종결 대각선 W5. 수렴형, 거래량 점감. 완성 후 2018 Q1 급락."
                }
            },
            # ===== 4. Leading Diagonal (선행 대각선) =====
            {
                "id": "btc_2019_leading_diag",
                "symbol": "BTC-USD",
                "start_date": "2018-12-15",
                "end_date": "2019-06-26",
                "waves": {"0": 3200, "1": 5400, "2": 3700, "3": 9000, "4": 7500, "5": 14000},
                "outcome": "new_supercycle",
                "success": True,
                "target_hit": 0.40,
                "metadata": {
                    "pattern_type": "leading_diagonal",
                    "decline_depth": 0.46,
                    "fib_ratios": {"overlap_w4_w1": False, "w3_to_w1": 2.41},
                    "volume": "increasing_w1_to_w3",
                    "market_condition": "bear_market_reversal",
                    "notes": "약세장 바닥에서 선행 대각선으로 새 추세 시작. W1 위치에 출현."
                }
            },
            # ===== 5. Zigzag (지그재그) =====
            {
                "id": "btc_2022_zigzag",
                "symbol": "BTC-USD",
                "start_date": "2021-11-10",
                "end_date": "2022-11-21",
                "waves": {"0": 69000, "1": 33000, "2": 48000, "3": 0, "4": 0, "5": 0},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.77,
                "metadata": {
                    "pattern_type": "zigzag",
                    "decline_depth": 0.77,
                    "correction_duration_days": 376,
                    "fib_ratios": {"b_retrace_of_a": 0.417, "c_extension_of_a": 1.36},
                    "volume": "capitulation_in_c",
                    "market_condition": "fed_tightening_luna_ftx",
                    "notes": "A파 급락 → B파 38.2% 되돌림 → C파 확장 (LUNA/FTX 촉발). 교과서적 지그재그."
                }
            },
            {
                "id": "spx_2020_covid_zigzag",
                "symbol": "SPX",
                "start_date": "2020-02-19",
                "end_date": "2020-03-23",
                "waves": {"0": 3393, "1": 2855, "2": 3136, "3": 0, "4": 0, "5": 0},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.95,
                "metadata": {
                    "pattern_type": "zigzag",
                    "decline_depth": 0.34,
                    "correction_duration_days": 33,
                    "fib_ratios": {"b_retrace_of_a": 0.522, "c_extension_of_a": 1.618},
                    "volume": "extreme_volume_c_wave",
                    "market_condition": "pandemic_shock",
                    "failure_mode": None,
                    "notes": "코로나 충격 — 초고속 지그재그. C파 1.618 확장. VIX 82."
                }
            },
            # ===== 6. Double Zigzag (이중 지그재그) =====
            {
                "id": "eth_2022_double_zigzag",
                "symbol": "ETH-USD",
                "start_date": "2021-11-10",
                "end_date": "2022-06-18",
                "waves": {"0": 4870, "1": 2160, "2": 3580, "3": 2100, "4": 3200, "5": 880},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.82,
                "metadata": {
                    "pattern_type": "double_zigzag",
                    "decline_depth": 0.82,
                    "correction_duration_days": 220,
                    "fib_ratios": {"x_retrace_of_w": 0.59, "y_similar_to_w": True},
                    "volume": "two_capitulation_events",
                    "market_condition": "terra_luna_contagion",
                    "notes": "WXY 이중 지그재그. X파 59% 되돌림. W와 Y 비슷한 크기."
                }
            },
            # ===== 7. Expanded Flat (확장형 플랫) =====
            {
                "id": "spx_2015_expanded_flat",
                "symbol": "SPX",
                "start_date": "2015-05-20",
                "end_date": "2016-02-11",
                "waves": {"0": 2135, "1": 1867, "2": 2135, "3": 0, "4": 0, "5": 0},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.45,
                "metadata": {
                    "pattern_type": "expanded_flat",
                    "decline_depth": 0.15,
                    "correction_duration_days": 266,
                    "fib_ratios": {"b_retrace_of_a": 1.00, "c_extension_of_a": 1.38},
                    "volume": "increasing_in_c",
                    "market_condition": "china_devaluation_oil_crash",
                    "notes": "B파가 A 시작점 100% 되돌림. C파 138% 확장. 중국 위안 절하 + 유가 급락."
                }
            },
            # ===== 8. Running Flat (러닝 플랫) =====
            {
                "id": "spx_2014_running_flat",
                "symbol": "SPX",
                "start_date": "2014-09-19",
                "end_date": "2014-10-15",
                "waves": {"0": 2019, "1": 1820, "2": 1965, "3": 0, "4": 0, "5": 0},
                "outcome": "new_supercycle",
                "success": True,
                "target_hit": 0.80,
                "metadata": {
                    "pattern_type": "running_flat",
                    "decline_depth": 0.10,
                    "correction_duration_days": 26,
                    "fib_ratios": {"b_retrace_of_a": 0.73, "c_less_than_a": True},
                    "volume": "low_volume_c",
                    "market_condition": "strong_uptrend_ebola_scare",
                    "notes": "러닝 플랫: C파가 A 끝점 미달. 강한 상승추세 지속 신호. 에볼라 공포 후 급반등."
                }
            },
            # ===== 9. Triangle (삼각형) =====
            {
                "id": "btc_2019_triangle",
                "symbol": "BTC-USD",
                "start_date": "2019-06-26",
                "end_date": "2020-03-12",
                "waves": {"0": 14000, "1": 6500, "2": 10500, "3": 6800, "4": 10100, "5": 3800},
                "outcome": "abc_correction",
                "success": False,
                "target_hit": 0.20,
                "metadata": {
                    "pattern_type": "triangle",
                    "decline_depth": 0.73,
                    "fib_ratios": {"contracting": True, "e_wave_smallest": True},
                    "volume": "declining_within_triangle",
                    "market_condition": "pre_halving_consolidation",
                    "failure_mode": "pandemic_broke_triangle",
                    "notes": "수렴형 삼각형이 코로나 충격으로 E파 하향 이탈. 삼각형 실패 사례."
                }
            },
            {
                "id": "gold_2013_triangle",
                "symbol": "GOLD",
                "start_date": "2013-06-28",
                "end_date": "2015-07-20",
                "waves": {"0": 1180, "1": 1430, "2": 1185, "3": 1390, "4": 1130, "5": 1080},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.50,
                "metadata": {
                    "pattern_type": "triangle",
                    "decline_depth": 0.15,
                    "correction_duration_days": 752,
                    "fib_ratios": {"contracting": True, "a_b_c_d_e_narrowing": True},
                    "volume": "steadily_declining",
                    "market_condition": "post_qe_taper_tantrum",
                    "notes": "수렴형 삼각형. 2년간 수렴 후 하향 돌파. 거래량 점감 패턴."
                }
            },
            # ===== 10. Complex Correction WXY (복합 조정) =====
            {
                "id": "spx_2000_2003_complex",
                "symbol": "SPX",
                "start_date": "2000-03-24",
                "end_date": "2003-03-12",
                "waves": {"0": 1553, "1": 1210, "2": 1530, "3": 775, "4": 0, "5": 0},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.50,
                "metadata": {
                    "pattern_type": "complex_wxy",
                    "decline_depth": 0.50,
                    "correction_duration_days": 1084,
                    "fib_ratios": {"x_retrace": 0.93, "y_exceeds_w": True},
                    "volume": "multiple_capitulations",
                    "market_condition": "dotcom_bust",
                    "notes": "WXY 복합 조정. W=지그재그, X=플랫, Y=지그재그. 닷컴 버블 붕괴."
                }
            },
            # ===== 11. Impulse Failure — Truncated 5th (5파 절단) =====
            {
                "id": "nikkei_1989_truncation",
                "symbol": "NI225",
                "start_date": "1982-10-01",
                "end_date": "1989-12-29",
                "waves": {"0": 6849, "1": 13000, "2": 9900, "3": 33000, "4": 21000, "5": 38957},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.80,
                "metadata": {
                    "pattern_type": "impulse",
                    "decline_depth": 0.82,
                    "correction_duration_days": 9000,
                    "fib_ratios": {"w3_to_w1": 3.75, "w5_to_w1": 2.92},
                    "volume": "w3_peak_volume",
                    "market_condition": "asset_bubble_peak",
                    "failure_mode": "extended_correction_34_years",
                    "notes": "5파 완성 후 34년 조정. 극단적 장기 ABC. 자산 버블의 극단 사례."
                }
            },
            # ===== 12. Triple Zigzag — 희귀 패턴 =====
            {
                "id": "djia_1966_1974_triple_zz",
                "symbol": "DJIA",
                "start_date": "1966-02-09",
                "end_date": "1974-12-06",
                "waves": {"0": 1000, "1": 740, "2": 990, "3": 630, "4": 850, "5": 570},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.43,
                "metadata": {
                    "pattern_type": "triple_zigzag",
                    "decline_depth": 0.43,
                    "correction_duration_days": 3222,
                    "fib_ratios": {"x1_retrace": 0.962, "x2_retrace": 0.687},
                    "volume": "episodic_spikes",
                    "market_condition": "stagflation_era",
                    "notes": "WXYXZ 삼중 지그재그. 8년에 걸친 깊은 조정. 스태그플레이션 시대."
                }
            }
        ]
        
        self.patterns = [WavePattern(**p) for p in default_patterns]
        self.save()
    
    def save(self):
        """패턴 저장"""
        with open(self.db_path, 'w') as f:
            data = [
                {
                    'id': p.id,
                    'symbol': p.symbol,
                    'start_date': p.start_date,
                    'end_date': p.end_date,
                    'waves': p.waves,
                    'outcome': p.outcome,
                    'success': p.success,
                    'target_hit': p.target_hit,
                    'metadata': p.metadata
                }
                for p in self.patterns
            ]
            json.dump(data, f, indent=2)
    
    def add_pattern(self, pattern: WavePattern):
        """패턴 추가"""
        self.patterns.append(pattern)
        self.save()
    
    def get_all(self) -> List[WavePattern]:
        """전체 패턴 반환"""
        return self.patterns
    
    def filter_by_symbol(self, symbol: str) -> List[WavePattern]:
        """심볼별 필터링"""
        return [p for p in self.patterns if p.symbol == symbol]
    
    def filter_by_outcome(self, outcome: str) -> List[WavePattern]:
        """결과별 필터링"""
        return [p for p in self.patterns if p.outcome == outcome]


class PatternVectorizer:
    """패턴 벡터화"""
    
    @staticmethod
    def vectorize(waves: Dict[str, float]) -> np.ndarray:
        """파동 패턴을 벡터로 변환"""
        if not waves:
            return np.zeros(10)
        
        # 가격 정규화 (0-5파 비율)
        prices = [
            waves.get('0', 0),
            waves.get('1', 0),
            waves.get('2', 0),
            waves.get('3', 0),
            waves.get('4', 0),
            waves.get('5', 0)
        ]
        
        if prices[0] == 0:
            prices[0] = 1  # 0 방지
        
        # 비율 계산
        ratios = [p / prices[0] for p in prices]
        
        # 파동 간 비율 추가
        w1_w0 = (prices[1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        w3_w1 = (prices[3] - prices[2]) / (prices[1] - prices[0]) if (prices[1] - prices[0]) > 0 else 0
        w5_w3 = (prices[5] - prices[4]) / (prices[3] - prices[2]) if (prices[3] - prices[2]) > 0 else 0
        
        # 되돌림 비율
        w2_retrace = (prices[1] - prices[2]) / (prices[1] - prices[0]) if (prices[1] - prices[0]) > 0 else 0
        
        vector = np.array(ratios + [w1_w0, w3_w1, w5_w3, w2_retrace])
        
        return vector
    
    @staticmethod
    def similarity(v1: np.ndarray, v2: np.ndarray) -> float:
        """코사인 유사도"""
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(np.dot(v1, v2) / (norm1 * norm2))


class ElliottWaveRAG:
    """
    Elliott Wave RAG 시스템
    
    과거 패턴 기반 검색 및 분석
    """
    
    def __init__(self, db_path: str = None):
        db_path = db_path or "data/patterns/elliott_patterns.json"
        self.db = PatternDatabase(db_path)
        self.vectorizer = PatternVectorizer()
    
    def search_similar(
        self, 
        current_waves: Dict[str, float],
        top_k: int = 5,
        min_similarity: float = 0.5
    ) -> List[Tuple[WavePattern, float]]:
        """유사 패턴 검색"""
        current_vec = self.vectorizer.vectorize(current_waves)
        
        results = []
        for pattern in self.db.get_all():
            pattern_vec = self.vectorizer.vectorize(pattern.waves)
            similarity = self.vectorizer.similarity(current_vec, pattern_vec)
            
            if similarity >= min_similarity:
                results.append((pattern, similarity))
        
        # 유사도 순 정렬
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    def predict_outcome(
        self, 
        current_waves: Dict[str, float],
        current_price: float
    ) -> Dict:
        """결과 예측"""
        similar = self.search_similar(current_waves)
        
        if not similar:
            return {
                'predicted_outcome': 'unknown',
                'confidence': 0.0,
                'reasoning': 'No similar patterns found'
            }
        
        # 결과별 가중 투표
        outcome_scores = {}
        total_weight = 0
        
        for pattern, similarity in similar:
            outcome = pattern.outcome
            weight = similarity * (1.5 if pattern.success else 0.5)
            
            if outcome not in outcome_scores:
                outcome_scores[outcome] = 0
            outcome_scores[outcome] += weight
            total_weight += weight
        
        # 정규화
        for k in outcome_scores:
            outcome_scores[k] /= total_weight if total_weight > 0 else 1
        
        # 최고 점수 결과
        best_outcome = max(outcome_scores.items(), key=lambda x: x[1])
        
        # 상세 정보
        details = []
        for pattern, similarity in similar:
            details.append({
                'pattern_id': pattern.id,
                'symbol': pattern.symbol,
                'period': f"{pattern.start_date} ~ {pattern.end_date}",
                'outcome': pattern.outcome,
                'success': pattern.success,
                'similarity': similarity,
                'decline_depth': pattern.metadata.get('decline_depth', 0)
            })
        
        return {
            'predicted_outcome': best_outcome[0],
            'confidence': best_outcome[1],
            'all_scores': outcome_scores,
            'similar_patterns': details,
            'reasoning': self._generate_reasoning(details, current_price, current_waves)
        }
    
    def _generate_reasoning(
        self, 
        similar: List[Dict],
        current_price: float,
        current_waves: Dict
    ) -> str:
        """추론 생성"""
        if not similar:
            return "유사한 과거 패턴을 찾지 못했습니다."
        
        top = similar[0]
        w5_price = current_waves.get('5', current_price)
        decline = 1 - (current_price / w5_price) if w5_price > 0 else 0
        
        lines = [
            f"가장 유사한 패턴: {top['pattern_id']} ({top['similarity']:.1%} 일치)",
            f"해당 패턴 결과: {top['outcome']} (성공: {top['success']})",
            f"당시 하락폭: {top['decline_depth']:.1%}",
            f"현재 하락폭: {decline:.1%}",
        ]
        
        if decline > 0.35 and top['outcome'] == 'abc_correction':
            lines.append("→ 과거 패턴 대비 조정이 깊은 편이며, ABC 완료 가능성 높음")
        
        return " | ".join(lines)
    
    def add_current_pattern(
        self,
        symbol: str,
        waves: Dict[str, float],
        start_date: str,
        end_date: str = None,
        outcome: str = "ongoing",
        metadata: Dict = None
    ):
        """현재 패턴 저장"""
        pattern = WavePattern(
            id=f"{symbol}_{start_date.replace('-', '')}",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date or datetime.now().strftime('%Y-%m-%d'),
            waves=waves,
            outcome=outcome,
            success=False,
            metadata=metadata or {}
        )
        self.db.add_pattern(pattern)
    
    def get_statistics(self) -> Dict:
        """통계 정보"""
        patterns = self.db.get_all()
        
        outcome_counts = {}
        success_counts = {}
        
        for p in patterns:
            outcome_counts[p.outcome] = outcome_counts.get(p.outcome, 0) + 1
            if p.success:
                success_counts[p.outcome] = success_counts.get(p.outcome, 0) + 1
        
        success_rates = {}
        for outcome, count in outcome_counts.items():
            success_rates[outcome] = success_counts.get(outcome, 0) / count if count > 0 else 0
        
        return {
            'total_patterns': len(patterns),
            'outcome_distribution': outcome_counts,
            'success_rates': success_rates
        }


# 테스트
def test_pattern_rag():
    """패턴 RAG 테스트"""
    print("=== Elliott Wave Pattern RAG 테스트 ===\n")
    
    rag = ElliottWaveRAG()
    
    # 현재 BTC 패턴
    current_waves = {
        '0': 15500,
        '1': 31000,
        '2': 25000,
        '3': 73000,
        '4': 56000,
        '5': 109000
    }
    current_price = 69000
    
    # 통계
    stats = rag.get_statistics()
    print(f"📊 패턴 DB 통계:")
    print(f"   총 패턴: {stats['total_patterns']}")
    print(f"   결과 분포: {stats['outcome_distribution']}")
    print(f"   성공률: {stats['success_rates']}\n")
    
    # 유사 패턴 검색
    print("🔍 유사 패턴 검색:")
    similar = rag.search_similar(current_waves, top_k=3)
    for pattern, sim in similar:
        print(f"   {pattern.id}: {sim:.1%} 일치 → {pattern.outcome}")
    
    # 결과 예측
    print("\n📈 결과 예측:")
    prediction = rag.predict_outcome(current_waves, current_price)
    print(f"   예측 결과: {prediction['predicted_outcome']}")
    print(f"   신뢰도: {prediction['confidence']:.1%}")
    print(f"   추론: {prediction['reasoning']}")
    
    return rag


if __name__ == '__main__':
    test_pattern_rag()

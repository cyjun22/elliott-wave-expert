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
        """기본 BTC 패턴 초기화"""
        default_patterns = [
            {
                "id": "btc_2017_2018",
                "symbol": "BTC-USD",
                "start_date": "2015-01-01",
                "end_date": "2018-12-15",
                "waves": {"0": 200, "1": 1200, "2": 150, "3": 5000, "4": 1800, "5": 20000},
                "outcome": "abc_correction",
                "success": True,
                "target_hit": 0.85,
                "metadata": {"decline_depth": 0.84, "correction_duration_days": 365}
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
                "metadata": {"decline_depth": 0.77, "correction_duration_days": 400}
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
                "metadata": {"decline_depth": 0.36, "is_ongoing": True}
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
                "metadata": {"decline_depth": 0.94}
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
                "metadata": {"decline_depth": 0.57, "asset_type": "index"}
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

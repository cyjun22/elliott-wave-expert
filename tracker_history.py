"""
Wave Tracker History - 영속 저장 및 NN 트레이닝 준비
=====================================================
- 모든 확률 업데이트 기록
- 시나리오 결과 라벨링
- 피처 추출 (향후 NN 학습용)
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import pandas as pd

from experts.elliott.live_tracker import WaveScenarioLive, MarketState


class WaveTrackerHistory:
    """
    추적 기록 영속 저장
    
    - SQLite에 모든 업데이트 저장
    - NN 트레이닝용 피처 추출
    - 시나리오 결과 라벨링
    """
    
    def __init__(self, db_path: str = "data/wave_tracker_history.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """데이터베이스 초기화"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS probability_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    scenario_name TEXT,
                    old_probability REAL,
                    new_probability REAL,
                    current_price REAL,
                    events TEXT,  -- JSON array
                    is_valid INTEGER,
                    invalidation_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scenario_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    scenario_name TEXT,
                    start_price REAL,
                    start_time TEXT,
                    end_price REAL,
                    end_time TEXT,
                    predicted_target REAL,
                    actual_outcome TEXT,  -- 'hit_target', 'invalidated', 'ongoing'
                    profit_loss REAL,
                    accuracy_score REAL,  -- 예측 정확도
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS training_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    -- 시장 상태 피처
                    price REAL,
                    rsi_14 REAL,
                    macd_histogram REAL,
                    volume_ratio REAL,  -- 평균 대비
                    atr_14 REAL,
                    -- 파동 상태 피처
                    wave_position TEXT,
                    wave_progress REAL,  -- 0~1 (파동 내 진행도)
                    fib_distance REAL,   -- 가장 가까운 fib 레벨까지 거리
                    -- 시나리오 피처
                    num_valid_scenarios INTEGER,
                    primary_scenario TEXT,
                    primary_probability REAL,
                    bearish_probability REAL,
                    bullish_probability REAL,
                    -- 라벨 (나중에 업데이트)
                    next_1h_direction INTEGER,  -- 1: up, -1: down, 0: flat
                    next_4h_direction INTEGER,
                    next_1d_direction INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 인덱스
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prob_symbol ON probability_updates(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prob_time ON probability_updates(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_features_symbol ON training_features(symbol)")
    
    def log_probability_update(
        self,
        symbol: str,
        scenario: WaveScenarioLive,
        old_prob: float,
        new_prob: float,
        current_price: float,
        events: List[str] = None
    ):
        """확률 업데이트 기록"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO probability_updates 
                (timestamp, symbol, scenario_id, scenario_name, old_probability, 
                 new_probability, current_price, events, is_valid, invalidation_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                symbol,
                scenario.id,
                scenario.name,
                old_prob,
                new_prob,
                current_price,
                json.dumps(events or []),
                1 if scenario.is_valid else 0,
                scenario.invalidation_reason if not scenario.is_valid else None
            ))
    
    def log_scenario_outcome(
        self,
        symbol: str,
        scenario: WaveScenarioLive,
        end_price: float,
        outcome: str  # 'hit_target', 'invalidated', 'ongoing'
    ):
        """시나리오 결과 기록"""
        start_price = scenario.waves[0]['price'] if scenario.waves else 0
        predicted_target = scenario.targets[0].price if scenario.targets else 0
        
        profit_loss = (end_price - start_price) / start_price if start_price > 0 else 0
        
        # 정확도: 예측 방향과 실제 방향 일치도
        accuracy = 1.0 if outcome == 'hit_target' else 0.0
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO scenario_outcomes
                (symbol, scenario_id, scenario_name, start_price, start_time,
                 end_price, end_time, predicted_target, actual_outcome, 
                 profit_loss, accuracy_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                scenario.id,
                scenario.name,
                start_price,
                scenario.created_at,
                end_price,
                datetime.now().isoformat(),
                predicted_target,
                outcome,
                profit_loss,
                accuracy
            ))
    
    def log_training_features(
        self,
        symbol: str,
        market_state: MarketState,
        scenarios: List[WaveScenarioLive],
        primary: WaveScenarioLive = None
    ):
        """NN 트레이닝용 피처 저장"""
        valid_scenarios = [s for s in scenarios if s.is_valid]
        
        bullish_prob = sum(s.probability for s in valid_scenarios 
                         if s.wave_type.value == 'impulse')
        bearish_prob = 1 - bullish_prob
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO training_features
                (timestamp, symbol, price, rsi_14, macd_histogram, volume_ratio, atr_14,
                 wave_position, wave_progress, fib_distance, num_valid_scenarios,
                 primary_scenario, primary_probability, bearish_probability, bullish_probability)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                symbol,
                market_state.current_price,
                market_state.rsi,
                None,  # MACD 필요시 추가
                None,  # Volume ratio
                None,  # ATR
                primary.current_position.value if primary else None,
                None,  # wave_progress
                None,  # fib_distance
                len(valid_scenarios),
                primary.name if primary else None,
                primary.probability if primary else 0,
                bearish_prob,
                bullish_prob
            ))
    
    def update_labels(self, symbol: str, lookback_hours: int = 24):
        """
        과거 피처에 라벨 업데이트 (실제 가격 움직임 기반)
        
        주기적으로 호출하여 ground truth 라벨 추가
        """
        # 구현 예정: 과거 레코드의 next_1h_direction 등 업데이트
        pass
    
    def get_training_data(self, symbol: str = None) -> pd.DataFrame:
        """NN 트레이닝용 데이터 추출"""
        query = "SELECT * FROM training_features"
        params = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)

        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(query, conn, params=params)
    
    def get_probability_history(
        self,
        symbol: str,
        scenario_id: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """확률 변화 히스토리"""
        query = """
            SELECT * FROM probability_updates 
            WHERE symbol = ?
        """
        params = [symbol]
        
        if scenario_id:
            query += " AND scenario_id = ?"
            params.append(scenario_id)
        
        query += f" ORDER BY timestamp DESC LIMIT {limit}"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_scenario_accuracy(self, symbol: str = None) -> Dict:
        """시나리오 정확도 통계"""
        query = """
            SELECT
                scenario_name,
                COUNT(*) as total,
                SUM(CASE WHEN actual_outcome = 'hit_target' THEN 1 ELSE 0 END) as hits,
                AVG(accuracy_score) as avg_accuracy,
                AVG(profit_loss) as avg_pnl
            FROM scenario_outcomes
        """
        params = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " GROUP BY scenario_name"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return {row['scenario_name']: dict(row) for row in cursor.fetchall()}

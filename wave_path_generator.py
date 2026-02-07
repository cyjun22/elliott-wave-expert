"""
Wave Path Generator - Elliott Wave 기반 미래 경로 생성 (v2: Context-Aware)
=========================================================================
ScenarioGenerator의 WaveInterpretation을 입력받아
피보나치 비율 기반의 세밀한 경로를 생성 + Azure GPT-4o 검증

사용법:
    generator = WavePathGenerator(current_price=70400, atr=3000)
    paths = generator.generate_all_scenarios(df)  # 피벗 기반 동적 시나리오
    validated = generator.validate_with_llm(paths)
"""

import os
import sys
import re
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Azure OpenAI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass

try:
    from knowledge_core.azure_openai_client import AzureOpenAIClient
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

try:
    from experts.elliott.wave_tracker import ScenarioGenerator, WaveInterpretation
    SCENARIO_GEN_AVAILABLE = True
except ImportError:
    SCENARIO_GEN_AVAILABLE = False


# ===== 데이터 구조 =====

@dataclass
class WavePoint:
    """파동의 한 점"""
    label: str          # "W1", "W2", "W3", "W4", "W5", "A", "B", "C"
    price: float
    day: int            # 시작일 기준 경과일
    pct_from_start: float = 0.0  # 시작가 대비 변화율

@dataclass
class WavePath:
    """시나리오의 전체 경로"""
    scenario_name: str
    scenario_type: str     # "impulse_up", "impulse_down", "abc_correction", etc.
    view: str              # "BULL" or "BEAR"
    probability: float
    wave_points: List[WavePoint]
    daily_prices: List[float]   # 날짜별 가격 배열
    color: str
    current_wave: str = ""       # 현재 파동 위치 (from WaveInterpretation)
    description: str = ""        # 시나리오 설명
    invalidation_price: float = 0.0  # 무효화 가격
    llm_validated: bool = False
    llm_confidence: float = 0.0
    llm_reasoning: str = ""


# ===== 피보나치 상수 =====

FIB = {
    0.236: 0.236,
    0.382: 0.382,
    0.500: 0.500,
    0.618: 0.618,
    0.786: 0.786,
    1.000: 1.000,
    1.272: 1.272,
    1.618: 1.618,
    2.618: 2.618,
}


class WavePathGenerator:
    """
    Elliott Wave 규칙 기반 미래 가격 경로 생성기
    
    핵심 원리:
    - Impulse Wave: 5파 구조, 피보나치 확장/되돌림 비율
    - Corrective Wave: ABC 구조, 피보나치 되돌림 비율
    - 시간 비율: 각 파동의 기간도 피보나치 비율 배분
    """
    
    def __init__(self, current_price: float, atr: float = None, 
                 total_days: int = 30, seed: int = None):
        self.current_price = current_price
        self.atr = atr or current_price * 0.03  # 기본 ATR = 3%
        self.total_days = total_days
        
        if seed is not None:
            np.random.seed(seed)
    
    # ===== Impulse Wave (5파) 생성 =====
    
    def generate_impulse_path(
        self,
        start_price: float,
        target_price: float,
        direction: str = "up",  # "up" or "down"
        days: int = None
    ) -> Tuple[List[WavePoint], List[float]]:
        """
        5파 Impulse 구조 생성
        
        규칙:
        - Wave 2는 Wave 1의 시작점 아래로 안 감
        - Wave 3은 1, 3, 5 중 가장 짧지 않음 (보통 가장 김)
        - Wave 4는 Wave 1의 영역에 진입하지 않음
        - 피보나치 비율 적용
        """
        days = days or self.total_days
        total_move = target_price - start_price
        sign = 1 if direction == "up" else -1
        abs_move = abs(total_move)
        
        # 파동별 비율 (Wave 3이 가장 큼)
        w1_ratio = np.random.uniform(0.20, 0.28)   # Wave 1: 전체의 20-28%
        w2_retrace = np.random.uniform(0.382, 0.618)  # Wave 2: W1의 38.2-61.8% 되돌림
        w3_ext = np.random.uniform(1.272, 1.618)       # Wave 3: W1의 127.2-161.8% 확장
        w4_retrace = np.random.uniform(0.236, 0.382)  # Wave 4: W3의 23.6-38.2% 되돌림
        # Wave 5: 나머지
        
        # 가격 포인트 계산
        w1_move = abs_move * w1_ratio
        w1_end = start_price + sign * w1_move
        
        w2_end = w1_end - sign * (w1_move * w2_retrace)
        # Wave 2는 Wave 1 시작점을 넘지 않음
        if direction == "up":
            w2_end = max(w2_end, start_price + abs_move * 0.02)
        else:
            w2_end = min(w2_end, start_price - abs_move * 0.02)
        
        w3_move = w1_move * w3_ext
        w3_end = w2_end + sign * w3_move
        
        w4_end = w3_end - sign * (w3_move * w4_retrace)
        # Wave 4는 Wave 1 영역에 진입하지 않음
        if direction == "up":
            w4_end = max(w4_end, w1_end * 1.005)
        else:
            w4_end = min(w4_end, w1_end * 0.995)
        
        w5_end = target_price  # 최종 목표
        
        # 시간 배분 (피보나치 비율)
        time_ratios = [0.18, 0.10, 0.32, 0.12, 0.28]  # W1, W2, W3, W4, W5
        time_days = [max(2, int(r * days)) for r in time_ratios]
        # 총 일수 조정
        diff = days - sum(time_days)
        time_days[2] += diff  # Wave 3에 잔여일 추가
        
        # WavePoint 리스트
        wave_prices = [start_price, w1_end, w2_end, w3_end, w4_end, w5_end]
        wave_labels = ["Start", "W1", "W2", "W3", "W4", "W5"]
        
        cumulative_days = [0]
        for td in time_days:
            cumulative_days.append(cumulative_days[-1] + td)
        
        wave_points = []
        for i, (label, price, day) in enumerate(zip(wave_labels, wave_prices, cumulative_days)):
            pct = (price - start_price) / start_price * 100
            wave_points.append(WavePoint(label=label, price=round(price, 2), 
                                         day=day, pct_from_start=round(pct, 2)))
        
        # 일별 가격 생성 (부드러운 곡선)
        daily = self._interpolate_wave_path(wave_prices, time_days)
        
        return wave_points, daily
    
    # ===== Corrective Wave (ABC) 생성 =====
    
    def generate_corrective_path(
        self,
        start_price: float,
        target_price: float,
        correction_type: str = "zigzag",  # "zigzag", "flat", "expanded_flat"
        days: int = None
    ) -> Tuple[List[WavePoint], List[float]]:
        """
        ABC 조정파 구조 생성
        
        Zigzag: A-B-C, B파가 A파의 38.2-61.8% 되돌림
        Flat: A-B-C, B파가 A파의 78.6-100% 되돌림
        Expanded Flat: B파가 A파 시작점 넘어감
        """
        days = days or self.total_days
        total_move = target_price - start_price
        sign = 1 if total_move > 0 else -1
        abs_move = abs(total_move)
        
        if correction_type == "zigzag":
            a_ratio = np.random.uniform(0.55, 0.65)
            b_retrace = np.random.uniform(0.382, 0.618)
            # C파 = 나머지
        elif correction_type == "flat":
            a_ratio = np.random.uniform(0.35, 0.45)
            b_retrace = np.random.uniform(0.786, 1.00)
        elif correction_type == "expanded_flat":
            a_ratio = np.random.uniform(0.30, 0.40)
            b_retrace = np.random.uniform(1.00, 1.236)  # B가 시작점 넘어감
        else:
            a_ratio = 0.5
            b_retrace = 0.5
        
        # 가격 포인트
        a_end = start_price + sign * abs_move * a_ratio
        b_end = a_end - sign * abs(a_end - start_price) * b_retrace
        c_end = target_price
        
        # 시간 배분
        time_ratios = [0.35, 0.25, 0.40]  # A, B, C
        time_days = [max(2, int(r * days)) for r in time_ratios]
        diff = days - sum(time_days)
        time_days[2] += diff
        
        wave_prices = [start_price, a_end, b_end, c_end]
        wave_labels = ["Start", "A", "B", "C"]
        
        cumulative_days = [0]
        for td in time_days:
            cumulative_days.append(cumulative_days[-1] + td)
        
        wave_points = []
        for label, price, day in zip(wave_labels, wave_prices, cumulative_days):
            pct = (price - start_price) / start_price * 100
            wave_points.append(WavePoint(label=label, price=round(price, 2),
                                         day=day, pct_from_start=round(pct, 2)))
        
        daily = self._interpolate_wave_path(wave_prices, time_days)
        
        return wave_points, daily
    
    # ===== 복합 경로 생성 =====
    
    def generate_scenario_path(
        self,
        scenario_type: str,
        target_price: float,
        **kwargs
    ) -> Tuple[List[WavePoint], List[float]]:
        """
        시나리오 타입에 따라 적절한 경로 생성
        
        scenario_type:
        - "new_impulse_up": ABC 완료 후 새 상승 Impulse
        - "dead_cat_bounce": 반등 후 하락 (B파 반등 → C파 하락)
        - "flat_b_wave": Flat의 B파 반등
        - "breakdown": 구조적 하락 Impulse
        """
        start = self.current_price
        
        if scenario_type == "new_impulse_up":
            return self.generate_impulse_path(start, target_price, "up", **kwargs)
            
        elif scenario_type == "dead_cat_bounce":
            # B파 반등 → C파 하락 = ABC 하락
            return self.generate_corrective_path(
                start, target_price, "zigzag", **kwargs)
            
        elif scenario_type == "flat_b_wave":
            return self.generate_corrective_path(
                start, target_price, "flat", **kwargs)
            
        elif scenario_type == "expanded_flat":
            return self.generate_corrective_path(
                start, target_price, "expanded_flat", **kwargs)
            
        elif scenario_type == "breakdown":
            return self.generate_impulse_path(start, target_price, "down", **kwargs)
            
        else:
            # Fallback: 방향에 따라 impulse
            direction = "up" if target_price > start else "down"
            return self.generate_impulse_path(start, target_price, direction, **kwargs)
    
    # ===== WaveInterpretation → WavePath 변환 =====
    
    SCENARIO_COLORS = {
        'zigzag_abc': '#ff4444',
        'running_flat': '#00ff88',
        'expanded_flat': '#ffaa00',
        'extended_5th': '#00ccff',
    }
    
    SCENARIO_LETTERS = {
        'zigzag_abc': 'A',
        'running_flat': 'B',
        'expanded_flat': 'C',
        'extended_5th': 'D',
    }
    
    def generate_from_interpretation(
        self,
        interp: 'WaveInterpretation'
    ) -> WavePath:
        """
        WaveInterpretation의 시나리오 정보를 기반으로
        피보나치 경로를 세밀하게 생성
        
        시나리오 ID → 경로 생성 방식 자동 선택:
        - zigzag_abc → ABC 조정 (zigzag)
        - running_flat → Impulse up (W4→W5)
        - expanded_flat → ABC 조정 (expanded_flat)
        - extended_5th → Impulse up (W5 확장)
        """
        cp = self.current_price
        sid = interp.scenario_id
        
        # 타겟 가격 결정 (projected_path의 마지막 점)
        if interp.projected_path:
            last_point = interp.projected_path[-1]
            target_price = last_point.get('price', cp)
        elif interp.targets:
            target_price = interp.targets[0].get('price', cp)
        else:
            target_price = cp * 1.10  # fallback
        
        # 방향 결정
        view = 'BULL' if target_price > cp else 'BEAR'
        
        # 시나리오 타입에 따라 경로 생성
        if sid == 'zigzag_abc':
            wave_points, daily = self.generate_corrective_path(
                cp, target_price, 'zigzag'
            )
        elif sid == 'running_flat':
            # W4→W5 = 상승 Impulse
            wave_points, daily = self.generate_impulse_path(
                cp, target_price, 'up'
            )
        elif sid == 'expanded_flat':
            wave_points, daily = self.generate_corrective_path(
                cp, target_price, 'expanded_flat'
            )
        elif sid == 'extended_5th':
            # W5 서브파동 확장 = 상승 Impulse
            wave_points, daily = self.generate_impulse_path(
                cp, target_price, 'up'
            )
        else:
            # 방향에 따라 자동 선택
            direction = 'up' if target_price > cp else 'down'
            wave_points, daily = self.generate_impulse_path(
                cp, target_price, direction
            )
        
        letter = self.SCENARIO_LETTERS.get(sid, '?')
        color = self.SCENARIO_COLORS.get(sid, '#ffffff')
        
        return WavePath(
            scenario_name=f"{letter}: {interp.scenario_name}",
            scenario_type=sid,
            view=view,
            probability=interp.probability,
            wave_points=wave_points,
            daily_prices=daily,
            color=color,
            current_wave=interp.current_wave,
            description=interp.description,
            invalidation_price=interp.invalidation_price
        )
    
    # ===== 전체 시나리오 경로 생성 (동적) =====
    
    def generate_all_scenarios(
        self,
        df: pd.DataFrame = None,
        recent_low: float = None,
        recent_high: float = None
    ) -> List[WavePath]:
        """
        ScenarioGenerator를 통해 동적 시나리오 생성
        
        Args:
            df: OHLCV 데이터 (피벗 추출용)
            recent_low/high: df 없을 때 fallback
        """
        if df is not None and SCENARIO_GEN_AVAILABLE:
            return self._generate_dynamic_scenarios(df)
        else:
            return self._generate_fallback_scenarios(recent_low, recent_high)
    
    def _generate_dynamic_scenarios(self, df: pd.DataFrame) -> List[WavePath]:
        """
        ScenarioGenerator.generate_interpretations()의 결과를 기반으로
        동적 시나리오 경로 생성
        """
        # 피벗 추출
        pivots = self._extract_pivots_simple(df)
        
        if len(pivots) < 6:
            print(f"⚠️ 피벗 부족 ({len(pivots)}개) → fallback 시나리오 사용")
            rl = float(df['Low'].tail(5).min()) if 'Low' in df.columns else self.current_price * 0.9
            rh = float(df['High'].tail(30).max()) if 'High' in df.columns else self.current_price * 1.3
            return self._generate_fallback_scenarios(rl, rh)
        
        # ScenarioGenerator로 동적 시나리오 해석
        sg = ScenarioGenerator()
        interpretations = sg.generate_interpretations(
            pivots, self.current_price, datetime.now()
        )
        
        print(f"\n📊 ScenarioGenerator → {len(interpretations)}개 시나리오 (동적 확률):")
        for interp in interpretations:
            print(f"  • {interp.scenario_name}: {interp.probability:.1%} "
                  f"(현재 {interp.current_wave}) → {interp.description[:50]}")
        
        # WaveInterpretation → WavePath 변환
        paths = []
        for interp in interpretations:
            path = self.generate_from_interpretation(interp)
            paths.append(path)
        
        return paths
    
    def _generate_fallback_scenarios(
        self,
        recent_low: float = None,
        recent_high: float = None
    ) -> List[WavePath]:
        """
        ScenarioGenerator 없을 때 기본 시나리오 (하위 호환)
        """
        cp = self.current_price
        rl = recent_low or cp * 0.85
        rh = recent_high or cp * 1.30
        
        scenarios = [
            {'name': 'A: Zigzag ABC', 'type': 'dead_cat_bounce',
             'target': rl * 0.90, 'view': 'BEAR', 'prob': 0.45, 'color': '#ff4444'},
            {'name': 'B: Running Flat', 'type': 'new_impulse_up',
             'target': rh * 1.10, 'view': 'BULL', 'prob': 0.25, 'color': '#00ff88'},
            {'name': 'C: Expanded Flat', 'type': 'expanded_flat',
             'target': rl * 0.80, 'view': 'BEAR', 'prob': 0.15, 'color': '#ffaa00'},
            {'name': 'D: Extended 5th', 'type': 'new_impulse_up',
             'target': rh * 1.20, 'view': 'BULL', 'prob': 0.15, 'color': '#00ccff'},
        ]
        
        paths = []
        for sc in scenarios:
            wave_points, daily = self.generate_scenario_path(
                sc['type'], sc['target']
            )
            paths.append(WavePath(
                scenario_name=sc['name'],
                scenario_type=sc['type'],
                view=sc['view'],
                probability=sc['prob'],
                wave_points=wave_points,
                daily_prices=daily,
                color=sc['color']
            ))
        return paths
    
    def _extract_pivots_simple(self, df: pd.DataFrame, window: int = 20) -> List[Dict]:
        """
        간단한 피벗 추출 (DualAgentExpert 없이 독립 사용)
        """
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df_work = df.copy()
            df_work.columns = [c[0] for c in df_work.columns]
        else:
            df_work = df.copy()
        
        # 대소문자 통일
        col_map = {c: c.lower() for c in df_work.columns}
        df_work = df_work.rename(columns=col_map)
        
        pivots = []
        
        # 로컬 고점
        rolling_max = df_work['high'].rolling(window=window, center=True).max()
        local_highs = df_work[df_work['high'] == rolling_max].dropna()
        for idx, row in local_highs.iterrows():
            pivots.append({
                'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                'price': float(row['high']),
                'type': 'high'
            })
        
        # 로컬 저점
        rolling_min = df_work['low'].rolling(window=window, center=True).min()
        local_lows = df_work[df_work['low'] == rolling_min].dropna()
        for idx, row in local_lows.iterrows():
            pivots.append({
                'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                'price': float(row['low']),
                'type': 'low'
            })
        
        # 중복 제거 + 정렬
        seen = set()
        unique = []
        for p in pivots:
            key = (p['date'], p['type'])
            if key not in seen:
                seen.add(key)
                unique.append(p)
        
        unique.sort(key=lambda x: x['date'])
        return unique
    
    # ===== Azure GPT-4o LLM 검증 =====
    
    def validate_with_llm(self, paths: List[WavePath]) -> List[WavePath]:
        """
        Azure GPT-4o로 생성된 파동 구조를 검증하고 수정
        """
        if not LLM_AVAILABLE:
            print("⚠️ LLM not available, skipping validation")
            return paths
        
        client = AzureOpenAIClient()
        if not client.available:
            print("⚠️ Azure OpenAI not available, skipping validation")
            return paths
        
        validated_paths = []
        
        for path in paths:
            print(f"\n🤖 Validating: {path.scenario_name}...")
            
            # 프롬프트 생성
            wave_desc = "\n".join([
                f"  {wp.label}: ${wp.price:,.0f} (Day {wp.day}, {wp.pct_from_start:+.1f}%)"
                for wp in path.wave_points
            ])
            
            # 현재 파동 위치 컨텍스트
            context_str = ""
            if path.current_wave:
                context_str = f"\nCurrent Wave Position: {path.current_wave}"
            if path.description:
                context_str += f"\nScenario Context: {path.description}"
            if path.invalidation_price > 0:
                context_str += f"\nInvalidation Price: ${path.invalidation_price:,.0f}"
            
            prompt = f"""You are an Elliott Wave expert. Validate the following projected wave structure.

BTC Current Price: ${self.current_price:,.0f}
Scenario: {path.scenario_name} ({path.scenario_type})
Direction: {path.view}{context_str}

Projected Wave Structure:
{wave_desc}

Elliott Wave Rules to Check:
1. Impulse (5-wave): Wave 2 never retraces beyond Wave 1 start; Wave 3 is NOT the shortest among 1,3,5; Wave 4 does not enter Wave 1 territory
2. Corrective (ABC): B-wave typically retraces 38.2-78.6% of A-wave; C-wave often equals A-wave in length
3. Fibonacci relationships between waves should be reasonable
4. Time proportions should be realistic

Respond ONLY in valid JSON (no markdown, no trailing commas, no ellipsis).
Return ALL corrected waves as complete array entries.

Example response:
{{
  "valid": true,
  "issues": [],
  "corrected_waves": [
    {{"label": "W1", "price": 78500, "day": 10, "pct_from_start": 11.5}},
    {{"label": "W2", "price": 72000, "day": 15, "pct_from_start": 2.3}}
  ],
  "confidence": 0.85,
  "reasoning": "Brief explanation"
}}"""

            try:
                # response_format으로 JSON 강제
                resp = client.client.chat.completions.create(
                    model=client.deployment,
                    messages=[
                        {"role": "system", "content": "You are an Elliott Wave analyst. Respond only in valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                    response_format={"type": "json_object"}
                )
                response = resp.choices[0].message.content
            except Exception as e:
                print(f"  ⚠️ API error: {e}")
                # Fallback: 일반 generate
                response = client.generate(
                    prompt=prompt,
                    system_prompt="You are an Elliott Wave analyst. Always respond in valid JSON only.",
                    temperature=0.2,
                    max_tokens=1024
                )
            
            # 응답 파싱
            validated_path = self._apply_llm_corrections(path, response)
            validated_paths.append(validated_path)
        
        return validated_paths
    
    def _apply_llm_corrections(self, path: WavePath, llm_response: str) -> WavePath:
        """LLM 응답을 파싱하여 경로에 적용"""
        try:
            # 강력한 JSON 추출
            cleaned = llm_response.strip()
            
            # 1) 마크다운 코드블록 제거
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'```\s*$', '', cleaned)
            
            # 2) JSON 객체 추출 (첫 번째 { ... } 매칭)
            match = re.search(r'\{[\s\S]*\}', cleaned)
            if match:
                cleaned = match.group(0)
            
            # 3) trailing comma 제거 (JSON 표준에 어긋남)
            cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)
            
            # 4) true/false 보정
            cleaned = cleaned.replace('True', 'true').replace('False', 'false')
            cleaned = re.sub(r'"valid":\s*true/false', '"valid": true', cleaned)
            cleaned = re.sub(r'"confidence":\s*"?0\.0\s*to\s*1\.0"?', '"confidence": 0.5', cleaned)
            
            # 5) ... 제거 + inline 주석 제거
            cleaned = re.sub(r',\s*\.\.\.[\s,]*', '', cleaned)
            cleaned = re.sub(r'//[^\n]*', '', cleaned)  # // 주석 제거
            
            # 6) 문자열 내부가 아닌 곳의 NaN, Infinity 처리
            cleaned = re.sub(r'\bNaN\b', '0', cleaned)
            cleaned = re.sub(r'\bInfinity\b', '999999', cleaned)
            
            # 7) 다시 trailing comma 정리 (이전 치환으로 생길 수 있음)
            cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)
            
            data = json.loads(cleaned)
            
            path.llm_validated = True
            path.llm_confidence = data.get('confidence', 0.5)
            path.llm_reasoning = data.get('reasoning', '')
            
            issues = data.get('issues', [])
            if issues:
                print(f"  ⚠️ Issues: {', '.join(issues)}")
            
            if not data.get('valid', True) and 'corrected_waves' in data:
                # 수정된 파동 적용
                corrected = data['corrected_waves']
                new_points = []
                for cw in corrected:
                    # 타입 검증: dict만 처리
                    if not isinstance(cw, dict):
                        continue
                    if 'label' not in cw or 'price' not in cw or 'day' not in cw:
                        continue
                    new_points.append(WavePoint(
                        label=str(cw['label']),
                        price=float(cw['price']),
                        day=int(cw['day']),
                        pct_from_start=float(cw.get('pct_from_start', 0))
                    ))
                
                # Start 포인트 추가 (없으면)
                if new_points and new_points[0].label != "Start":
                    new_points.insert(0, WavePoint(
                        label="Start", price=self.current_price, day=0, pct_from_start=0
                    ))
                
                # 일별 가격 재생성
                prices = [wp.price for wp in new_points]
                days_between = []
                for i in range(1, len(new_points)):
                    days_between.append(new_points[i].day - new_points[i-1].day)
                
                if days_between:
                    path.daily_prices = self._interpolate_wave_path(prices, days_between)
                    path.wave_points = new_points
                    print(f"  ✅ Corrected by LLM (confidence: {path.llm_confidence:.0%})")
                else:
                    print(f"  ✅ Valid (confidence: {path.llm_confidence:.0%})")
            else:
                print(f"  ✅ Valid (confidence: {path.llm_confidence:.0%})")
            
        except json.JSONDecodeError as e:
            print(f"  ⚠️ JSON parse error: {e}")
            path.llm_validated = False
            path.llm_reasoning = f"Parse error: {str(e)}"
        except Exception as e:
            print(f"  ⚠️ Validation error: {e}")
            path.llm_validated = False
            path.llm_reasoning = str(e)
        
        return path
    
    # ===== 보조 함수 =====
    
    def _interpolate_wave_path(
        self, 
        wave_prices: List[float], 
        time_days: List[int]
    ) -> List[float]:
        """
        파동 포인트 사이를 부드러운 곡선으로 보간
        
        각 세그먼트를 sine 곡선으로 연결하여
        파동의 가속/감속을 자연스럽게 표현
        """
        daily = [wave_prices[0]]
        
        for i in range(len(time_days)):
            start_p = wave_prices[i]
            end_p = wave_prices[i + 1]
            n = time_days[i]
            
            if n <= 0:
                continue
            
            # S-curve 보간 (sigmoid-like)
            t = np.linspace(0, np.pi, n + 1)
            # 0→π에서 (1 - cos(t))/2 는 0에서 1로 S-curve
            s_curve = (1 - np.cos(t)) / 2
            segment = start_p + (end_p - start_p) * s_curve
            
            # 미세 노이즈 추가 (실제 가격 변동 시뮬레이션)
            noise_scale = abs(end_p - start_p) * 0.008
            noise = np.random.normal(0, noise_scale, len(segment))
            noise[0] = 0
            noise[-1] = 0
            segment = segment + noise
            
            daily.extend(segment[1:].tolist())
        
        # 정확히 total_days 길이로 조정
        while len(daily) < self.total_days:
            daily.append(daily[-1])
        
        return daily[:self.total_days]


# ===== 테스트 =====

if __name__ == "__main__":
    import yfinance as yf
    
    print("=" * 60)
    print("🌊 Wave Path Generator v2 - Context-Aware Test")
    print("=" * 60)
    
    # 실시간 데이터
    btc = yf.Ticker("BTC-USD")
    hist = btc.history(period="1y")
    cp = float(hist['Close'].iloc[-1])
    atr = float(np.mean(hist['High'].tail(14).values - hist['Low'].tail(14).values))
    
    print(f"\n📊 BTC: ${cp:,.0f} | ATR: ${atr:,.0f}")
    
    # 경로 생성 (ScenarioGenerator 통합)
    gen = WavePathGenerator(current_price=cp, atr=atr, total_days=30, seed=42)
    paths = gen.generate_all_scenarios(df=hist)  # ← 피벗 기반 동적 시나리오
    
    print(f"\n📈 Generated {len(paths)} scenario paths:\n")
    for p in paths:
        wave_pos = f" [{p.current_wave}]" if p.current_wave else ""
        print(f"  {p.scenario_name} ({p.view}) prob={p.probability:.1%}{wave_pos}")
        for wp in p.wave_points:
            print(f"    {wp.label:6s} ${wp.price:>10,.0f}  Day {wp.day:2d}  ({wp.pct_from_start:+6.1f}%)")
        if p.description:
            print(f"    📝 {p.description[:70]}")
        print(f"    Daily prices: {len(p.daily_prices)} points")
        print()
    
    # LLM 검증
    print("=" * 60)
    print("🤖 Azure GPT-4o Validation (response_format: json_object)")
    print("=" * 60)
    validated = gen.validate_with_llm(paths)
    
    print("\n📊 Validation Results:")
    for p in validated:
        status = "✅" if p.llm_validated else "⏭️"
        print(f"  {status} {p.scenario_name}: confidence={p.llm_confidence:.0%}")
        if p.llm_reasoning:
            print(f"     → {p.llm_reasoning[:80]}")
    
    # ===== 차트 생성 =====
    print("\n📊 Generating chart...")
    
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    
    for fname in ['AppleGothic']:
        if any(fname in f.name for f in fm.fontManager.ttflist):
            plt.rcParams['font.family'] = fname
            plt.rcParams['axes.unicode_minus'] = False
            break
    
    prices = hist['Close'].tail(60).values
    N = gen.total_days
    
    fig = plt.figure(figsize=(18, 13))
    
    # Main chart
    ax = fig.add_axes([0.06, 0.35, 0.88, 0.58])
    ax.plot(range(len(prices)), prices, color='white', linewidth=2, zorder=5)
    ax.fill_between(range(len(prices)), hist['Low'].tail(60).values, 
                    hist['High'].tail(60).values, alpha=0.06, color='cyan')
    
    # NOW marker
    ax.scatter([len(prices)-1], [cp], color='yellow', s=150, zorder=10, 
              edgecolors='white', linewidths=2)
    ax.annotate(f'NOW ${cp:,.0f}', xy=(len(prices)-1, cp),
                xytext=(len(prices)+2, cp*1.02), fontsize=12, color='yellow', 
                fontweight='bold', arrowprops=dict(arrowstyle='->', color='yellow', lw=1.5))
    
    # Scenario paths with wave points
    x_start = len(prices) - 1
    for path in validated:
        daily = path.daily_prices
        x_fut = list(range(x_start, x_start + len(daily)))
        
        # Path line
        ax.plot(x_fut, daily, color=path.color, linewidth=2.5, linestyle='--', alpha=0.85)
        
        # Uncertainty band
        unc = np.abs(np.array(daily) - cp) * 0.04
        ax.fill_between(x_fut, np.array(daily)-unc, np.array(daily)+unc, 
                        alpha=0.05, color=path.color)
        
        # Wave points (피벗)
        for wp in path.wave_points[1:]:  # Start 제외
            x_pos = x_start + wp.day
            if x_pos < x_start + len(daily):
                ax.scatter([x_pos], [wp.price], color=path.color, s=40, zorder=8,
                          edgecolors='white', linewidths=0.5)
                ax.annotate(wp.label, xy=(x_pos, wp.price),
                           xytext=(3, 8 if wp.price > cp else -15),
                           textcoords='offset points',
                           fontsize=7, color=path.color, fontweight='bold')
        
        # End label
        end_p = daily[-1]
        pct = (end_p - cp) / cp * 100
        sign = '+' if pct > 0 else ''
        conf_str = f" [{path.llm_confidence:.0%}]" if path.llm_validated else ""
        label_text = f"{path.scenario_name} ({path.probability*100:.0f}%){conf_str}\n${end_p:,.0f} ({sign}{pct:.0f}%)"
        ax.annotate(label_text,
                    xy=(x_fut[-1], end_p), fontsize=9, color=path.color, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='#0d1117', 
                             edgecolor=path.color, alpha=0.9))
    
    # Divider
    ax.axvline(x=len(prices)-1, color='yellow', linestyle='-', alpha=0.2)
    ylim = ax.get_ylim()
    ax.text(len(prices)-5, ylim[1]*0.99, 'PAST', color='gray', fontsize=10, ha='right')
    ax.text(len(prices)+2, ylim[1]*0.99, 'PROJECTION (30d)', color='yellow', fontsize=10)
    
    ax.set_title(f'Deep Wave Oracle v3 — BTC-USD ${cp:,.0f}  |  Context-Aware Elliott Wave',
                 fontsize=15, fontweight='bold', color='white', pad=12)
    ax.set_facecolor('#0d1117')
    ax.tick_params(colors='gray')
    ax.grid(alpha=0.08, color='gray')
    ax.set_ylabel('Price (USD)', color='gray')
    
    ticks = [0, len(prices)//2, len(prices)-1, len(prices)+14, len(prices)+28]
    ax.set_xticks(ticks)
    ax.set_xticklabels([hist.index[-60].strftime('%m/%d'), hist.index[-30].strftime('%m/%d'), 
                         'TODAY', '+15d', '+30d'], color='gray')
    
    # Bottom panels
    # Probability
    ax2 = fig.add_axes([0.06, 0.04, 0.25, 0.26])
    sorted_paths = sorted(validated, key=lambda x: x.probability)
    for i, p in enumerate(sorted_paths):
        bar = ax2.barh(p.scenario_name.split(':')[0], p.probability*100, 
                       color=p.color, edgecolor='white', linewidth=0.5, height=0.6)
        ax2.text(p.probability*100+1, i, f'{p.probability*100:.0f}%', 
                 va='center', color='white', fontsize=10, fontweight='bold')
    ax2.set_xlim(0, 70)
    ax2.set_title('Scenario Probability (Dynamic)', fontsize=11, color='white')
    ax2.set_facecolor('#0d1117')
    ax2.tick_params(colors='gray')
    
    # Wave structure detail
    ax3 = fig.add_axes([0.35, 0.04, 0.30, 0.26])
    ax3.axis('off')
    ax3.set_facecolor('#0d1117')
    winner = max(validated, key=lambda x: x.probability)
    txt = f"  Top: {winner.scenario_name}\n"
    if winner.current_wave:
        txt += f"  Current Wave: {winner.current_wave}\n"
    txt += "\n"
    for wp in winner.wave_points:
        txt += f"  {wp.label:6s} ${wp.price:>10,.0f}  Day {wp.day:2d}  ({wp.pct_from_start:+.1f}%)\n"
    if winner.llm_validated:
        txt += f"\n  LLM Confidence: {winner.llm_confidence:.0%}"
        txt += f"\n  {winner.llm_reasoning[:55]}"
    ax3.text(0.02, 0.95, txt, transform=ax3.transAxes, fontsize=8.5, color='white',
             fontfamily='monospace', verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='#1a1a2e', 
                      edgecolor=winner.color, linewidth=2))
    
    # Volatility
    ax4 = fig.add_axes([0.70, 0.04, 0.24, 0.26])
    r10 = hist.tail(10)
    dr = ((r10['High']-r10['Low'])/r10['Close']*100).values
    ds = [d.strftime('%m/%d') for d in r10.index]
    bc = ['#ff4444' if r>10 else '#ffaa00' if r>5 else '#00ff88' for r in dr]
    ax4.bar(ds, dr, color=bc, edgecolor='white', linewidth=0.5)
    ax4.axhline(y=5, color='yellow', linestyle='--', alpha=0.4)
    ax4.axhline(y=10, color='red', linestyle='--', alpha=0.4)
    ax4.set_title('Daily Range (%)', fontsize=11, color='white')
    ax4.set_facecolor('#0d1117')
    ax4.tick_params(colors='gray', labelsize=7)
    ax4.tick_params(axis='x', rotation=45)
    
    fig.patch.set_facecolor('#0d1117')
    
    out = '/Users/changyoonjun/.gemini/antigravity/brain/2e411074-5f31-4d41-8741-5eb51c2fde04/deep_wave_oracle_v3.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    print(f"\n✅ Chart saved: {out}")

"""
Elliott Wave v2.0 통합 테스트
==============================

Phase 1-3 전체 기능 통합 테스트
"""

import sys
import os
import json
from datetime import datetime
from typing import Dict, List

# 테스트 결과 저장
TEST_RESULTS = {
    'timestamp': datetime.now().isoformat(),
    'phases': {},
    'summary': {},
    'errors': []
}


def test_phase1_multi_timeframe():
    """Phase 1: 다중 타임프레임 검증"""
    print("\n" + "=" * 60)
    print("📊 Phase 1: 다중 타임프레임 검증")
    print("=" * 60)
    
    results = {'status': 'PASS', 'tests': []}
    
    try:
        from experts.elliott.multi_timeframe_validator import MultiTimeframeValidator
        
        validator = MultiTimeframeValidator('BTC-USD')
        consensus = validator.validate(timeframes=['1d', '1h'])
        
        results['tests'].append({
            'name': 'MultiTimeframeValidator 생성',
            'status': 'PASS'
        })
        
        results['tests'].append({
            'name': f'합의 결과: {consensus.aligned_phase}',
            'status': 'PASS' if consensus.is_valid else 'WARN',
            'confidence': consensus.confidence
        })
        
        print(f"   ✅ 합의: {consensus.aligned_phase} ({consensus.confidence:.1%})")
        
    except Exception as e:
        results['status'] = 'FAIL'
        results['error'] = str(e)
        print(f"   ❌ 오류: {e}")
        TEST_RESULTS['errors'].append(f"Phase 1: {e}")
    
    return results


def test_phase1_invalidation_rules():
    """Phase 1: 무효화 규칙"""
    print("\n" + "-" * 40)
    print("📋 무효화 규칙 테스트")
    
    results = {'status': 'PASS', 'tests': []}
    
    try:
        from experts.elliott.wave_tracker import ScenarioGenerator, InvalidationRule
        
        waves = [
            {'label': '0', 'price': 15000, 'date': '2022-11-01'},
            {'label': '1', 'price': 31000, 'date': '2023-04-01'},
            {'label': '2', 'price': 25000, 'date': '2023-06-01'},
            {'label': '3', 'price': 73000, 'date': '2024-03-01'},
            {'label': '4', 'price': 56000, 'date': '2024-07-01'},
            {'label': '5', 'price': 109000, 'date': '2025-01-20'},
        ]
        
        gen = ScenarioGenerator()
        scenarios = gen.generate_from_analysis(waves, 70000, 'BTC-USD')
        
        # ABC 시나리오 무효화 규칙 확인
        abc_scenario = next((s for s in scenarios if 'ABC' in s.name), None)
        
        if abc_scenario:
            rule_count = len(abc_scenario.invalidation_rules)
            results['tests'].append({
                'name': f'ABC 시나리오 무효화 규칙 ({rule_count}개)',
                'status': 'PASS' if rule_count >= 2 else 'FAIL'
            })
            
            for rule in abc_scenario.invalidation_rules:
                print(f"   📌 {rule.description}")
        
        print(f"   ✅ {len(scenarios)} 시나리오 생성 완료")
        
    except Exception as e:
        results['status'] = 'FAIL'
        results['error'] = str(e)
        print(f"   ❌ 오류: {e}")
        TEST_RESULTS['errors'].append(f"Invalidation Rules: {e}")
    
    return results


def test_phase1_adaptive_tracker():
    """Phase 1: 적응형 추적기"""
    print("\n" + "-" * 40)
    print("🔄 적응형 추적기 테스트")
    
    results = {'status': 'PASS', 'tests': []}
    
    try:
        from experts.elliott.adaptive_tracker import AdaptiveWaveTracker
        
        tracker = AdaptiveWaveTracker('BTC-USD')
        
        # 시나리오 설정
        tracker.set_scenarios([
            {
                'id': 'abc',
                'name': 'ABC Correction',
                'probability': 0.7,
                'invalidation_price': 111180,
                'invalidation_type': 'price_above'
            }
        ])
        
        # 캔들 추가
        test_candle = {
            'date': datetime(2025, 2, 6),
            'open': 69000, 'high': 70000, 'low': 68000, 'close': 69500,
            'volume': 1000
        }
        
        result = tracker.add_candle(test_candle)
        
        results['tests'].append({
            'name': '캔들 추가',
            'status': 'PASS'
        })
        
        # 무효화 트리거 테스트
        trigger_candle = {
            'date': datetime(2025, 2, 7),
            'open': 110000, 'high': 115000, 'low': 109000, 'close': 112000,
            'volume': 2000
        }
        
        result = tracker.add_candle(trigger_candle)
        
        if result['invalidated_scenarios']:
            results['tests'].append({
                'name': f'무효화 감지: {result["invalidated_scenarios"]}',
                'status': 'PASS'
            })
            print(f"   ✅ 무효화 감지: {result['invalidated_scenarios']}")
        
        status = tracker.get_status()
        print(f"   ✅ 상태: {status['current_phase']}")
        
    except Exception as e:
        results['status'] = 'FAIL'
        results['error'] = str(e)
        print(f"   ❌ 오류: {e}")
        TEST_RESULTS['errors'].append(f"Adaptive Tracker: {e}")
    
    return results


def test_phase2_subwave():
    """Phase 2: 서브파동 분석"""
    print("\n" + "=" * 60)
    print("📈 Phase 2: 서브파동 분석")
    print("=" * 60)
    
    results = {'status': 'PASS', 'tests': []}
    
    try:
        import yfinance as yf
        from experts.elliott.subwave_analyzer import SubWaveAnalyzer
        
        # 데이터 로드
        df = yf.download('BTC-USD', period='2y', interval='1d', progress=False)
        if hasattr(df.columns, 'get_level_values'):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.title() for c in df.columns]
        
        waves = {
            '0': {'price': 15000, 'date': '2022-11-01'},
            '1': {'price': 31000, 'date': '2023-04-01'},
            '2': {'price': 25000, 'date': '2023-06-01'},
            '3': {'price': 73000, 'date': '2024-03-01'},
            '4': {'price': 56000, 'date': '2024-07-01'},
            '5': {'price': 109000, 'date': '2025-01-20'},
        }
        
        analyzer = SubWaveAnalyzer(df, waves)
        analysis = analyzer.analyze_all()
        
        # 서브파동
        sub_count = sum(len(subs) for subs in analysis['sub_waves'].values())
        results['tests'].append({
            'name': f'서브파동 감지: {sub_count}개',
            'status': 'PASS' if sub_count > 0 else 'WARN'
        })
        print(f"   ✅ 서브파동: {sub_count}개")
        
        # 거래량 검증
        vol_valid = all(v.is_valid for v in analysis['volume_validation'].values())
        results['tests'].append({
            'name': '거래량 검증',
            'status': 'PASS' if vol_valid else 'WARN'
        })
        print(f"   ✅ 거래량 검증: {'통과' if vol_valid else '주의'}")
        
        # 시간 비율
        time_valid = all(t.is_valid for t in analysis['time_validation'])
        results['tests'].append({
            'name': '시간 비율 검증',
            'status': 'PASS' if time_valid else 'WARN'
        })
        print(f"   ✅ 시간 비율: {'통과' if time_valid else '주의'}")
        
        # 진입 구간
        entry_count = len(analysis['entry_zones'])
        print(f"   ✅ 진입 구간: {entry_count}개")
        
    except Exception as e:
        results['status'] = 'FAIL'
        results['error'] = str(e)
        print(f"   ❌ 오류: {e}")
        TEST_RESULTS['errors'].append(f"Phase 2: {e}")
    
    return results


def test_phase3_multi_agent():
    """Phase 3: Multi-Agent 시스템"""
    print("\n" + "=" * 60)
    print("🤖 Phase 3: Multi-Agent 시스템")
    print("=" * 60)
    
    results = {'status': 'PASS', 'tests': []}
    
    try:
        import yfinance as yf
        from experts.elliott.multi_agent_system import ElliottWaveAgentSystem
        
        df = yf.download('BTC-USD', period='2y', interval='1d', progress=False)
        if hasattr(df.columns, 'get_level_values'):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.title() for c in df.columns]
        
        current_price = float(df['Close'].iloc[-1])
        
        system = ElliottWaveAgentSystem()
        analysis = system.analyze(df, current_price)
        
        results['tests'].append({
            'name': f'에이전트 실행: {len(analysis["execution_log"])}개',
            'status': 'PASS' if analysis['success'] else 'FAIL'
        })
        
        results['tests'].append({
            'name': f'시나리오 생성: {len(analysis["scenarios"])}개',
            'status': 'PASS' if analysis['scenarios'] else 'FAIL'
        })
        
        print(f"   ✅ 시나리오 확률:")
        for s in analysis['scenarios']:
            print(f"      {s['name']}: {s['probability']:.1%}")
        
    except Exception as e:
        results['status'] = 'FAIL'
        results['error'] = str(e)
        print(f"   ❌ 오류: {e}")
        TEST_RESULTS['errors'].append(f"Phase 3 Multi-Agent: {e}")
    
    return results


def test_phase3_pattern_rag():
    """Phase 3: 패턴 RAG"""
    print("\n" + "-" * 40)
    print("🔍 패턴 RAG 테스트")
    
    results = {'status': 'PASS', 'tests': []}
    
    try:
        from experts.elliott.pattern_rag import ElliottWaveRAG
        
        rag = ElliottWaveRAG()
        
        # 현재 패턴
        current_waves = {
            '0': 15500, '1': 31000, '2': 25000,
            '3': 73000, '4': 56000, '5': 109000
        }
        
        # 유사 패턴 검색
        similar = rag.search_similar(current_waves, top_k=3)
        results['tests'].append({
            'name': f'유사 패턴: {len(similar)}개',
            'status': 'PASS' if similar else 'WARN'
        })
        
        # 결과 예측
        prediction = rag.predict_outcome(current_waves, 69000)
        results['tests'].append({
            'name': f'예측: {prediction["predicted_outcome"]}',
            'status': 'PASS',
            'confidence': prediction['confidence']
        })
        
        print(f"   ✅ 유사 패턴: {len(similar)}개")
        print(f"   ✅ 예측 결과: {prediction['predicted_outcome']} ({prediction['confidence']:.1%})")
        
    except Exception as e:
        results['status'] = 'FAIL'
        results['error'] = str(e)
        print(f"   ❌ 오류: {e}")
        TEST_RESULTS['errors'].append(f"Pattern RAG: {e}")
    
    return results


def run_all_tests():
    """전체 테스트 실행"""
    print("\n" + "=" * 60)
    print("🚀 Elliott Wave v2.0 통합 테스트")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Phase 1
    TEST_RESULTS['phases']['phase1_mtf'] = test_phase1_multi_timeframe()
    TEST_RESULTS['phases']['phase1_invalidation'] = test_phase1_invalidation_rules()
    TEST_RESULTS['phases']['phase1_adaptive'] = test_phase1_adaptive_tracker()
    
    # Phase 2
    TEST_RESULTS['phases']['phase2_subwave'] = test_phase2_subwave()
    
    # Phase 3
    TEST_RESULTS['phases']['phase3_multi_agent'] = test_phase3_multi_agent()
    TEST_RESULTS['phases']['phase3_rag'] = test_phase3_pattern_rag()
    
    # 요약
    print("\n" + "=" * 60)
    print("📋 테스트 요약")
    print("=" * 60)
    
    passed = sum(1 for p in TEST_RESULTS['phases'].values() if p['status'] == 'PASS')
    total = len(TEST_RESULTS['phases'])
    
    TEST_RESULTS['summary'] = {
        'passed': passed,
        'total': total,
        'pass_rate': passed / total if total > 0 else 0,
        'error_count': len(TEST_RESULTS['errors'])
    }
    
    print(f"   통과: {passed}/{total} ({TEST_RESULTS['summary']['pass_rate']:.1%})")
    print(f"   오류: {TEST_RESULTS['summary']['error_count']}개")
    
    if TEST_RESULTS['errors']:
        print("\n⚠️ 오류 목록:")
        for err in TEST_RESULTS['errors']:
            print(f"   - {err}")
    
    return TEST_RESULTS


if __name__ == '__main__':
    results = run_all_tests()
    
    # 결과 저장
    os.makedirs('data/test_results', exist_ok=True)
    with open('data/test_results/elliott_v2_test.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n✅ 결과 저장: data/test_results/elliott_v2_test.json")

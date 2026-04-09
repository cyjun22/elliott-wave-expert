"""
Elliott Wave Report Generator
==============================
일관된 시각적 보고서 생성 모듈

매 실행마다 동일한 포맷의 HTML 보고서를 생성하여
결과의 비교 가능성과 가독성을 보장.

주요 기능:
- 시스템 상태 대시보드 (패턴 수, 테스트, 코드 라인 등)
- 패턴 인식 현황 차트 (12종 패턴 구현 상태)
- 시나리오 무효화 시스템 상태
- 코드 품질 지표
- 변경 이력 타임라인

Usage:
    from report_generator import ReportGenerator
    gen = ReportGenerator(project_root=".")
    gen.generate("output/report.html")

    # CLI:
    python report_generator.py                  # → reports/elliott_report_YYYYMMDD_HHMMSS.html
    python report_generator.py -o my_report.html
    python report_generator.py --json           # JSON 데이터만 출력
"""

import os
import re
import ast
import json
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ─────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────

@dataclass
class FileMetrics:
    """파일별 코드 지표"""
    path: str
    lines: int
    classes: int
    functions: int
    docstring_ratio: float  # 독스트링 보유 함수 비율

@dataclass
class PatternStatus:
    """패턴 구현 상태"""
    name: str
    category: str           # 'motive' | 'corrective'
    implemented: bool
    test_covered: bool
    line_count: int

@dataclass
class TestRunResult:
    """테스트 실행 결과"""
    total: int
    passed: int
    failed: int
    errors: int
    duration_sec: float
    details: List[Dict] = field(default_factory=list)

@dataclass
class GitInfo:
    """Git 커밋 정보"""
    commit_hash: str
    message: str
    date: str
    files_changed: int
    insertions: int
    deletions: int

@dataclass
class ReportData:
    """보고서 전체 데이터"""
    generated_at: str
    project_name: str
    version: str

    # 코드 지표
    total_files: int
    total_lines: int
    total_classes: int
    total_functions: int
    avg_docstring_ratio: float
    file_metrics: List[FileMetrics]

    # 패턴 현황
    patterns: List[PatternStatus]
    patterns_implemented: int
    patterns_total: int

    # 테스트
    test_result: TestRunResult

    # Git
    git_log: List[GitInfo]
    current_branch: str

    # 아키텍처
    module_groups: Dict[str, List[str]]  # 그룹명 → 파일 목록

    # 보안/품질
    security_issues: List[Dict]
    quality_score: float  # 0-100


# ─────────────────────────────────────────────
# Collector — 프로젝트에서 데이터 수집
# ─────────────────────────────────────────────

class ProjectCollector:
    """프로젝트 루트에서 메트릭 수집"""

    PATTERN_DEFINITIONS = [
        ("Impulse",          "motive"),
        ("Leading Diagonal", "motive"),
        ("Ending Diagonal",  "motive"),
        ("Zigzag",           "corrective"),
        ("Double Zigzag",    "corrective"),
        ("Triple Zigzag",    "corrective"),
        ("Flat",             "corrective"),
        ("Expanded Flat",    "corrective"),
        ("Running Flat",     "corrective"),
        ("Triangle",         "corrective"),
        ("Complex (WXY)",    "corrective"),
        ("Unknown",          "other"),
    ]

    MODULE_GROUPS = {
        "Core Analysis": [
            "core.py", "patterns.py", "validation.py", "targets.py",
        ],
        "Tracking Engine": [
            "wave_tracker.py", "wave_scenarios.py", "wave_visualization.py",
            "live_tracker.py", "adaptive_tracker.py", "tracker_history.py",
        ],
        "AI / LLM": [
            "llm_utils.py", "llm_validator.py", "dual_agent_expert.py",
            "hybrid_expert.py", "rag_expert.py", "pattern_rag.py",
            "ai_strategist_report.py",
        ],
        "Multi-agent": [
            "multi_agent_system.py", "multi_timeframe_validator.py",
            "subwave_analyzer.py",
        ],
        "Visualization": [
            "chart_renderer.py", "scenario_chart.py",
            "wave_path_generator.py",
        ],
        "Execution": [
            "strategy_executor.py", "retroactive_adjuster.py",
            "data_validator.py",
        ],
    }

    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()

    # ── 파일 지표 ────────────────────────────

    def _python_files(self) -> List[Path]:
        """테스트 제외 Python 파일 목록"""
        return sorted(
            p for p in self.root.glob("*.py")
            if not p.name.startswith("test_") and p.name != "conftest.py"
        )

    def _test_files(self) -> List[Path]:
        """테스트 파일 목록"""
        files = list(self.root.glob("tests/test_*.py"))
        files += [p for p in self.root.glob("test_*.py")]
        return sorted(set(files))

    def _analyze_file(self, path: Path) -> FileMetrics:
        source = path.read_text(encoding="utf-8", errors="replace")
        lines = source.count("\n") + 1

        classes = 0
        functions = 0
        has_docstring = 0
        total_defs = 0

        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    classes += 1
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions += 1
                    total_defs += 1
                    if (node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                        has_docstring += 1
        except SyntaxError:
            pass

        ratio = has_docstring / total_defs if total_defs else 0.0
        return FileMetrics(
            path=path.name, lines=lines,
            classes=classes, functions=functions,
            docstring_ratio=round(ratio, 2),
        )

    # ── 패턴 현황 ────────────────────────────

    def _check_patterns(self) -> List[PatternStatus]:
        patterns_file = self.root / "patterns.py"
        test_files_content = ""
        for tf in self._test_files():
            test_files_content += tf.read_text(encoding="utf-8", errors="replace")

        source = ""
        if patterns_file.exists():
            source = patterns_file.read_text(encoding="utf-8", errors="replace")

        results = []
        for name, cat in self.PATTERN_DEFINITIONS:
            # 구현 여부: recognize 메서드 내에서 패턴 이름 또는 enum 확인
            key = name.lower().replace(" ", "_").replace("(", "").replace(")", "")
            implemented = (
                key in source.lower()
                or name.lower() in source.lower()
            )
            # 테스트 커버리지
            test_covered = (
                key in test_files_content.lower()
                or name.lower() in test_files_content.lower()
            )
            # 해당 패턴 관련 코드 줄 수 (대략)
            line_count = sum(
                1 for line in source.split("\n")
                if key in line.lower() or name.lower() in line.lower()
            )
            results.append(PatternStatus(
                name=name, category=cat,
                implemented=implemented, test_covered=test_covered,
                line_count=line_count,
            ))
        return results

    # ── 테스트 실행 ──────────────────────────

    def _run_tests(self) -> TestRunResult:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=no", "-q",
                 "-p", "no:cacheprovider",
                 "--ignore=tests/test_report.py",  # 재귀 방지
                 str(self.root / "tests"), str(self.root / "test_v2_integration.py")],
                capture_output=True, text=True, cwd=str(self.root),
                timeout=60,
            )
            output = proc.stdout + proc.stderr
            # "76 passed" 파싱
            m = re.search(r"(\d+)\s+passed", output)
            passed = int(m.group(1)) if m else 0
            m_fail = re.search(r"(\d+)\s+failed", output)
            failed = int(m_fail.group(1)) if m_fail else 0
            m_err = re.search(r"(\d+)\s+error", output)
            errors = int(m_err.group(1)) if m_err else 0
            m_dur = re.search(r"in\s+([\d.]+)s", output)
            dur = float(m_dur.group(1)) if m_dur else 0.0

            return TestRunResult(
                total=passed + failed + errors,
                passed=passed, failed=failed, errors=errors,
                duration_sec=dur,
            )
        except Exception as e:
            return TestRunResult(total=0, passed=0, failed=0, errors=1,
                              duration_sec=0, details=[{"error": str(e)}])

    # ── Git 정보 ─────────────────────────────

    def _git_log(self, max_commits: int = 10) -> Tuple[List[GitInfo], str]:
        log = []
        branch = "unknown"
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.root), text=True, stderr=subprocess.DEVNULL,
            ).strip()

            raw = subprocess.check_output(
                ["git", "log", f"-{max_commits}",
                 "--format=%H|||%s|||%ad|||%h", "--date=iso-strict"],
                cwd=str(self.root), text=True, stderr=subprocess.DEVNULL,
            ).strip()

            for line in raw.split("\n"):
                if "|||" not in line:
                    continue
                parts = line.split("|||")
                full_hash, msg, date_str, short = parts[0], parts[1], parts[2], parts[3]

                # diff stat
                try:
                    stat = subprocess.check_output(
                        ["git", "diff", "--shortstat", f"{full_hash}~1", full_hash],
                        cwd=str(self.root), text=True, stderr=subprocess.DEVNULL,
                    ).strip()
                except Exception:
                    stat = ""

                fc = ins = dels = 0
                m_fc = re.search(r"(\d+)\s+file", stat)
                m_ins = re.search(r"(\d+)\s+insertion", stat)
                m_del = re.search(r"(\d+)\s+deletion", stat)
                if m_fc:
                    fc = int(m_fc.group(1))
                if m_ins:
                    ins = int(m_ins.group(1))
                if m_del:
                    dels = int(m_del.group(1))

                log.append(GitInfo(
                    commit_hash=short, message=msg,
                    date=date_str, files_changed=fc,
                    insertions=ins, deletions=dels,
                ))
        except Exception:
            pass
        return log, branch

    # ── 보안/품질 ────────────────────────────

    def _security_scan(self) -> List[Dict]:
        issues = []
        for py in self._python_files():
            source = py.read_text(encoding="utf-8", errors="replace")
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # bare except
                if re.match(r"except\s*:", stripped):
                    issues.append({
                        "file": py.name, "line": i,
                        "severity": "warning",
                        "issue": "Bare except clause",
                    })
                # SQL injection
                if "f\"" in stripped and ("execute" in stripped or "INSERT" in stripped.upper()):
                    issues.append({
                        "file": py.name, "line": i,
                        "severity": "high",
                        "issue": "Potential SQL injection (f-string in query)",
                    })
                # eval/exec
                if re.match(r"(eval|exec)\s*\(", stripped):
                    issues.append({
                        "file": py.name, "line": i,
                        "severity": "high",
                        "issue": f"Dangerous {stripped.split('(')[0]}() call",
                    })
        return issues

    def _quality_score(
        self, file_metrics: List[FileMetrics],
        test_result: TestRunResult,
        patterns: List[PatternStatus],
        security_issues: List[Dict],
    ) -> float:
        score = 100.0

        # 독스트링 커버리지 (최대 -20)
        avg_doc = (
            sum(f.docstring_ratio for f in file_metrics) / len(file_metrics)
            if file_metrics else 0
        )
        score -= max(0, (0.6 - avg_doc)) * 33  # 60% 미만이면 감점

        # 테스트 통과율 (최대 -30)
        if test_result.total > 0:
            pass_rate = test_result.passed / test_result.total
            score -= (1 - pass_rate) * 30
        else:
            score -= 30

        # 패턴 구현율 (최대 -20)
        impl = sum(1 for p in patterns if p.implemented)
        total = len(patterns)
        if total > 0:
            score -= (1 - impl / total) * 20

        # 보안 이슈 (고위험 -5 / 경고 -2)
        for issue in security_issues:
            if issue["severity"] == "high":
                score -= 5
            else:
                score -= 2

        return round(max(0, min(100, score)), 1)

    # ── 통합 수집 ────────────────────────────

    def collect(self) -> ReportData:
        py_files = self._python_files()
        file_metrics = [self._analyze_file(f) for f in py_files]
        patterns = self._check_patterns()
        test_result = self._run_tests()
        git_log, branch = self._git_log()
        security = self._security_scan()

        all_py = list(self.root.glob("*.py")) + list(self.root.glob("tests/*.py"))
        total_lines = sum(
            p.read_text(encoding="utf-8", errors="replace").count("\n") + 1
            for p in all_py if p.exists()
        )

        return ReportData(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            project_name="Elliott Wave Expert",
            version=self._detect_version(),
            total_files=len(all_py),
            total_lines=total_lines,
            total_classes=sum(f.classes for f in file_metrics),
            total_functions=sum(f.functions for f in file_metrics),
            avg_docstring_ratio=round(
                sum(f.docstring_ratio for f in file_metrics) / len(file_metrics), 2
            ) if file_metrics else 0,
            file_metrics=file_metrics,
            patterns=patterns,
            patterns_implemented=sum(1 for p in patterns if p.implemented),
            patterns_total=len(patterns),
            test_result=test_result,
            git_log=git_log,
            current_branch=branch,
            module_groups=self.MODULE_GROUPS,
            security_issues=security,
            quality_score=self._quality_score(
                file_metrics, test_result, patterns, security,
            ),
        )

    def _detect_version(self) -> str:
        cl = self.root / "CHANGELOG.md"
        if cl.exists():
            content = cl.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"##\s+\[?(v?[\d.]+)", content)
            if m:
                return m.group(1)
        return "unknown"


# ─────────────────────────────────────────────
# HTML Renderer
# ─────────────────────────────────────────────

class HTMLRenderer:
    """ReportData → HTML 변환"""

    @staticmethod
    def render(data: ReportData) -> str:
        d = data  # shorthand

        # 패턴 카드 HTML
        pattern_cards = ""
        for p in d.patterns:
            cat_class = {
                "motive": "cat-motive",
                "corrective": "cat-corrective",
            }.get(p.category, "cat-other")
            status_icon = "✓" if p.implemented else "✗"
            status_class = "impl-yes" if p.implemented else "impl-no"
            test_badge = (
                '<span class="badge badge-pass">tested</span>'
                if p.test_covered
                else '<span class="badge badge-skip">no test</span>'
            )
            pattern_cards += f"""
            <div class="pattern-card {cat_class}">
                <span class="pattern-status {status_class}">{status_icon}</span>
                <span class="pattern-name">{p.name}</span>
                {test_badge}
            </div>"""

        # 파일 테이블 행
        file_rows = ""
        for fm in sorted(d.file_metrics, key=lambda x: -x.lines):
            bar_w = min(100, fm.lines / 12)  # 1200줄 = 100%
            doc_pct = f"{fm.docstring_ratio:.0%}"
            file_rows += f"""
            <tr>
                <td class="cell-file">{fm.path}</td>
                <td class="cell-num">{fm.lines:,}</td>
                <td class="cell-num">{fm.classes}</td>
                <td class="cell-num">{fm.functions}</td>
                <td>
                    <div class="bar-track"><div class="bar-fill" style="width:{bar_w}%"></div></div>
                </td>
                <td class="cell-num">{doc_pct}</td>
            </tr>"""

        # Git 커밋 행
        commit_rows = ""
        for g in d.git_log:
            commit_rows += f"""
            <tr>
                <td><code>{g.commit_hash}</code></td>
                <td>{g.message}</td>
                <td class="cell-num">{g.files_changed}</td>
                <td class="cell-num add">+{g.insertions:,}</td>
                <td class="cell-num del">-{g.deletions:,}</td>
                <td class="cell-date">{g.date[:10]}</td>
            </tr>"""

        # 보안 이슈 행
        security_rows = ""
        if d.security_issues:
            for s in d.security_issues:
                sev_class = "sev-high" if s["severity"] == "high" else "sev-warn"
                security_rows += f"""
                <tr>
                    <td><span class="sev-badge {sev_class}">{s['severity']}</span></td>
                    <td>{s['file']}:{s['line']}</td>
                    <td>{s['issue']}</td>
                </tr>"""
        else:
            security_rows = '<tr><td colspan="3" class="no-issues">보안 이슈 없음</td></tr>'

        # 모듈 그룹 시각화
        module_html = ""
        for group_name, files in d.module_groups.items():
            chips = "".join(f'<span class="mod-chip">{f}</span>' for f in files)
            module_html += f"""
            <div class="mod-group">
                <div class="mod-title">{group_name}</div>
                <div class="mod-chips">{chips}</div>
            </div>"""

        # 테스트 결과 바
        test_pass_pct = (
            d.test_result.passed / d.test_result.total * 100
            if d.test_result.total > 0 else 0
        )

        # 품질 점수 색상
        if d.quality_score >= 80:
            q_color = "#10b981"
        elif d.quality_score >= 60:
            q_color = "#f59e0b"
        else:
            q_color = "#ef4444"

        html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{d.project_name} — Analysis Report</title>
<style>
/* ─── Reset & Base ─── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0a0e17;
    color: #c9d1d9;
    line-height: 1.6;
    padding: 0;
}}
a {{ color: #58a6ff; text-decoration: none; }}

/* ─── Layout ─── */
.report {{
    max-width: 1120px;
    margin: 0 auto;
    padding: 40px 24px;
}}

/* ─── Header ─── */
.header {{
    text-align: center;
    padding: 48px 0 32px;
    border-bottom: 1px solid #1e2736;
    margin-bottom: 40px;
}}
.header h1 {{
    font-size: 2rem;
    font-weight: 700;
    color: #e6edf3;
    letter-spacing: -0.5px;
}}
.header .subtitle {{
    color: #7d8590;
    font-size: 0.95rem;
    margin-top: 8px;
}}
.header .version-badge {{
    display: inline-block;
    background: #1f6feb22;
    color: #58a6ff;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 600;
    margin-top: 12px;
    border: 1px solid #1f6feb44;
}}

/* ─── KPI Cards ─── */
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 40px;
}}
.kpi-card {{
    background: #111827;
    border: 1px solid #1e2736;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
}}
.kpi-value {{
    font-size: 2rem;
    font-weight: 700;
    color: #e6edf3;
}}
.kpi-label {{
    font-size: 0.8rem;
    color: #7d8590;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
}}

/* ─── Sections ─── */
.section {{
    margin-bottom: 40px;
}}
.section-title {{
    font-size: 1.15rem;
    font-weight: 600;
    color: #e6edf3;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid #1e2736;
    display: flex;
    align-items: center;
    gap: 8px;
}}
.section-icon {{
    font-size: 1.2rem;
}}

/* ─── Quality Score Ring ─── */
.quality-ring-wrapper {{
    display: flex;
    justify-content: center;
    margin-bottom: 32px;
}}
.quality-ring {{
    position: relative;
    width: 160px;
    height: 160px;
}}
.quality-ring svg {{
    transform: rotate(-90deg);
}}
.quality-ring .ring-bg {{
    fill: none;
    stroke: #1e2736;
    stroke-width: 12;
}}
.quality-ring .ring-fg {{
    fill: none;
    stroke: {q_color};
    stroke-width: 12;
    stroke-linecap: round;
    stroke-dasharray: {d.quality_score * 4.4} 440;
    transition: stroke-dasharray 1s ease;
}}
.quality-ring .ring-label {{
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
}}
.quality-ring .ring-score {{
    font-size: 2.2rem;
    font-weight: 700;
    color: {q_color};
}}
.quality-ring .ring-text {{
    font-size: 0.75rem;
    color: #7d8590;
}}

/* ─── Patterns Grid ─── */
.pattern-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
}}
.pattern-card {{
    display: flex;
    align-items: center;
    gap: 10px;
    background: #111827;
    border: 1px solid #1e2736;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 0.9rem;
}}
.pattern-card.cat-motive {{ border-left: 3px solid #3b82f6; }}
.pattern-card.cat-corrective {{ border-left: 3px solid #a855f7; }}
.pattern-card.cat-other {{ border-left: 3px solid #6b7280; }}
.pattern-status {{
    font-size: 1.1rem;
    font-weight: 700;
    width: 22px;
    text-align: center;
}}
.impl-yes {{ color: #10b981; }}
.impl-no {{ color: #ef4444; }}
.pattern-name {{ flex: 1; color: #c9d1d9; }}
.badge {{
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 600;
}}
.badge-pass {{ background: #10b98122; color: #34d399; }}
.badge-skip {{ background: #6b728022; color: #9ca3af; }}

/* ─── Test Bar ─── */
.test-bar-wrapper {{
    background: #111827;
    border: 1px solid #1e2736;
    border-radius: 12px;
    padding: 20px;
}}
.test-summary {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}}
.test-count {{
    font-size: 1.6rem;
    font-weight: 700;
    color: #e6edf3;
}}
.test-count span {{ color: #10b981; }}
.test-duration {{
    color: #7d8590;
    font-size: 0.85rem;
}}
.test-bar {{
    height: 12px;
    background: #1e2736;
    border-radius: 6px;
    overflow: hidden;
}}
.test-bar-fill {{
    height: 100%;
    border-radius: 6px;
    background: linear-gradient(90deg, #10b981, #34d399);
    width: {test_pass_pct}%;
    transition: width 0.8s ease;
}}

/* ─── Tables ─── */
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
}}
thead th {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 2px solid #1e2736;
    color: #7d8590;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.5px;
}}
tbody td {{
    padding: 8px 12px;
    border-bottom: 1px solid #1e273644;
}}
tbody tr:hover {{ background: #111827; }}
.cell-file {{ font-family: 'JetBrains Mono', monospace; color: #e6edf3; font-size: 0.82rem; }}
.cell-num {{ text-align: right; font-family: 'JetBrains Mono', monospace; }}
.cell-date {{ color: #7d8590; font-size: 0.8rem; }}
.add {{ color: #3fb950; }}
.del {{ color: #f85149; }}
code {{
    background: #1e2736;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
}}

/* ─── Bar Chart ─── */
.bar-track {{
    height: 8px;
    background: #1e2736;
    border-radius: 4px;
    overflow: hidden;
    min-width: 80px;
}}
.bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, #1f6feb, #58a6ff);
    border-radius: 4px;
}}

/* ─── Module Groups ─── */
.mod-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 16px;
}}
.mod-group {{
    background: #111827;
    border: 1px solid #1e2736;
    border-radius: 10px;
    padding: 16px;
}}
.mod-title {{
    font-weight: 600;
    color: #e6edf3;
    margin-bottom: 10px;
    font-size: 0.9rem;
}}
.mod-chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}}
.mod-chip {{
    background: #1e2736;
    color: #8b949e;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 0.78rem;
    font-family: 'JetBrains Mono', monospace;
}}

/* ─── Security ─── */
.sev-badge {{
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
}}
.sev-high {{ background: #f8514922; color: #f85149; }}
.sev-warn {{ background: #f59e0b22; color: #f59e0b; }}
.no-issues {{
    text-align: center;
    color: #10b981;
    padding: 16px !important;
    font-weight: 500;
}}

/* ─── Footer ─── */
.footer {{
    text-align: center;
    padding: 32px 0;
    border-top: 1px solid #1e2736;
    color: #484f58;
    font-size: 0.8rem;
    margin-top: 40px;
}}

/* ─── Print ─── */
@media print {{
    body {{ background: #fff; color: #1f2937; }}
    .kpi-card, .pattern-card, .mod-group, .test-bar-wrapper {{
        background: #f9fafb;
        border-color: #e5e7eb;
    }}
}}
</style>
</head>
<body>
<div class="report">

    <!-- Header -->
    <div class="header">
        <h1>⚡ {d.project_name}</h1>
        <div class="subtitle">System Analysis Report — {d.generated_at}</div>
        <div class="version-badge">{d.version} · {d.current_branch}</div>
    </div>

    <!-- Quality Score -->
    <div class="quality-ring-wrapper">
        <div class="quality-ring">
            <svg width="160" height="160" viewBox="0 0 160 160">
                <circle class="ring-bg" cx="80" cy="80" r="70"/>
                <circle class="ring-fg" cx="80" cy="80" r="70"/>
            </svg>
            <div class="ring-label">
                <div class="ring-score">{d.quality_score}</div>
                <div class="ring-text">Quality Score</div>
            </div>
        </div>
    </div>

    <!-- KPI Cards -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-value">{d.total_files}</div>
            <div class="kpi-label">Python Files</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{d.total_lines:,}</div>
            <div class="kpi-label">Total Lines</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{d.total_classes}</div>
            <div class="kpi-label">Classes</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{d.total_functions}</div>
            <div class="kpi-label">Functions</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{d.patterns_implemented}/{d.patterns_total}</div>
            <div class="kpi-label">Patterns</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{d.test_result.passed}/{d.test_result.total}</div>
            <div class="kpi-label">Tests Passed</div>
        </div>
    </div>

    <!-- Tests -->
    <div class="section">
        <div class="section-title"><span class="section-icon">🧪</span> Test Results</div>
        <div class="test-bar-wrapper">
            <div class="test-summary">
                <div class="test-count"><span>{d.test_result.passed}</span> / {d.test_result.total} passed</div>
                <div class="test-duration">{d.test_result.duration_sec:.2f}s</div>
            </div>
            <div class="test-bar"><div class="test-bar-fill"></div></div>
        </div>
    </div>

    <!-- Patterns -->
    <div class="section">
        <div class="section-title"><span class="section-icon">🔬</span> Pattern Implementation ({d.patterns_implemented}/{d.patterns_total})</div>
        <div class="pattern-grid">
            {pattern_cards}
        </div>
    </div>

    <!-- Architecture -->
    <div class="section">
        <div class="section-title"><span class="section-icon">🏗️</span> Module Architecture</div>
        <div class="mod-grid">
            {module_html}
        </div>
    </div>

    <!-- File Metrics -->
    <div class="section">
        <div class="section-title"><span class="section-icon">📊</span> File Metrics</div>
        <table>
            <thead>
                <tr>
                    <th>File</th>
                    <th style="text-align:right">Lines</th>
                    <th style="text-align:right">Classes</th>
                    <th style="text-align:right">Functions</th>
                    <th>Size</th>
                    <th style="text-align:right">Docstrings</th>
                </tr>
            </thead>
            <tbody>
                {file_rows}
            </tbody>
        </table>
    </div>

    <!-- Git History -->
    <div class="section">
        <div class="section-title"><span class="section-icon">📝</span> Git History</div>
        <table>
            <thead>
                <tr>
                    <th>Hash</th>
                    <th>Message</th>
                    <th style="text-align:right">Files</th>
                    <th style="text-align:right">+</th>
                    <th style="text-align:right">-</th>
                    <th>Date</th>
                </tr>
            </thead>
            <tbody>
                {commit_rows}
            </tbody>
        </table>
    </div>

    <!-- Security -->
    <div class="section">
        <div class="section-title"><span class="section-icon">🛡️</span> Security Scan</div>
        <table>
            <thead>
                <tr>
                    <th>Severity</th>
                    <th>Location</th>
                    <th>Issue</th>
                </tr>
            </thead>
            <tbody>
                {security_rows}
            </tbody>
        </table>
    </div>

    <!-- Footer -->
    <div class="footer">
        Generated by Elliott Wave Report Generator · {d.generated_at}
    </div>

</div>
</body>
</html>"""
        return html


# ─────────────────────────────────────────────
# ReportGenerator — 통합 인터페이스
# ─────────────────────────────────────────────

class ReportGenerator:
    """
    일관된 시각적 보고서 생성기

    Usage:
        gen = ReportGenerator(project_root="/path/to/elliott-wave-expert")
        gen.generate("report.html")
        gen.generate_json("report.json")
    """

    def __init__(self, project_root: str = "."):
        self.collector = ProjectCollector(root=project_root)
        self._data: Optional[ReportData] = None

    def collect(self) -> ReportData:
        """데이터 수집 (캐시)"""
        if self._data is None:
            self._data = self.collector.collect()
        return self._data

    def generate(self, output_path: str = None) -> str:
        """
        HTML 보고서 생성

        Args:
            output_path: 저장 경로 (None이면 reports/ 디렉토리에 자동 생성)

        Returns:
            생성된 파일 경로
        """
        data = self.collect()

        if output_path is None:
            reports_dir = Path(self.collector.root) / "reports"
            reports_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(reports_dir / f"elliott_report_{ts}.html")

        html = HTMLRenderer.render(data)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")

        return str(out)

    def generate_json(self, output_path: str = None) -> str:
        """JSON 형식 보고서 생성"""
        data = self.collect()

        if output_path is None:
            reports_dir = Path(self.collector.root) / "reports"
            reports_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(reports_dir / f"elliott_report_{ts}.json")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(asdict(data), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return str(out)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Elliott Wave Expert — Report Generator"
    )
    parser.add_argument(
        "-o", "--output",
        help="출력 파일 경로 (기본: reports/elliott_report_TIMESTAMP.html)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="JSON 형식으로 출력",
    )
    parser.add_argument(
        "--root", default=".",
        help="프로젝트 루트 경로 (기본: 현재 디렉토리)",
    )
    args = parser.parse_args()

    gen = ReportGenerator(project_root=args.root)

    if args.json:
        path = gen.generate_json(args.output)
    else:
        path = gen.generate(args.output)

    print(f"Report generated: {path}")


if __name__ == "__main__":
    main()

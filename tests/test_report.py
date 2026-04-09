"""
report_generator.py 테스트
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from report_generator import (
    ProjectCollector,
    HTMLRenderer,
    ReportGenerator,
    ReportData,
    FileMetrics,
    PatternStatus,
    TestRunResult,
    GitInfo,
)


@pytest.fixture
def collector():
    return ProjectCollector(root=str(PROJECT_ROOT))


@pytest.fixture
def report_data(collector):
    return collector.collect()


class TestProjectCollector:
    """ProjectCollector 데이터 수집 검증"""

    def test_collect_returns_report_data(self, collector):
        data = collector.collect()
        assert isinstance(data, ReportData)

    def test_total_files_positive(self, report_data):
        assert report_data.total_files > 0

    def test_total_lines_positive(self, report_data):
        assert report_data.total_lines > 0

    def test_file_metrics_not_empty(self, report_data):
        assert len(report_data.file_metrics) > 0

    def test_file_metrics_structure(self, report_data):
        for fm in report_data.file_metrics:
            assert isinstance(fm, FileMetrics)
            assert fm.path.endswith(".py")
            assert fm.lines > 0
            assert 0 <= fm.docstring_ratio <= 1.0

    def test_patterns_count(self, report_data):
        assert report_data.patterns_total == 12

    def test_patterns_mostly_implemented(self, report_data):
        # v2.0에서 12/12 구현 완료
        assert report_data.patterns_implemented >= 10

    def test_pattern_structure(self, report_data):
        for p in report_data.patterns:
            assert isinstance(p, PatternStatus)
            assert p.name
            assert p.category in ("motive", "corrective", "other")

    def test_test_result(self, report_data):
        tr = report_data.test_result
        assert isinstance(tr, TestRunResult)
        assert tr.total > 0
        assert tr.passed > 0
        assert tr.failed == 0

    def test_git_log_exists(self, report_data):
        assert len(report_data.git_log) > 0
        for g in report_data.git_log:
            assert isinstance(g, GitInfo)
            assert g.commit_hash
            assert g.message

    def test_quality_score_range(self, report_data):
        assert 0 <= report_data.quality_score <= 100

    def test_version_detected(self, report_data):
        assert report_data.version != "unknown"


class TestHTMLRenderer:
    """HTML 렌더링 검증"""

    def test_render_returns_html(self, report_data):
        html = HTMLRenderer.render(report_data)
        assert "<!DOCTYPE html>" in html
        assert report_data.project_name in html

    def test_render_contains_kpi(self, report_data):
        html = HTMLRenderer.render(report_data)
        assert str(report_data.total_files) in html
        assert f"{report_data.total_lines:,}" in html

    def test_render_contains_patterns(self, report_data):
        html = HTMLRenderer.render(report_data)
        assert "Impulse" in html
        assert "Zigzag" in html
        assert "Triangle" in html

    def test_render_contains_quality_score(self, report_data):
        html = HTMLRenderer.render(report_data)
        assert str(report_data.quality_score) in html
        assert "Quality Score" in html

    def test_render_valid_html_structure(self, report_data):
        html = HTMLRenderer.render(report_data)
        assert html.count("<html") == 1
        assert html.count("</html>") == 1
        assert "<head>" in html
        assert "<body>" in html


class TestReportGenerator:
    """통합 보고서 생성 검증"""

    def test_generate_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "test_report.html")
            gen = ReportGenerator(project_root=str(PROJECT_ROOT))
            result = gen.generate(output)
            assert os.path.exists(result)
            content = Path(result).read_text()
            assert "<!DOCTYPE html>" in content
            assert len(content) > 1000

    def test_generate_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "test_report.json")
            gen = ReportGenerator(project_root=str(PROJECT_ROOT))
            result = gen.generate_json(output)
            assert os.path.exists(result)
            data = json.loads(Path(result).read_text())
            assert data["project_name"] == "Elliott Wave Expert"
            assert data["total_files"] > 0

    def test_generate_auto_path(self):
        gen = ReportGenerator(project_root=str(PROJECT_ROOT))
        result = gen.generate()
        assert os.path.exists(result)
        assert "reports" in result
        # 정리
        os.remove(result)

    def test_data_caching(self):
        gen = ReportGenerator(project_root=str(PROJECT_ROOT))
        data1 = gen.collect()
        data2 = gen.collect()
        assert data1 is data2  # 같은 객체 (캐시)


class TestConsistency:
    """보고서 일관성 검증 — 같은 입력에서 동일 구조 출력"""

    def test_two_reports_same_structure(self):
        gen = ReportGenerator(project_root=str(PROJECT_ROOT))

        with tempfile.TemporaryDirectory() as tmpdir:
            r1 = gen.generate(os.path.join(tmpdir, "r1.html"))
            gen._data = None  # 캐시 초기화
            r2 = gen.generate(os.path.join(tmpdir, "r2.html"))

            h1 = Path(r1).read_text()
            h2 = Path(r2).read_text()

            # 타임스탬프 제외하면 구조 동일
            # KPI 값들이 동일한지 확인
            assert h1.count("kpi-card") == h2.count("kpi-card")
            assert h1.count("pattern-card") == h2.count("pattern-card")
            assert h1.count("<tr>") == h2.count("<tr>")

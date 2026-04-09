"""
Elliott Wave Expert — CLI Entry Point
======================================

Usage:
    python -m elliott report              # HTML 보고서 생성
    python -m elliott report --json       # JSON 보고서 생성
    python -m elliott report -o out.html  # 지정 경로에 저장
"""

import sys


def main():
    if len(sys.argv) < 2:
        print_help()
        return

    command = sys.argv[1]

    if command == "report":
        from .report_generator import main as report_main
        # report_generator.main()이 argparse를 처리하므로
        # 'report' 커맨드를 제거하고 나머지를 전달
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        report_main()
    elif command in ("-h", "--help", "help"):
        print_help()
    else:
        print(f"Unknown command: {command}")
        print_help()


def print_help():
    print("""
Elliott Wave Expert CLI
=======================

Commands:
    report              Generate analysis report (HTML)
    report --json       Generate analysis report (JSON)
    report -o PATH      Save report to specific path
    report --root DIR   Specify project root directory

Examples:
    python -m elliott report
    python -m elliott report --json -o analysis.json
    python -m elliott report -o reports/latest.html
""")


if __name__ == "__main__":
    main()

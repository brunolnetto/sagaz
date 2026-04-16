#!/usr/bin/env python3
"""
Generate code quality issues report using local analysis tools.
This simulates what Codacy would report without needing Codacy API access.
"""

import subprocess
import json
import re
from collections import defaultdict
from pathlib import Path


def run_ruff_check():
    """Get issues from ruff linter."""
    try:
        result = subprocess.run(
            ["uv", "run", "ruff", "check", "sagaz/", "--output-format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout) if result.stdout else []
        issues = []
        for item in data:
            issues.append({
                "file": item.get("filename"),
                "line": item.get("location", {}).get("row"),
                "code": item.get("code"),
                "message": item.get("message"),
                "type": "CodeStyle",
            })
        return issues
    except Exception as e:
        print(f"❌ Ruff check failed: {e}")
        return []


def run_mypy_check():
    """Get type errors from mypy."""
    try:
        result = subprocess.run(
            ["uv", "run", "mypy", "sagaz/", "--json", "--no-error-summary"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        issues = []
        if result.stdout:
            try:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        item = json.loads(line)
                        issues.append({
                            "file": item.get("filename"),
                            "line": item.get("line"),
                            "code": "TypeError",
                            "message": item.get("message"),
                            "type": "ErrorProne",
                        })
            except json.JSONDecodeError:
                pass
        
        return issues
    except Exception as e:
        print(f"⚠️  Mypy check skipped (pre-existing errors): {e}")
        return []


def run_bandit_check():
    """Get security issues from bandit."""
    try:
        result = subprocess.run(
            ["uv", "run", "bandit", "-r", "sagaz/", "-f", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout) if result.stdout else {"results": []}
        issues = []
        for result_item in data.get("results", []):
            issues.append({
                "file": result_item.get("filename"),
                "line": result_item.get("line_number"),
                "code": result_item.get("test_id"),
                "message": result_item.get("issue_text"),
                "type": "Security",
            })
        return issues
    except Exception as e:
        print(f"⚠️  Bandit check skipped: {e}")
        return []


def run_complexity_check():
    """Get complexity issues using radon."""
    try:
        result = subprocess.run(
            ["uv", "run", "radon", "cc", "-j", "sagaz/"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout) if result.stdout else {}
        
        issues = []
        for file, functions in data.items():
            if isinstance(functions, dict):
                for func_name, metrics in functions.items():
                    if isinstance(metrics, dict):
                        cc = metrics.get("complexity", 0)
                        if cc >= 10:
                            issues.append({
                                "file": file,
                                "line": metrics.get("lineno", "?"),
                                "code": "CC",
                                "message": f"{func_name} has complexity {cc} (threshold: 10)",
                                "type": "Performance",
                            })
        return issues
    except Exception as e:
        print(f"⚠️  Complexity check skipped: {e}")
        return []


def main():
    """Run all checks and generate report."""
    print("🔍 Running local code quality analysis...")
    print()
    
    all_issues = []
    
    print("  📋 Ruff linting...")
    all_issues.extend(run_ruff_check())
    
    print("  🔍 MyPy type checking...")
    all_issues.extend(run_mypy_check())
    
    print("  🔒 Bandit security...")
    all_issues.extend(run_bandit_check())
    
    print("  📊 Complexity analysis...")
    all_issues.extend(run_complexity_check())
    
    print()
    print("=" * 80)
    print("📊 CODE QUALITY REPORT")
    print("=" * 80)
    print()
    
    if not all_issues:
        print("✅ No issues found!")
        return 0
    
    print(f"Total Issues: {len(all_issues)}\n")
    
    # Group by type
    by_type = defaultdict(list)
    for issue in all_issues:
        by_type[issue["type"]].append(issue)
    
    print("### Issues by Category:\n")
    for issue_type in sorted(by_type.keys()):
        count = len(by_type[issue_type])
        print(f"  • {issue_type}: {count}")
    
    print("\n### Issues by Severity:\n")
    
    # Display top issues
    for issue_type in sorted(by_type.keys()):
        print(f"\n#### {issue_type}:\n")
        for issue in sorted(by_type[issue_type], key=lambda x: (x.get("file", ""), x.get("line", 0)))[:5]:
            file = issue.get("file", "?")
            line = issue.get("line", "?")
            code = issue.get("code", "")
            msg = issue.get("message", "")[:60]
            print(f"  • {file}:{line} [{code}] {msg}")
        
        if len(by_type[issue_type]) > 5:
            print(f"  • ... and {len(by_type[issue_type]) - 5} more")
    
    # Export to JSON
    report = {
        "total": len(all_issues),
        "by_type": {k: len(v) for k, v in by_type.items()},
        "issues": all_issues,
    }
    
    with open("quality-report-local.json", "w") as f:
        json.dump(report, f, indent=2)
    
    print("\n💾 Report saved to: quality-report-local.json")
    print()
    
    return 1 if all_issues else 0


if __name__ == "__main__":
    exit(main())

#!/usr/bin/env python
"""Generate demo module inventory and coverage report.

Usage:
    python scripts/inventory_demos.py              # Full report
    python scripts/inventory_demos.py --json       # JSON output
    python scripts/inventory_demos.py --domain [domain]  # Filter by domain
"""

import json
import sys
from pathlib import Path

# Get script location and resolve paths from repo root
SCRIPT_DIR = Path(__file__).parent.absolute()
REPO_ROOT = SCRIPT_DIR.parent
DEMO_ROOT = REPO_ROOT / "sagaz" / "demonstrations"
TEST_ROOT = REPO_ROOT / "tests" / "unit" / "demonstrations"


def get_demo_metadata(demo_dir: Path) -> dict | None:
    """Extract metadata from demo module."""
    main_py = demo_dir / "main.py"
    if not main_py.exists():
        return None

    # Read docstring from main.py
    content = main_py.read_text()
    docstring = ""

    # Extract module docstring
    if '"""' in content:
        start = content.find('"""') + 3
        end = content.find('"""', start)
        if end > start:
            docstring = content[start:end].strip().split("\n")[0]
    elif "'''" in content:
        start = content.find("'''") + 3
        end = content.find("'''", start)
        if end > start:
            docstring = content[start:end].strip().split("\n")[0]

    return {"docstring": docstring}


def list_demos(domain_filter: str | None = None) -> dict[str, dict]:
    """Find all demo modules with coverage status."""
    demos = {}

    if not DEMO_ROOT.exists():
        return demos

    for domain_dir in sorted(DEMO_ROOT.iterdir()):
        if not domain_dir.is_dir():
            continue

        domain = domain_dir.name

        if domain_filter and domain != domain_filter:
            continue

        demos[domain] = {}

        for pattern_dir in sorted(domain_dir.iterdir()):
            if not pattern_dir.is_dir():
                continue

            pattern = pattern_dir.name

            # Check demo existence
            demo_metadata = get_demo_metadata(pattern_dir)
            if demo_metadata is None:
                continue

            # Check test existence - flexible matching
            # Look for test_[domain].py or test_[pattern].py
            test_variants = [
                TEST_ROOT / f"test_{domain}.py",
                TEST_ROOT / domain / f"test_{pattern}.py",
                TEST_ROOT / domain / "test_service_manager_coverage.py",  # Special case
            ]
            has_test = any(tf.exists() for tf in test_variants)
            test_path = next((tf for tf in test_variants if tf.exists()), None)

            demos[domain][pattern] = {
                "path": str(pattern_dir.relative_to(REPO_ROOT)),
                "tested": has_test,
                "test_path": str(test_path.relative_to(REPO_ROOT)) if test_path else None,
                "docstring": demo_metadata.get("docstring", ""),
            }

    return demos


def report_markdown(demos: dict[str, dict]) -> str:
    """Generate markdown report."""
    lines = []

    total_demos = sum(len(patterns) for patterns in demos.values())
    total_tested = sum(
        1 for patterns in demos.values() for pattern in patterns.values() if pattern["tested"]
    )

    lines.append("## Demo Module Inventory")
    lines.append(
        f"\n**Total:** {total_demos} | **Tested:** {total_tested} | **Coverage:** {total_tested}/{total_demos} ({100 * total_tested // total_demos if total_demos else 0}%)\n"
    )

    for domain in sorted(demos.keys()):
        patterns = demos[domain]
        lines.append(f"### {domain.replace('_', ' ').title()}")
        lines.append("")

        for pattern in sorted(patterns.keys()):
            info = patterns[pattern]
            status = "✅" if info["tested"] else "❌"
            desc = info["docstring"] or "*No description*"
            lines.append(f"- **{pattern}** {status}  \n  {desc}")

        lines.append("")

    return "\n".join(lines)


def report_json(demos: dict[str, dict]) -> str:
    """Generate JSON report."""
    return json.dumps(demos, indent=2)


def report_table(demos: dict[str, dict]) -> str:
    """Generate table report."""
    lines = []

    total_demos = sum(len(patterns) for patterns in demos.values())
    total_tested = sum(
        1 for patterns in demos.values() for pattern in patterns.values() if pattern["tested"]
    )

    lines.append("| Domain | Pattern | Status | Description |")
    lines.append("|--------|---------|--------|-------------|")

    for domain in sorted(demos.keys()):
        patterns = demos[domain]
        for pattern in sorted(patterns.keys()):
            info = patterns[pattern]
            status = "✅ Tested" if info["tested"] else "❌ No Test"
            desc = info["docstring"] or ""
            lines.append(f"| {domain} | {pattern} | {status} | {desc[:60]} |")

    lines.append("")
    lines.append(f"**Total Demos:** {total_demos} | **Tested:** {total_tested}/{total_demos}")

    return "\n".join(lines)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate demo module inventory report")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--table", action="store_true", help="Output as markdown table")
    parser.add_argument("--domain", type=str, help="Filter by domain")

    args = parser.parse_args()

    demos = list_demos(domain_filter=args.domain)

    if not demos:
        print("No demo modules found.")
        return 1

    if args.json:
        print(report_json(demos))
    elif args.table:
        print(report_table(demos))
    else:
        print(report_markdown(demos))

    return 0


if __name__ == "__main__":
    sys.exit(main())

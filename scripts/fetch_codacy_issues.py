#!/usr/bin/env python3
"""
Fetch and analyze Codacy issues for the sagaz repository.

Usage:
    python3 fetch_codacy_issues.py [--token TOKEN] [--severity LEVEL] [--type TYPE]

Environment:
    CODACY_PROJECT_TOKEN - Codacy API token (required if --token not provided)

Example:
    export CODACY_PROJECT_TOKEN=your-token-here
    python3 fetch_codacy_issues.py --severity Error
"""

import os
import sys
import json
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from collections import defaultdict


class CodacyAnalyzer:
    """Fetch and analyze Codacy issues."""

    BASE_URL = "https://api.codacy.com/api/v3/organizations/gh/brunolnetto/repositories/sagaz"

    def __init__(self, token: str):
        """Initialize with Codacy API token."""
        if not token:
            raise ValueError("CODACY_PROJECT_TOKEN is required")
        self.token = token

    def fetch_issues(self, severity: str = None, subcategory: str = None, limit: int = 100) -> dict:
        """Fetch issues from Codacy API."""
        params = f"limit={limit}"

        if severity and severity != "all":
            params += f"&severity={severity}"

        if subcategory and subcategory != "all":
            params += f"&subcategory={subcategory}"

        url = f"{self.BASE_URL}/issues?{params}"

        print(f"📡 Fetching from: {url}")

        request = Request(url)
        request.add_header("api-token", self.token)
        request.add_header("Content-Type", "application/json")

        try:
            with urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())
                return data
        except URLError as e:
            print(f"❌ API Error: {e.reason}")
            sys.exit(1)

    def group_issues(self, issues: list) -> dict:
        """Group issues by file and subcategory."""
        grouped = defaultdict(lambda: defaultdict(list))

        for issue in issues:
            file = issue.get("filename", "unknown")
            subcat = issue.get("subcategory", "Other")
            grouped[file][subcat].append(issue)

        return grouped

    def print_summary(self, data: dict):
        """Print summary of issues."""
        issues = data.get("issues", [])

        if not issues:
            print("✅ No issues found!")
            return

        print(f"\n📊 Codacy Analysis Report")
        print(f"Total Issues: {len(issues)}\n")

        # Count by severity
        by_severity = defaultdict(int)
        for issue in issues:
            severity = issue.get("severity", "Info")
            by_severity[severity] += 1

        print("Severity Breakdown:")
        for severity in ["Error", "Warning", "Info"]:
            count = by_severity.get(severity, 0)
            if count > 0:
                print(f"  • {severity}: {count}")

        # Count by type
        by_type = defaultdict(int)
        for issue in issues:
            subcat = issue.get("subcategory", "Other")
            by_type[subcat] += 1

        print("\nIssue Types:")
        for subcat in sorted(by_type.keys()):
            print(f"  • {subcat}: {by_type[subcat]}")

        # Group by file
        grouped = self.group_issues(issues)

        print("\n### Issues by File (Top Issues):\n")

        for file in sorted(grouped.keys())[:10]:
            file_issues = []
            for subcat in sorted(grouped[file].keys()):
                file_issues.extend(grouped[file][subcat])

            print(f"**{file}** ({len(file_issues)} issues)")

            for issue in file_issues[:3]:
                line = issue.get("line", "?")
                severity = issue.get("severity", "Info")
                message = issue.get("message", "No description")[:70]
                print(f"  - Line {line} [{severity}] {message}")

            if len(file_issues) > 3:
                print(f"  - ... and {len(file_issues) - 3} more")

            print()

    def export_json(self, data: dict, output_file: str = "codacy-issues.json"):
        """Export issues to JSON file."""
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"💾 Issues exported to: {output_file}")

    def export_csv(self, data: dict, output_file: str = "codacy-issues.csv"):
        """Export issues to CSV file."""
        import csv

        issues = data.get("issues", [])

        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "filename",
                    "line",
                    "severity",
                    "subcategory",
                    "message",
                    "id",
                ],
            )
            writer.writeheader()

            for issue in issues:
                writer.writerow(
                    {
                        "filename": issue.get("filename", ""),
                        "line": issue.get("line", ""),
                        "severity": issue.get("severity", ""),
                        "subcategory": issue.get("subcategory", ""),
                        "message": issue.get("message", ""),
                        "id": issue.get("id", ""),
                    }
                )

        print(f"📋 Issues exported to: {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch Codacy issues for brunolnetto/sagaz repository"
    )
    parser.add_argument(
        "--token", help="Codacy API token (defaults to CODACY_PROJECT_TOKEN env var)"
    )
    parser.add_argument(
        "--severity",
        choices=["all", "Error", "Warning", "Info"],
        default="all",
        help="Filter by severity",
    )
    parser.add_argument(
        "--subcategory",
        choices=[
            "all",
            "CodeSmell",
            "ErrorProne",
            "Performance",
            "CodeStyle",
            "Suggestion",
        ],
        default="all",
        help="Filter by issue type",
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Maximum number of issues to fetch"
    )
    parser.add_argument(
        "--export-json", action="store_true", help="Export to JSON file"
    )
    parser.add_argument(
        "--export-csv", action="store_true", help="Export to CSV file"
    )

    args = parser.parse_args()

    # Get token from args or environment
    token = args.token or os.getenv("CODACY_PROJECT_TOKEN")

    if not token:
        print("❌ Error: CODACY_PROJECT_TOKEN not provided")
        print("   Set with: export CODACY_PROJECT_TOKEN=your-token-here")
        print("   Or pass:  --token your-token-here")
        sys.exit(1)

    # Create analyzer and fetch issues
    analyzer = CodacyAnalyzer(token)

    print("🔍 Fetching Codacy issues...\n")

    data = analyzer.fetch_issues(
        severity=args.severity,
        subcategory=args.subcategory,
        limit=args.limit,
    )

    # Print summary
    analyzer.print_summary(data)

    # Export if requested
    if args.export_json:
        analyzer.export_json(data)

    if args.export_csv:
        analyzer.export_csv(data)

    # Return exit code based on issues
    issues = data.get("issues", [])
    errors = [i for i in issues if i.get("severity") == "Error"]

    if errors:
        print(f"\n⚠️  Found {len(errors)} error(s)")
        return 1
    else:
        print("\n✅ No critical errors")
        return 0


if __name__ == "__main__":
    sys.exit(main())

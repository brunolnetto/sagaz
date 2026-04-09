module.exports = {
  extends: ["@commitlint/config-conventional"],
  ignores: [(commit) => /^Merge (pull request|branch)/.test(commit)],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",
        "fix",
        "docs",
        "refactor",
        "test",
        "perf",
        "build",
        "ci",
        "chore",
        "revert",
      ],
    ],
    "scope-enum": [
      2,
      "always",
      [
        "saga",      // core saga engine
        "dag",       // DAG / parallel execution
        "outbox",    // transactional outbox
        "storage",   // storage backends
        "strategies",// failure strategies
        "monitoring",// metrics, logging, tracing
        "cli",       // command-line tools
        "execution", // execution engine
        "triggers",  // event-driven triggers
        "visualization", // mermaid / diagram generation
        "integrations",  // framework integrations (FastAPI, Flask)
        "sagaz",     // general / package-level
        "docs",      // documentation
        "ci",        // CI/CD workflows
        "deps",      // dependency management
        "tests",     // test infrastructure / fixtures
      ],
    ],
    "subject-case": [2, "never", ["sentence-case", "start-case", "pascal-case"]],
    "subject-full-stop": [2, "never", "."],
    "scope-empty": [2, "never"],
    "type-empty": [2, "never"],
  },
};

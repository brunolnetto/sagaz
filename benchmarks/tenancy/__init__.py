"""Multi-tenancy overhead benchmark (ADR-020, issue #54).

Runs the same saga workload as a single tenant and spread over many tenants,
on each storage backend, and reports throughput, latency percentiles and the
overhead of multi-tenancy. See ``docs/benchmarks/tenancy-overhead.md``.
"""

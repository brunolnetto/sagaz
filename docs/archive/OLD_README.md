# Saga Pattern - Distributed Transactions with Compensation

Production-ready implementation of the Saga pattern with DAG support for parallel execution.

## Features

- ✅ Sequential and parallel (DAG) execution
- ✅ Automatic compensation on failure
- ✅ Three failure strategies (FAIL_FAST, WAIT_ALL, FAIL_FAST_WITH_GRACE)
- ✅ Retry logic with exponential backoff
- ✅ Timeout protection
- ✅ Idempotency support
- ✅ Comprehensive monitoring
- ✅ Type-safe with full type hints

## Quick Start

```python
from saga import DAGSaga, SagaContext

class MyBusinessSaga(DAGSaga):
    async def build(self):
        await self.add_dag_step(
            "step1",
            action=my_action,
            compensation=my_compensation
        )

saga = MyBusinessSaga()
await saga.build()
result = await saga.execute()
```

## Documentation

- [Getting Started](docs/getting_started.md)
- [Architecture](docs/architecture.md)
- [DAG Pattern](docs/dag_pattern.md)
- [Best Practices](docs/best_practices.md)

## License

MIT
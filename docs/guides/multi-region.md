# Multi-region sagas

A saga can run some of its steps in another region: close to the data they use, or
because the law requires that data to stay there (GDPR in the EU, MLPS in China,
DPDP in India). The saga itself still has one coordinator, the process that runs it.
Steps declared for a region are sent to that region's workers over its message bus,
and the coordinator waits for the result. Design:
[ADR-034](../architecture/adr/adr-034-multi-region-coordination.md); issue #59.

**Data residency comes first.** When a region is down, its steps only move to a
healthy region of the **same jurisdiction**. If there is none, the step fails and
the saga compensates. Nothing moves to another jurisdiction unless an operator
forces it.

## Declaring where a step runs

```python
from sagaz import Saga, action, compensate


class CheckoutSaga(Saga):
    saga_name = "checkout"

    @action("reserve")                                    # runs here
    async def reserve(self, ctx):
        return {"reservation_id": await stock.reserve(ctx["sku"])}

    @action("charge", depends_on=["reserve"], region="eu-west-1")
    async def charge(self, ctx):                           # runs in eu-west-1
        return {"charge_id": await eu_payments.charge(ctx["card_token"], ctx["amount"])}

    @compensate("charge")                                  # also runs in eu-west-1
    async def refund(self, ctx):
        await eu_payments.refund(ctx["charge_id"])
```

With `add_step()`, pass `region="eu-west-1"`. A step without `region` runs locally,
as before. A step declared for the home region also runs locally.

## Configuring regions

Each region has a name, a **jurisdiction**, a message bus and a failover priority
(lower first):

```yaml
# sagaz.yaml
regions:
  home: us-east-1        # the region this process runs in
  stale_after: 3         # seconds without heartbeats before a region is down
  members:
    - {name: us-east-1,    jurisdiction: US, bus: "redis://us-redis:6379"}
    - {name: eu-west-1,    jurisdiction: EU, bus: "redis://eu-redis:6379"}
    - {name: eu-central-1, jurisdiction: EU, bus: "redis://eu2-redis:6379", priority: 1}
```

`SagaConfig.from_file("sagaz.yaml")` builds the coordinator into `SagaConfig.regions`.
In code:

```python
from sagaz import SagaConfig, configure
from sagaz.core.regions import MultiRegionCoordinator, Region

coordinator = MultiRegionCoordinator.from_regions(
    [Region("us-east-1", "US", "redis://us-redis:6379"),
     Region("eu-west-1", "EU", "redis://eu-redis:6379"),
     Region("eu-central-1", "EU", "redis://eu2-redis:6379", priority=1)],
    home="us-east-1",
)
configure(SagaConfig(regions=coordinator))
```

Buses: `redis://` (Redis Streams), `kafka://host:port`, `amqp://` (RabbitMQ), and
`memory://` for tests. A saga whose steps declare a region fails before it starts if
no coordinator is configured or a region is unknown.

## Running workers

In each region, and in each region that may stand in for it, run workers that know
the saga's steps:

```python
from sagaz.core.regions import RegionalWorker, bus_from_url

bus = bus_from_url("redis://eu-redis:6379", group="sagaz-worker-eu-west-1", member="eu-w1")
await bus.start()
worker = RegionalWorker("eu-west-1", bus)
worker.serve(CheckoutSaga)            # every step of the saga that declares a region
await worker.start()
```

For steps added with `add_step()`, use `worker.register("checkout", "charge", action,
compensation)`. Replicas of a worker share the consumer group (`group`), so each
request runs once. A worker publishes a heartbeat every second.

Steps receive a **copy** of the saga context and return their result, which joins the
context in the coordinator. Both cross the network, and the result is stored with the
saga in the home region. To keep personal data in its region, pass and return
references (ids, tokens), not the data itself.

## Failover

A region is down when no heartbeat has arrived for `stale_after` seconds (default 3).
Its steps then go to the healthy region of the same jurisdiction with the lowest
priority. With the defaults, new steps reach the stand-in within about 3 seconds, and
in under 5 in the integration test. When heartbeats come back, steps go back to the
region. The stand-in's workers must reach the same data, for example a replica in the
same jurisdiction.

| Situation | What happens |
|---|---|
| Region healthy | Steps run there |
| Region down, a same-jurisdiction region healthy | Steps run in the stand-in (`sagaz_region_failover_total{reason="automatic"}`) |
| Region down, no stand-in | `RegionUnavailableError`: the step fails, the saga compensates |
| A request is in flight when the region dies | The step times out (its `timeout_seconds`) and the saga compensates. Steps are never retried elsewhere, because the action may have run |
| A compensation's region is down | It goes to the stand-in the same way. If there is none, it fails and the saga ends `failed` |

## Operating regions

```bash
sagaz region list                      # regions, jurisdictions, workers heard, up/down
sagaz region failover --from eu-west-1 --to eu-central-1     # asks for confirmation
sagaz region failover --from eu-west-1 --restore
sagaz region failover --from eu-west-1 --to us-east-1 --force   # crosses jurisdictions
```

`failover` publishes a command on every reachable region bus, and every running
coordinator applies it until `--restore`. A target in another jurisdiction is refused
unless you pass `--force`, which moves the region's steps, and their data, out of its
jurisdiction.

## Metrics

| Metric | Labels |
|---|---|
| `sagaz_cross_region_latency_seconds` | `from_region`, `to_region`, `kind` (`action`, `compensation`) |
| `sagaz_region_failover_total` | `from_region`, `to_region`, `reason` (`automatic`, `manual`) |

## Cost for single-region sagas

Steps without `region` take the same path as before, plus one check per run and one
function call per step. That is about 1 µs on a 3-step run of about 250 µs, or 0.4%
(`tests/integration/test_multi_region_performance.py`, marker `performance`).

## Limits

- The lower-level `sagaz.core.saga.Saga` does not route steps to regions.
- Each coordinator process has its own consumer group on every region bus, so it
  sees replies and heartbeats. Clean up groups of decommissioned processes on your
  broker.
- There is no conflict resolution between regions: one coordinator owns each saga, so
  there are no concurrent writers to reconcile (see ADR-034).

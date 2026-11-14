# Local development with the `sagaz` CLI

Create a project, start its storage and broker in Docker Compose, and inspect running
sagas without writing any infrastructure configuration yourself.

Requirements: Python 3.11+, `pip install sagaz`, and Docker with the Compose plugin
(`docker compose`).

## 1. Create the project and its local environment

```bash
sagaz init --local
```

`sagaz init` asks for the project name, its directory and an optional example saga, then
writes `sagaz.yaml`, `profiles.yaml`, `sagas/`, `tests/`, `README.md` and `.gitignore`.

With `--local` it continues with the local environment questions and writes
`docker-compose.yaml` **inside the project directory**:

| Question | Choices (default first) |
|----------|-------------------------|
| Saga (OLTP) storage | PostgreSQL, in-memory, SQLite |
| Message broker | Redis, Kafka, RabbitMQ |
| Outbox storage | same as the saga storage, or separate |
| Metrics / tracing / logs | Prometheus + Grafana, Jaeger, Loki + Promtail (each on by default; adds `monitoring/`) |
| In-memory mode | runs without external storage |

A configuration summary is printed before the files are written. Without `--local`, only
the project is created; you can add the environment later with `sagaz setup` from the
project directory, which also offers self-hosted, Kubernetes and hybrid modes.

## 2. Start, check and stop

```bash
cd my-project
sagaz dev          # docker compose up, streaming logs in the foreground
sagaz dev -d       # start in the background
sagaz status       # health of each service, green ● running / red ○ otherwise
sagaz stop         # docker compose down
```

`sagaz dev` and `sagaz stop` need the `docker-compose.yaml` created by `sagaz init --local`
(or `sagaz setup`) in the current directory.

## 3. Logs

```bash
sagaz logs                 # all services
sagaz logs -f              # follow
sagaz logs -s worker       # one service
sagaz logs <saga-id>       # only lines mentioning that saga
```

## 4. Visualize a saga

```bash
sagaz visualize myapp.sagas:OrderSaga                       # Mermaid to stdout
sagaz visualize myapp.sagas:OrderSaga --format markdown     # fenced Mermaid block
sagaz visualize myapp.sagas:OrderSaga --format url          # mermaid.live link
sagaz visualize myapp.sagas:OrderSaga --output diagram.md
```

For a live view of running sagas, see the monitor:
[docs/monitoring/visualization-ui.md](../monitoring/visualization-ui.md).

Every command documents its options and examples under `--help`, for example
`sagaz init --help`.

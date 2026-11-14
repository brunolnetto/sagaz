"""``sagaz monitor`` command: web visualization dashboard or Grafana."""

import click

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})  # nosec B104 - used to detect wildcard binds


def _is_loopback(host: str) -> bool:
    return host.lower() in _LOOPBACK_HOSTS


def _url_host(host: str) -> str:
    """Bracket a bare IPv6 address for use inside an http:// URL."""
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


@click.command()
@click.option(
    "--ui",
    type=click.Choice(["web", "grafana"], case_sensitive=False),
    default="web",
    show_default=True,
    help="Dashboard backend.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Web dashboard bind address.",
)
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    default=7070,
    show_default=True,
    help="Web dashboard port.",
)
@click.option(
    "--advertise-host",
    default=None,
    metavar="HOST",
    help=(
        "Address advertised to Saga workers in export instructions. "
        "Defaults to the bind address (127.0.0.1 for wildcards)."
    ),
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Start the server without opening a browser.",
)
@click.option(
    "--storage-url",
    envvar="SAGAZ_STORAGE_URL",
    default=None,
    metavar="URL",
    help=(
        "Saga storage the /api/v1/analytics/* reports read from (read-only), e.g. "
        "postgresql://... or sqlite:///sagas.db. Requires sagaz[analytics]. "
        "Env: SAGAZ_STORAGE_URL."
    ),
)
@click.option(
    "--unsafe-expose",
    is_flag=True,
    help=(
        "Required when binding to a non-loopback address. Read endpoints remain unauthenticated."
    ),
)
def monitor_cmd(
    ui: str,
    host: str,
    port: int,
    advertise_host: str | None,
    no_browser: bool,
    unsafe_expose: bool,
    storage_url: str | None = None,
) -> None:
    """Start the Saga visualization dashboard or open Grafana."""
    import os
    import secrets

    if ui == "grafana":
        grafana_url = "http://localhost:3000"
        click.echo(f"Grafana dashboard: {grafana_url}")
        _maybe_open_browser(grafana_url, no_browser, announce=False)
        return

    _require_safe_bind(host, unsafe_expose)

    # Import here so the core CLI remains usable without visualization extras.
    from sagaz.visualization.server import run_server

    configured_token = os.environ.get("SAGAZ_VISUALIZATION_TOKEN")
    token = configured_token or secrets.token_urlsafe(32)
    dashboard_url = f"http://{_browser_host(host)}:{port}/"

    if not _is_loopback(host):
        click.echo(
            "WARNING: Read endpoints (dashboard, SSE stream, REST) are unauthenticated. "
            "Do not expose this server to untrusted networks without additional controls."
        )

    click.echo(f"Sagaz visualization dashboard: {dashboard_url}")

    if configured_token:
        click.echo(
            "SAGAZ_VISUALIZATION_TOKEN is already configured. "
            "Saga workers must inherit the same token."
        )
    else:
        _echo_worker_setup(host, port, advertise_host, token)

    _maybe_open_browser(dashboard_url, no_browser)
    run_server(host=host, port=port, event_token=token, analytics_storage_url=storage_url)


def _require_safe_bind(host: str, unsafe_expose: bool) -> None:
    if not _is_loopback(host) and not unsafe_expose:
        msg = (
            f"Binding to {host!r} exposes the dashboard beyond loopback. "
            "Read endpoints (dashboard, SSE stream, REST) are unauthenticated. "
            "Pass --unsafe-expose to acknowledge this limitation."
        )
        raise click.UsageError(msg)


def _browser_host(host: str) -> str:
    """Browser address: loopback for wildcard binds, bracketed for bare IPv6."""
    return "127.0.0.1" if host in _WILDCARD_HOSTS else _url_host(host)


def _worker_host(host: str, advertise_host: str | None) -> str:
    """Address advertised to Saga workers (distinct from the browser address)."""
    if advertise_host is not None:
        return _url_host(advertise_host)
    return _browser_host(host)


def _echo_worker_setup(host: str, port: int, advertise_host: str | None, token: str) -> None:
    if host in _WILDCARD_HOSTS and advertise_host is None:
        click.echo(
            "NOTE: Server binds to all interfaces. "
            "Workers on other hosts should use --advertise-host to override the URL below."
        )
    click.echo("Generated an event-ingestion token for this monitor process.")
    click.echo("Configure Saga workers with:")
    click.echo(f"export SAGAZ_VISUALIZATION_URL=http://{_worker_host(host, advertise_host)}:{port}")
    click.echo(f"export SAGAZ_VISUALIZATION_TOKEN={token}")
    click.echo("Then register VisualizationSagaListener.from_env() on each Saga class.")


def _maybe_open_browser(url: str, no_browser: bool, *, announce: bool = True) -> None:
    import webbrowser

    if not no_browser:
        webbrowser.open(url)
    elif announce:
        click.echo("Browser launch disabled.")

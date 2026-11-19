#!/usr/bin/env bash
# Local Fluss + Flink lakehouse for sagaz analytics (ADR-013, #482). No Docker:
# pinned binary distributions on a JDK (17 recommended), with the Iceberg
# catalog in PostgreSQL (JDBC) and the warehouse on local disk.
#
#   scripts/lakehouse/lakehouse.sh fetch     # download and verify (once)
#   scripts/lakehouse/lakehouse.sh start     # Fluss local cluster + Flink cluster
#   scripts/lakehouse/lakehouse.sh tiering   # submit the Fluss -> Iceberg tiering job
#   scripts/lakehouse/lakehouse.sh sql       # Flink SQL client with both catalogs
#   scripts/lakehouse/lakehouse.sh status | stop
#   scripts/lakehouse/lakehouse.sh reset     # stop, then delete all data and the catalog
#
# Settings (environment):
#   LAKEHOUSE_HOME     where everything is installed  (~/.cache/sagaz/lakehouse)
#   ICEBERG_JDBC_URL   catalog database               (jdbc:postgresql://localhost:5432/iceberg)
#   ICEBERG_JDBC_USER / ICEBERG_JDBC_PASSWORD         (postgres / empty)
#   ICEBERG_WAREHOUSE  table files                    (file://$LAKEHOUSE_HOME/warehouse)
#   FLUSS_BOOTSTRAP    the coordinator                (localhost:9123)
#   FLINK_REST_PORT    Flink UI and REST API          (8083)
set -euo pipefail

FLUSS_VERSION=1.0.0
FLINK_VERSION=1.20.5
FLINK_MINOR=1.20
ICEBERG_VERSION=1.10.1
HADOOP_APACHE_VERSION=3.3.5-2
PG_JDBC_VERSION=42.7.14

LAKEHOUSE_HOME=${LAKEHOUSE_HOME:-$HOME/.cache/sagaz/lakehouse}
ICEBERG_JDBC_URL=${ICEBERG_JDBC_URL:-jdbc:postgresql://localhost:5432/iceberg}
ICEBERG_JDBC_USER=${ICEBERG_JDBC_USER:-postgres}
ICEBERG_JDBC_PASSWORD=${ICEBERG_JDBC_PASSWORD:-}
ICEBERG_WAREHOUSE=${ICEBERG_WAREHOUSE:-file://$LAKEHOUSE_HOME/warehouse}
FLUSS_BOOTSTRAP=${FLUSS_BOOTSTRAP:-localhost:9123}
FLINK_REST_PORT=${FLINK_REST_PORT:-8083}

FLUSS_HOME=$LAKEHOUSE_HOME/fluss-$FLUSS_VERSION
FLINK_HOME=$LAKEHOUSE_HOME/flink-$FLINK_VERSION
JARS=$LAKEHOUSE_HOME/jars
MAVEN=https://repo1.maven.org/maven2

log() { printf '[lakehouse] %s\n' "$*" >&2; }
die() { log "$*"; exit 1; }

# -- fetch ---------------------------------------------------------------------

download() { # url file checksum-url algorithm
    local url=$1 file=$2 sum_url=$3 algo=$4
    if [[ ! -s $file ]]; then
        log "downloading $(basename "$file")"
        curl -fSL --retry 3 -C - -o "$file.part" "$url"  # resumes a partial download
        mv "$file.part" "$file"
    fi
    local expected actual
    expected=$(curl -fsSL --retry 3 "$sum_url" | awk '{print $1}')
    actual=$("${algo}sum" "$file" | awk '{print $1}')
    [[ $expected == "$actual" ]] || { rm -f "$file"; die "checksum mismatch: $file"; }
}

maven_jar() { # group-path artifact version
    local path=$1 artifact=$2 version=$3
    local url=$MAVEN/$path/$artifact/$version/$artifact-$version.jar
    download "$url" "$JARS/$artifact-$version.jar" "$url.sha1" sha1
}

fetch() {
    mkdir -p "$LAKEHOUSE_HOME" "$JARS"
    local fluss_tgz=$LAKEHOUSE_HOME/fluss-$FLUSS_VERSION-bin.tgz
    local fluss_url=https://downloads.apache.org/fluss/fluss-$FLUSS_VERSION/fluss-$FLUSS_VERSION-bin.tgz
    download "$fluss_url" "$fluss_tgz" "$fluss_url.sha512" sha512
    [[ -d $FLUSS_HOME ]] || tar -xzf "$fluss_tgz" -C "$LAKEHOUSE_HOME"

    local flink_tgz=$LAKEHOUSE_HOME/flink-$FLINK_VERSION-bin-scala_2.12.tgz
    local flink_url=https://archive.apache.org/dist/flink/flink-$FLINK_VERSION/flink-$FLINK_VERSION-bin-scala_2.12.tgz
    download "$flink_url" "$flink_tgz" "$flink_url.sha512" sha512
    [[ -d $FLINK_HOME ]] || tar -xzf "$flink_tgz" -C "$LAKEHOUSE_HOME"

    maven_jar org/apache/fluss "fluss-flink-$FLINK_MINOR" "$FLUSS_VERSION"
    maven_jar org/apache/fluss fluss-lake-iceberg "$FLUSS_VERSION"
    maven_jar org/apache/fluss fluss-flink-tiering "$FLUSS_VERSION"
    maven_jar org/apache/iceberg "iceberg-flink-runtime-$FLINK_MINOR" "$ICEBERG_VERSION"
    maven_jar io/trino/hadoop hadoop-apache "$HADOOP_APACHE_VERSION"
    maven_jar org/postgresql postgresql "$PG_JDBC_VERSION"
    log "fetched into $LAKEHOUSE_HOME"
}

# -- configure -----------------------------------------------------------------

datalake_options() { # one "key value" per line, the server.yaml / tiering options
    cat <<EOF
datalake.format iceberg
datalake.iceberg.catalog-impl org.apache.iceberg.jdbc.JdbcCatalog
datalake.iceberg.name iceberg
datalake.iceberg.uri $ICEBERG_JDBC_URL
datalake.iceberg.jdbc.user $ICEBERG_JDBC_USER
datalake.iceberg.jdbc.password $ICEBERG_JDBC_PASSWORD
datalake.iceberg.warehouse $ICEBERG_WAREHOUSE
EOF
}

managed_block() { # file, then the block on stdin: replace the previous one
    local file=$1 begin="# >>> sagaz lakehouse" end="# <<< sagaz lakehouse"
    sed -i "/^$begin/,/^$end/d" "$file"
    { echo "$begin"; cat; echo "$end"; } >>"$file"
}

configure() {
    [[ -d $FLUSS_HOME && -d $FLINK_HOME ]] || die "run '$0 fetch' first"
    mkdir -p "$FLUSS_HOME/plugins/iceberg" "$FLUSS_HOME/log" "$FLINK_HOME/log" "$LAKEHOUSE_HOME/data"
    [[ $ICEBERG_WAREHOUSE != file://* ]] || mkdir -p "${ICEBERG_WAREHOUSE#file://}"
    # The coordinator creates the Iceberg table of a datalake-enabled Fluss table.
    cp "$JARS/hadoop-apache-$HADOOP_APACHE_VERSION.jar" "$JARS/postgresql-$PG_JDBC_VERSION.jar" \
        "$FLUSS_HOME/plugins/iceberg/"
    {
        echo "datalake.enabled: true"
        # Fluss reads "key: value" literally: no quotes.
        datalake_options | while read -r key value; do
            [[ -z $value ]] || echo "$key: $value"  # an empty value is not a valid line
        done
    } | managed_block "$FLUSS_HOME/conf/server.yaml"
    # Keep the data out of /tmp, the distribution's default.
    sed -i -e "s|^data.dir:.*|data.dir: $LAKEHOUSE_HOME/data/fluss|" \
        -e "s|^remote.data.dir:.*|remote.data.dir: $LAKEHOUSE_HOME/data/fluss-remote|" \
        "$FLUSS_HOME/conf/server.yaml"
    sed -i "s|^dataDir=.*|dataDir=$LAKEHOUSE_HOME/data/zookeeper|" "$FLUSS_HOME/conf/zookeeper.properties"

    cp "$JARS/fluss-flink-$FLINK_MINOR-$FLUSS_VERSION.jar" \
        "$JARS/fluss-lake-iceberg-$FLUSS_VERSION.jar" \
        "$JARS/iceberg-flink-runtime-$FLINK_MINOR-$ICEBERG_VERSION.jar" \
        "$JARS/hadoop-apache-$HADOOP_APACHE_VERSION.jar" \
        "$JARS/postgresql-$PG_JDBC_VERSION.jar" "$FLINK_HOME/lib/"
    # config.yaml is nested YAML: edit the keys it has, add the ones it lacks.
    local flink_conf=$FLINK_HOME/conf/config.yaml
    sed -i -e "s|^  numberOfTaskSlots:.*|  numberOfTaskSlots: 4|" "$flink_conf"
    sed -i -e "/^rest:/,/^[a-z]/{/^  port:/d}" -e "s|^rest:\$|rest:\n  port: $FLINK_REST_PORT|" \
        "$flink_conf"
    managed_block "$flink_conf" <<EOF
execution:
  checkpointing:
    interval: 10s
EOF
}

ensure_catalog_database() {
    local db=${ICEBERG_JDBC_URL##*/}
    command -v psql >/dev/null || { log "psql not found: create database '$db' yourself"; return; }
    psql_catalog -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
        || psql_catalog -qc "CREATE DATABASE \"$db\""
}

# -- run -----------------------------------------------------------------------

wait_for_port() { # host:port seconds
    local host=${1%%:*} port=${1##*:} deadline=$((SECONDS + $2))
    until (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; do
        ((SECONDS < deadline)) || die "nothing listening on $1"
        sleep 1
    done
}

start() {
    configure
    ensure_catalog_database
    log "starting Fluss"
    "$FLUSS_HOME/bin/local-cluster.sh" start
    wait_for_port "$FLUSS_BOOTSTRAP" 90
    log "starting Flink"
    "$FLINK_HOME/bin/start-cluster.sh"
    wait_for_port "localhost:$FLINK_REST_PORT" 90
    log "Fluss at $FLUSS_BOOTSTRAP, Flink UI at http://localhost:$FLINK_REST_PORT"
}

tiering() {
    local args=(--fluss.bootstrap.servers "$FLUSS_BOOTSTRAP")
    while read -r key value; do
        [[ -z $value ]] || args+=("--$key" "$value")
    done < <(datalake_options)
    "$FLINK_HOME/bin/flink" run -d "$JARS/fluss-flink-tiering-$FLUSS_VERSION.jar" "${args[@]}"
}

sql() {
    local init=$LAKEHOUSE_HOME/sql-init.sql
    cat >"$init" <<EOF
CREATE CATALOG fluss WITH ('type' = 'fluss', 'bootstrap.servers' = '$FLUSS_BOOTSTRAP');
CREATE CATALOG iceberg WITH (  -- the name the JDBC catalog files tables under
  'type' = 'iceberg',
  'catalog-impl' = 'org.apache.iceberg.jdbc.JdbcCatalog',
  'uri' = '$ICEBERG_JDBC_URL',
  'jdbc.user' = '$ICEBERG_JDBC_USER',
  'jdbc.password' = '$ICEBERG_JDBC_PASSWORD',
  'warehouse' = '$ICEBERG_WAREHOUSE'
);
USE CATALOG fluss;
EOF
    "$FLINK_HOME/bin/sql-client.sh" -i "$init" "$@"
}

status() {
    for target in "Fluss $FLUSS_BOOTSTRAP" "Flink localhost:$FLINK_REST_PORT"; do
        set -- $target
        if (exec 3<>"/dev/tcp/${2%%:*}/${2##*:}") 2>/dev/null; then
            log "$1 up ($2)"
        else
            log "$1 down ($2)"
        fi
    done
    [[ ! -x $FLINK_HOME/bin/flink ]] || "$FLINK_HOME/bin/flink" list 2>/dev/null | grep -E "RUNNING|Running" || true
}

stop() {
    [[ ! -x $FLINK_HOME/bin/stop-cluster.sh ]] || "$FLINK_HOME/bin/stop-cluster.sh" || true
    [[ ! -x $FLUSS_HOME/bin/local-cluster.sh ]] || "$FLUSS_HOME/bin/local-cluster.sh" stop || true
}

psql_catalog() { # SQL on the catalog server's postgres database
    local host_port=${ICEBERG_JDBC_URL#jdbc:postgresql://}
    host_port=${host_port%%/*}
    PGPASSWORD=$ICEBERG_JDBC_PASSWORD psql -h "${host_port%%:*}" -p "${host_port##*:}" \
        -U "$ICEBERG_JDBC_USER" -d postgres "$@"
}

reset() {
    stop
    rm -rf "$LAKEHOUSE_HOME/data" "${FLUSS_HOME:?}/log/"* "${FLINK_HOME:?}/log/"*
    [[ $ICEBERG_WAREHOUSE != file://* ]] || rm -rf "${ICEBERG_WAREHOUSE#file://}"
    command -v psql >/dev/null && psql_catalog -qc "DROP DATABASE IF EXISTS \"${ICEBERG_JDBC_URL##*/}\""
    log "reset: data, warehouse and catalog deleted"
}

case ${1:-} in
    fetch) fetch ;;
    start) start ;;
    tiering) tiering ;;
    sql) shift; sql "$@" ;;
    status) status ;;
    stop) stop ;;
    reset) reset ;;
    *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

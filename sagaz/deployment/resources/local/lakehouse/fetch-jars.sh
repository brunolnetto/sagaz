#!/usr/bin/env bash
# JARs the Fluss servers need for Iceberg on S3 with a JDBC catalog (mounted by
# docker-compose.yaml into /opt/fluss/plugins/iceberg). Checksums are verified.
set -euo pipefail
ICEBERG_VERSION=1.10.1
PG_JDBC_VERSION=42.7.14
cd "$(dirname "$0")"
mkdir -p lib
fetch() { # group-path artifact version
    local url=https://repo1.maven.org/maven2/$1/$2/$3/$2-$3.jar file=lib/$2-$3.jar
    [[ -s $file ]] || curl -fsSL --retry 3 -o "$file" "$url"
    [[ $(curl -fsSL --retry 3 "$url.sha1") == "$(sha1sum "$file" | cut -d' ' -f1)" ]] \
        || { rm -f "$file"; echo "checksum mismatch: $file" >&2; exit 1; }
}
fetch org/apache/iceberg iceberg-aws "$ICEBERG_VERSION"
fetch org/apache/iceberg iceberg-aws-bundle "$ICEBERG_VERSION"
fetch org/postgresql postgresql "$PG_JDBC_VERSION"
echo "JARs in $(pwd)/lib"

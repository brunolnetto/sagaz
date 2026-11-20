#!/usr/bin/env bash
# Submits Fluss's lake tiering job (Fluss -> Iceberg) to this Flink cluster.
# Run inside the jobmanager: docker compose exec jobmanager /opt/flink/tiering.sh
set -euo pipefail
exec /opt/flink/bin/flink run -d /opt/flink/opt/fluss-flink-tiering-1.0.0.jar \
    --fluss.bootstrap.servers coordinator-server:9123 \
    --datalake.format iceberg \
    --datalake.iceberg.catalog-impl org.apache.iceberg.jdbc.JdbcCatalog \
    --datalake.iceberg.name iceberg \
    --datalake.iceberg.uri jdbc:postgresql://catalog:5432/iceberg \
    --datalake.iceberg.jdbc.user iceberg \
    --datalake.iceberg.jdbc.password iceberg \
    --datalake.iceberg.warehouse s3://fluss/iceberg \
    --datalake.iceberg.io-impl org.apache.iceberg.aws.s3.S3FileIO \
    --datalake.iceberg.s3.endpoint http://rustfs:9000 \
    --datalake.iceberg.s3.access-key-id rustfsadmin \
    --datalake.iceberg.s3.secret-access-key rustfsadmin \
    --datalake.iceberg.s3.path-style-access true \
    --datalake.iceberg.client.region us-east-1

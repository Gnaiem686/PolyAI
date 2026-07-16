import os
import gzip
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import boto3
import requests
from fastmcp import FastMCP


mcp = FastMCP("polyai-observability")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

DEV_S3_LOGS_BUCKET = os.getenv("DEV_S3_LOGS_BUCKET", "gnaiem-polyai-logs-dev")
PROD_S3_LOGS_BUCKET = os.getenv("PROD_S3_LOGS_BUCKET", "gnaiem-polyai-logs-prod")

DEV_PROMETHEUS_URL = os.getenv("DEV_PROMETHEUS_URL", "http://localhost:9090")
PROD_PROMETHEUS_URL = os.getenv("PROD_PROMETHEUS_URL", "http://localhost:9090")

s3 = boto3.client("s3", region_name=AWS_REGION)


def get_bucket(environment: str) -> str:
    env = environment.lower()
    if env == "dev":
        return DEV_S3_LOGS_BUCKET
    if env == "prod":
        return PROD_S3_LOGS_BUCKET
    raise ValueError("environment must be 'dev' or 'prod'")


def get_prometheus_url(environment: str) -> str:
    env = environment.lower()
    if env == "dev":
        return DEV_PROMETHEUS_URL
    if env == "prod":
        return PROD_PROMETHEUS_URL
    raise ValueError("environment must be 'dev' or 'prod'")


@mcp.tool()
def list_log_services(environment: str = "dev") -> list[str]:
    """
    List services that are shipping logs to S3 for dev or prod.
    """
    bucket = get_bucket(environment)

    response = s3.list_objects_v2(
        Bucket=bucket,
        Prefix="logs/",
        Delimiter="/",
    )

    services = []
    for item in response.get("CommonPrefixes", []):
        prefix = item.get("Prefix", "")
        parts = prefix.strip("/").split("/")
        if len(parts) >= 2:
            services.append(parts[1])

    return sorted(set(services))


@mcp.tool()
def get_service_logs(
    service: str,
    environment: str = "dev",
    minutes: int = 5,
    max_files: int = 10,
) -> str:
    """
    Get recent logs for a service from S3.

    Example services:
    yolo, agent, frontend, img-proc-mcp, prometheus, grafana, node-exporter
    """
    bucket = get_bucket(environment)

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=minutes)

    prefixes = []
    current = start_time
    while current <= now:
        prefixes.append(
            f"logs/{service}/{current.year:04d}/{current.month:02d}/{current.day:02d}/"
        )
        current += timedelta(days=1)

    objects = []

    for prefix in sorted(set(prefixes)):
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        for obj in response.get("Contents", []):
            key = obj["Key"]
            last_modified = obj["LastModified"]
            if last_modified >= start_time:
                objects.append(obj)

    objects = sorted(objects, key=lambda x: x["LastModified"], reverse=True)[:max_files]

    if not objects:
        return f"No logs found for service={service}, environment={environment}, last {minutes} minutes."

    log_chunks = []

    for obj in reversed(objects):
        key = obj["Key"]
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()

        try:
            text = gzip.decompress(body).decode("utf-8", errors="replace")
        except Exception:
            text = body.decode("utf-8", errors="replace")

        log_chunks.append(f"\n===== s3://{bucket}/{key} =====\n{text}")

    return "\n".join(log_chunks)[-12000:]


@mcp.tool()
def query_prometheus(
    query: str,
    environment: str = "dev",
) -> dict:
    """
    Run an instant Prometheus query.

    Example:
    up
    rate(container_cpu_usage_seconds_total[5m])
    """
    base_url = get_prometheus_url(environment).rstrip("/")
    url = f"{base_url}/api/v1/query"

    response = requests.get(url, params={"query": query}, timeout=15)
    response.raise_for_status()
    return response.json()


@mcp.tool()
def query_prometheus_range(
    query: str,
    environment: str = "dev",
    minutes: int = 10,
    step_seconds: int = 30,
) -> dict:
    """
    Run a Prometheus range query for the last N minutes.
    """
    base_url = get_prometheus_url(environment).rstrip("/")
    url = f"{base_url}/api/v1/query_range"

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)

    response = requests.get(
        url,
        params={
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step_seconds,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


@mcp.tool()
def get_container_cpu_usage(
    environment: str = "dev",
    minutes: int = 10,
) -> dict:
    """
    Get container CPU usage from Prometheus for the last N minutes.
    """
    query = 'rate(container_cpu_usage_seconds_total[5m])'
    return query_prometheus_range(
        query=query,
        environment=environment,
        minutes=minutes,
        step_seconds=30,
    )


@mcp.tool()
def get_yolo_errors(
    environment: str = "dev",
    minutes: int = 10,
) -> str:
    """
    Get recent yolo logs and search for possible errors.
    """
    logs = get_service_logs(
        service="yolo",
        environment=environment,
        minutes=minutes,
        max_files=20,
    )

    lines = []
    for line in logs.splitlines():
        lowered = line.lower()
        if "error" in lowered or "exception" in lowered or "traceback" in lowered or "500" in lowered:
            lines.append(line)

    if not lines:
        return f"No obvious yolo errors found in the last {minutes} minutes."

    return "\n".join(lines[-200:])


if __name__ == "__main__":
    mcp.run()
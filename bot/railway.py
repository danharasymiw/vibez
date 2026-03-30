import asyncio

import aiohttp

from bot import config

API_URL = "https://backboard.railway.app/graphql/v2"


def is_configured() -> bool:
    return bool(
        config.DEPLOY_RAILWAY_TOKEN
        and config.DEPLOY_RAILWAY_SERVICE
        and config.DEPLOY_RAILWAY_ENVIRONMENT
    )


async def _query(query: str, variables: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {config.DEPLOY_RAILWAY_TOKEN}",
        "Content-Type": "application/json",
    }
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables

    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
            if "errors" in data:
                raise RuntimeError(f"Railway API error: {data['errors']}")
            return data["data"]


async def get_latest_deployment() -> dict | None:
    data = await _query(
        """
        query ($input: DeploymentListInput!) {
            deployments(first: 1, input: $input) {
                edges {
                    node {
                        id
                        status
                        createdAt
                    }
                }
            }
        }
        """,
        {
            "input": {
                "serviceId": config.DEPLOY_RAILWAY_SERVICE,
                "environmentId": config.DEPLOY_RAILWAY_ENVIRONMENT,
            }
        },
    )
    edges = data.get("deployments", {}).get("edges", [])
    return edges[0]["node"] if edges else None


async def get_deploy_logs(deployment_id: str) -> str:
    data = await _query(
        """
        query ($deploymentId: String!) {
            deploymentLogs(deploymentId: $deploymentId, limit: 200) {
                message
                severity
            }
        }
        """,
        {"deploymentId": deployment_id},
    )
    logs = data.get("deploymentLogs", [])
    return "\n".join(
        f"[{entry.get('severity', 'INFO')}] {entry['message']}" for entry in logs
    )


async def get_build_logs(deployment_id: str) -> str:
    data = await _query(
        """
        query ($deploymentId: String!) {
            buildLogs(deploymentId: $deploymentId, limit: 200) {
                message
                severity
            }
        }
        """,
        {"deploymentId": deployment_id},
    )
    logs = data.get("buildLogs", [])
    return "\n".join(
        f"[{entry.get('severity', 'INFO')}] {entry['message']}" for entry in logs
    )


async def wait_for_deployment(previous_id: str | None, timeout: float = 300) -> tuple[str, str | None]:
    """Poll until a deployment newer than previous_id succeeds or fails."""
    elapsed = 0.0
    interval = 10.0

    while elapsed < timeout:
        await asyncio.sleep(interval)
        elapsed += interval

        deployment = await get_latest_deployment()
        if not deployment or deployment["id"] == previous_id:
            continue

        status = deployment["status"]
        if status in ("SUCCESS", "READY"):
            return status, deployment["id"]
        if status in ("FAILED", "CRASHED"):
            return status, deployment["id"]

    return "TIMEOUT", None


async def get_all_logs(deployment_id: str) -> str:
    """Fetch both build and deploy logs, concatenated."""
    parts = []
    try:
        build = await get_build_logs(deployment_id)
        if build.strip():
            parts.append("=== BUILD LOGS ===\n" + build)
    except Exception:
        pass
    try:
        deploy = await get_deploy_logs(deployment_id)
        if deploy.strip():
            parts.append("=== DEPLOY LOGS ===\n" + deploy)
    except Exception:
        pass
    return "\n\n".join(parts) if parts else "No logs available."

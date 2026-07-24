import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

ROOT = Path(__file__).parent

credential = DefaultAzureCredential(
    exclude_interactive_browser_credential=True
)


ALL_RETIREMENTS_QUERY = r"""
advisorresources
| where type =~ "microsoft.advisor/metadata"
| where tostring(properties.recommendationSubCategory)
    =~ "ServiceUpgradeAndRetirement"
| extend
    recommendationTypeId = tostring(properties.recommendationTypeId),
    retirementDate =
        todatetime(properties.extendedProperties.retirementDate),
    service =
        coalesce(
            tostring(properties.extendedProperties.retiringFeature),
            tostring(properties.displayName),
            tostring(properties.shortDescription.problem)
        ),
    learnMore =
        coalesce(
            tostring(properties.extendedProperties.learnMoreLink),
            tostring(properties.extendedProperties.link)
        ),
    description =
        coalesce(
            tostring(properties.shortDescription.problem),
            tostring(properties.description)
        ),
    solution =
        tostring(properties.shortDescription.solution)
| where isnull(retirementDate)
    or retirementDate >= startofday(now())
| project
    recommendationTypeId,
    service,
    retirementDate,
    learnMore,
    description,
    solution
"""


IMPACTED_RESOURCES_QUERY = r"""
advisorresources
| where type =~ "microsoft.advisor/recommendations"
| where
    tostring(properties.extendedProperties.recommendationSubCategory)
        =~ "ServiceUpgradeAndRetirement"
    or tostring(properties.recommendationSubCategory)
        =~ "ServiceUpgradeAndRetirement"
    or tostring(properties.extendedProperties.recommendationControl)
        =~ "ServiceUpgradeAndRetirement"
| extend
    resourceId =
        tostring(properties.resourceMetadata.resourceId),
    recommendationTypeId =
        coalesce(
            tostring(properties.recommendationTypeId),
            tostring(properties.recommendationTypeIdGuid)
        ),
    retirementDate =
        todatetime(properties.extendedProperties.retirementDate),
    retiringFeature =
        tostring(properties.extendedProperties.retiringFeature),
    service =
        coalesce(
            tostring(properties.extendedProperties.retiringFeature),
            tostring(properties.shortDescription.problem)
        ),
    solution =
        tostring(properties.shortDescription.solution),
    impact =
        tostring(properties.impact),
    recommendationStatus =
        tostring(properties.recommendationStatus)
| where isnull(retirementDate)
    or retirementDate >= startofday(now())
| join kind=leftouter (
    resources
    | project
        resourceId = id,
        resourceName = name,
        resourceType = type,
        region = location,
        resourceGroup,
        subscriptionId,
        tags
) on resourceId
| project
    recommendationId = id,
    recommendationTypeId,
    service,
    retiringFeature,
    retirementDate,
    solution,
    impact,
    recommendationStatus,
    resourceId,
    resourceName,
    resourceType,
    region,
    resourceGroup,
    subscriptionId,
    tags
"""


def get_subscription_ids() -> list[str\]:
    """
    Reads comma-separated subscription IDs from the Function setting.
    """

    raw_value = os.getenv("AZURE_SUBSCRIPTION_IDS", "")

    subscription_ids = [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]

    if not subscription_ids:
        raise RuntimeError(
            "AZURE_SUBSCRIPTION_IDS is not configured. "
            "Add one or more comma-separated Azure subscription IDs."
        )

    return subscription_ids


def execute_resource_graph_query(
    query: str,
    page_size: int = 1000
) -> list[dict\]:
    """
    Executes a paginated Azure Resource Graph query.
    """

    client = ResourceGraphClient(credential)

    rows: list[dict] = []
    skip_token = None

    while True:
        options = QueryRequestOptions(
            result_format="objectArray",
            top=page_size,
            skip_token=skip_token
        )

        request = QueryRequest(
            subscriptions=get_subscription_ids(),
            query=query,
            options=options
        )

        response = client.resources(request)

        if response.data:
            rows.extend(response.data)

        skip_token = getattr(response, "skip_token", None)

        if not skip_token:
            break

    return rows


def convert_datetime(value):
    """
    Converts datetime-like Resource Graph values to an ISO string.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()

    return str(value)


def unique_nonempty(items, field_name):
    """
    Returns a sorted list of unique, nonempty values.
    """

    return sorted(
        {
            item.get(field_name)
            for item in items
            if item.get(field_name)
        }
    )


def count_unique_resources(items):
    """
    Counts distinct impacted resource IDs.
    """

    return len(
        {
            item.get("resourceId")
            for item in items
            if item.get("resourceId")
        }
    )


def build_retirement_dataset() -> dict:
    """
    Combines retirement metadata and impacted-resource recommendations.
    """

    all_retirements = execute_resource_graph_query(
        ALL_RETIREMENTS_QUERY
    )

    impacted_recommendations = execute_resource_graph_query(
        IMPACTED_RESOURCES_QUERY
    )

    impacted_by_recommendation = {}

    for recommendation in impacted_recommendations:
        key = (
            recommendation.get("recommendationTypeId")
            or recommendation.get("service")
            or "unknown"
        )

        impacted_by_recommendation.setdefault(key, []).append(
            recommendation
        )

    results = []
    processed_keys = set()

    for retirement in all_retirements:
        key = (
            retirement.get("recommendationTypeId")
            or retirement.get("service")
            or "unknown"
        )

        affected_resources = impacted_by_recommendation.get(key, [])

        results.append(
            {
                "id": key,
                "service":
                    retirement.get("service")
                    or "Unnamed retirement",
                "retirementDate":
                    convert_datetime(
                        retirement.get("retirementDate")
                    ),
                "link":
                    retirement.get("learnMore"),
                "description":
                    retirement.get("description"),
                "solution":
                    retirement.get("solution"),
                "impactAnalysisAvailable":
                    bool(affected_resources),
                "impactedCount":
                    count_unique_resources(affected_resources),
                "regions":
                    unique_nonempty(
                        affected_resources,
                        "region"
                    ),
                "subscriptions":
                    unique_nonempty(
                        affected_resources,
                        "subscriptionId"
                    ),
                "resourceGroups":
                    unique_nonempty(
                        affected_resources,
                        "resourceGroup"
                    ),
                "resourceTypes":
                    unique_nonempty(
                        affected_resources,
                        "resourceType"
                    ),
                "impactedResources":
                    affected_resources
            }
        )

        processed_keys.add(key)

    # Some tenants may return resource-level recommendations without
    # corresponding metadata in the same query result. Include those too.
    for key, affected_resources in impacted_by_recommendation.items():
        if key in processed_keys:
            continue

        first = affected_resources[0]

        results.append(
            {
                "id": key,
                "service":
                    first.get("service")
                    or first.get("retiringFeature")
                    or "Retirement recommendation",
                "retirementDate":
                    convert_datetime(
                        first.get("retirementDate")
                    ),
                "link":
                    None,
                "description":
                    None,
                "solution":
                    first.get("solution"),
                "impactAnalysisAvailable":
                    True,
                "impactedCount":
                    count_unique_resources(affected_resources),
                "regions":
                    unique_nonempty(
                        affected_resources,
                        "region"
                    ),
                "subscriptions":
                    unique_nonempty(
                        affected_resources,
                        "subscriptionId"
                    ),
                "resourceGroups":
                    unique_nonempty(
                        affected_resources,
                        "resourceGroup"
                    ),
                "resourceTypes":
                    unique_nonempty(
                        affected_resources,
                        "resourceType"
                    ),
                "impactedResources":
                    affected_resources
            }
        )

    results.sort(
        key=lambda item: (
            item["retirementDate"] is None,
            item["retirementDate"] or "9999-12-31",
            item["service"]
        )
    )

    return {
        "generatedAt":
            datetime.now(timezone.utc).isoformat(),
        "source":
            "Azure Advisor and Azure Resource Graph",
        "notice":
            (
                "Resource-level impact analysis is not available for "
                "every Azure retirement. A retirement showing zero "
                "identified resources must not automatically be "
                "interpreted as confirmation that the environment "
                "is unaffected."
            ),
        "items":
            results
    }


@app.route(
    route="api/retirements",
    methods=["GET"]
)
def api_retirements(
    req: func.HttpRequest
) -> func.HttpResponse:
    """
    Returns normalized retirement and impact data.
    """

    try:
        payload = build_retirement_dataset()

        return func.HttpResponse(
            body=json.dumps(payload, default=str),
            status_code=200,
            mimetype="application/json",
            headers={
                "Cache-Control": "private, max-age=300"
            }
        )

    except Exception as exception:
        logging.exception(
            "Azure retirement query failed."
        )

        return func.HttpResponse(
            body=json.dumps(
                {
                    "error": str(exception),
                    "generatedAt":
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                }
            ),
            status_code=500,
            mimetype="application/json"
        )


@app.route(
    route="api/health",
    methods=["GET"]
)
def api_health(
    req: func.HttpRequest
) -> func.HttpResponse:
    """
    Lightweight health endpoint.
    """

    return func.HttpResponse(
        body=json.dumps(
            {
                "status": "ok",
                "timestamp":
                    datetime.now(
                        timezone.utc
                    ).isoformat()
            }
        ),
        status_code=200,
        mimetype="application/json",
        headers={
            "Cache-Control": "no-store"
        }
    )


@app.route(
    route="",
    methods=["GET"]
)
@app.route(
    route="{*path}",
    methods=["GET"]
)
def ui(
    req: func.HttpRequest
) -> func.HttpResponse:
    """
    Serves the static customer GUI.
    """

    requested_path = (
        req.route_params.get("path")
        or "index.html"
    )

    if requested_path.startswith("api/"):
        return func.HttpResponse(
            "Not found",
            status_code=404
        )

    safe_path = re.sub(
        r"[^a-zA-Z0-9._/-]",
        "",
        requested_path
    )

    static_root = (ROOT / "static").resolve()
    requested_file = (
        ROOT / "static" / safe_path
    ).resolve()

    if (
        requested_file != static_root
        and static_root not in requested_file.parents
    ):
        return func.HttpResponse(
            "Not found",
            status_code=404
        )

    if (
        not requested_file.exists()
        or requested_file.is_dir()
    ):
        requested_file = (
            ROOT / "static" / "index.html"
        )

    content_types = {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon"
    }

    return func.HttpResponse(
        body=requested_file.read_bytes(),
        status_code=200,
        mimetype=content_types.get(
            requested_file.suffix.lower(),
            "application/octet-stream"
        ),
        headers={
            "Cache-Control": "public, max-age=300"
        }
    )

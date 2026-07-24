import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

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
        tolower(tostring(properties.resourceMetadata.resourceId)),
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
        resourceId = tolower(id),
        resourceName = name,
        resourceType = type,
        region = location,
        joinedResourceGroup = resourceGroup,
        joinedSubscriptionId = subscriptionId,
        resourceTags = tags
) on resourceId
| extend
    resourceName = coalesce(
        resourceName,
        tostring(split(resourceId, '/')[-1])
    ),
    resourceType = coalesce(
        resourceType,
        iff(
            array_length(split(resourceId, '/')) >= 9,
            strcat(
                tostring(split(resourceId, '/')[6]),
                '/',
                tostring(split(resourceId, '/')[7])
            ),
            ''
        )
    ),
    resourceGroup = coalesce(joinedResourceGroup, resourceGroup),
    subscriptionId = coalesce(joinedSubscriptionId, subscriptionId)
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
    tags = resourceTags
"""


def get_subscription_ids() -> list[str]:
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
) -> list[dict]:
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
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()

    return str(value)


def unique_nonempty(items, field_name):
    return sorted(
        {
            item.get(field_name)
            for item in items
            if item.get(field_name)
        }
    )


def count_unique_resources(items):
    return len(
        {
            item.get("resourceId")
            for item in items
            if item.get("resourceId")
        }
    )


def build_retirement_dataset() -> dict:
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/retirements")
async def api_retirements():
    try:
        payload = build_retirement_dataset()
        return Response(
            content=json.dumps(payload, default=str),
            media_type="application/json",
            headers={"Cache-Control": "private, max-age=300"}
        )
    except Exception as exc:
        logger.exception("Azure retirement query failed.")
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc),
                "generatedAt": datetime.now(timezone.utc).isoformat()
            }
        )


@app.get("/api/health")
async def api_health():
    return JSONResponse(
        content={
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        headers={"Cache-Control": "no-store"}
    )


@app.get("/")
async def ui():
    return FileResponse(ROOT / "static" / "index.html")


# Static files must be mounted last so API routes take precedence.
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

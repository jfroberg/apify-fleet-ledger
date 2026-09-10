#!/usr/bin/env python3
"""Pull real usage/cost data from the Apify API and write usage-data.json.

Run by .github/workflows/refresh-usage.yml on a schedule. Requires
APIFY_TOKEN in the environment (a GitHub Actions secret, never written
to the output file or logged).
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

TOKEN = os.environ.get("APIFY_TOKEN")
if not TOKEN:
    print("APIFY_TOKEN not set", file=sys.stderr)
    sys.exit(1)

API = "https://api.apify.com/v2"

# name -> (actor id, is this actor's source in this repo)
ACTORS = {
    "B&H":                  ("uyT70x2TgZ8Fgalcb", True),
    "Mozart / Medline":     ("ADnb6IYpm1Pp3gB79", True),
    "Fisher Scientific":    ("2fxV4yIi7vVBJyr0v", True),
    "DigiKey":              ("jrUOfWXFUMUTr6sdB", True),
    "CST":                  ("4WnfDZ2qY3ptiDe0J", True),
    "Ferguson":             ("zWa1i5e0cr8H50URs", True),
    "AVI":                  ("YYlwdzDbZjqydFcJQ", True),
    "Grainger":             ("31dvRegfepkUTcWOf", True),
    "Imperial Bag & Paper": ("dBpwb6p4tXuan7yvt", True),
    "Jagger (CDW)":         ("6wMU6OugwLeUsxKT9", True),
    "Sigma-Aldrich":        ("0fvgR1JjbvEef0feD", True),
    "Staples":              ("6TdbGbcy7ZS2C1iMa", True),
    "IDT":                  ("MSOzQ9fvzcd2EuG8D", False),
    "Eurofins":             ("HlARNGkqiyBuDLuTw", False),
    "Jemtech":              (None, True),
}


def fetch(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    limits = fetch(f"{API}/users/me/limits")["data"]
    account = fetch(f"{API}/users/me")["data"]
    plan = account.get("plan", {})

    actors_out = []
    for name, (actor_id, in_repo) in ACTORS.items():
        if actor_id is None:
            actors_out.append({
                "name": name, "actorId": None, "inLocalRepo": in_repo,
                "cloudRuns": None, "lifetimeUsd": None, "referenceRun": None,
                "note": "not deployed to Apify",
            })
            continue
        try:
            runs = fetch(f"{API}/acts/{actor_id}/runs?limit=100&desc=1")["data"]
            items = runs["items"]
            total_runs = runs["total"]
            lifetime_usd = sum(i.get("usageTotalUsd") or 0 for i in items)

            # "reference run" = the single largest-usd run on record, full detail,
            # regardless of status (an aborted/timed-out run still billed real CU) —
            # this is what seeds the schedule projector's per-run cost estimate.
            reference = None
            if items:
                biggest = max(items, key=lambda i: i.get("usageTotalUsd") or 0)
                detail = fetch(f"{API}/actor-runs/{biggest['id']}")["data"]
                reference = {
                    "status": biggest["status"],
                    "usd": biggest.get("usageTotalUsd"),
                    "startedAt": biggest.get("startedAt"),
                    "cu": round(detail["stats"]["computeUnits"], 3),
                    "durationMin": round(detail["stats"]["runTimeSecs"] / 60, 1),
                    "proxyGb": round(detail["usage"].get("PROXY_RESIDENTIAL_TRANSFER_GBYTES", 0), 4),
                }

            actors_out.append({
                "name": name,
                "actorId": actor_id,
                "inLocalRepo": in_repo,
                "cloudRuns": total_runs,
                "lifetimeUsd": round(lifetime_usd, 4),
                "referenceRun": reference,
            })
        except Exception as e:
            actors_out.append({"name": name, "actorId": actor_id, "inLocalRepo": in_repo, "error": str(e)})

    data = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "account": {
            "username": account.get("username"),
            "planBasePriceUsd": plan.get("monthlyBasePriceUsd"),
            "cuRateUsd": plan.get("planPricing", {}).get("chargeableServiceUnitPricesUsd", {}).get("ACTOR_COMPUTE_UNITS"),
            "residentialRateUsd": plan.get("planPricing", {}).get("chargeableServiceUnitPricesUsd", {}).get("PROXY_RESIDENTIAL_TRANSFER_GBYTES"),
        },
        "cycle": limits.get("monthlyUsageCycle"),
        "limits": {
            "maxMonthlyUsageUsd": limits["limits"]["maxMonthlyUsageUsd"],
        },
        "current": {
            "monthlyUsageUsd": limits["current"]["monthlyUsageUsd"],
            "monthlyActorComputeUnits": limits["current"]["monthlyActorComputeUnits"],
            "monthlyResidentialProxyGbytes": limits["current"]["monthlyResidentialProxyGbytes"],
            "actorCount": limits["current"]["actorCount"],
        },
        "actors": actors_out,
    }

    with open("usage-data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("wrote usage-data.json")


if __name__ == "__main__":
    main()

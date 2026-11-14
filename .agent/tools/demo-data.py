#!/usr/bin/env python3
"""Seed a *local* demonstration workspace through the public API.

Contributor tool only: nothing here is imported by the application. It talks to
a running API exactly as the interface does, so every record passes the same
validation, audit and tenant rules as real work. It refuses to run against
anything but a loopback address.

The five wells are shaped so each analysis in Cost Intelligence has something
real to find:

* WELL-A  steady spend, on plan                      -> healthy
* WELL-B  spend creeps upward from the second third   -> CUSUM drift, forecast overrun
* WELL-C  one day keyed ten times too high, a gap     -> spike, missing sheets
* WELL-D  already beyond its AFE, heavy NPT           -> overrun, NPT share
* WELL-E  configured with an AFE, no actuals          -> nothing recorded yet

Run (API on :8000, owner already provisioned):

    python3 .agent/tools/demo-data.py --base http://127.0.0.1:8000/api/v1 \
        --workspace demo --email owner@demo.example.com --password '...'
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from urllib.parse import urlsplit

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--end", default="", help="Last cost date (YYYY-MM-DD); defaults to yesterday")
    args = parser.parse_args()

    host = urlsplit(args.base).hostname or ""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print("Refusing to seed demonstration data into a non-local API.", file=sys.stderr)
        return 2

    rng = random.Random(7)
    client = httpx.Client(base_url=args.base, timeout=60, headers={"Origin": "http://localhost:5173"})
    signed = client.post("/auth/login", json={"organization": args.workspace, "email": args.email, "password": args.password})
    signed.raise_for_status()
    client.headers["Authorization"] = f"Bearer {signed.json()['access_token']}"

    def post(path: str, payload: dict, ok=(200, 201)) -> dict:
        response = client.post(path, json=payload)
        if response.status_code not in ok:
            raise SystemExit(f"POST {path} -> {response.status_code}: {response.text[:400]}")
        return response.json()

    def put(path: str, payload: dict) -> dict:
        response = client.put(path, json=payload)
        if response.status_code != 200:
            raise SystemExit(f"PUT {path} -> {response.status_code}: {response.text[:400]}")
        return response.json()

    if client.get("/rig-well/wells").json():
        print("This workspace already has wells; nothing was changed.")
        return 0

    # A new workspace may already carry these two reference rows.
    post("/master-data/currencies", {"code": "USD", "name": "US Dollar", "symbol": "$"}, ok=(200, 201, 409))
    post("/master-data/uom", {"code": "MT", "name": "Metric tonne", "symbol": "MT"}, ok=(200, 201, 409))
    holes = [
        post("/master-data/hole-sections", {"code": "17-1/2", "name": "Surface hole"}),
        post("/master-data/hole-sections", {"code": "12-1/4", "name": "Intermediate hole"}),
    ]
    phase = post("/master-data/phases", {"code": "DRILL", "name": "Drilling"})
    act_plan = post("/master-data/activities", {"code": "DRL", "name": "Drilling"})
    act_upa = post("/master-data/activities", {"code": "UPA", "name": "Unplanned activity"})
    act_npt = post("/master-data/activities", {"code": "NPT", "name": "Non-productive time"})
    group = post("/master-data/catalogue-options", {"list_key": "mud_chemical_group", "value": "Weighting agent"})
    post("/master-data/mud-chemicals", {
        "chemical_code": "BARITE", "chemical_name": "Barite", "group_id": group["id"], "part_number": "BR-25",
        "uom": "MT", "unit_rate": "180", "currency": "USD", "effective_date": "2026-01-15",
    })
    vendors = [
        post("/master-data/vendors", {"vendor_code": "V-RIGCO", "vendor_name": "Delta Rig Contractors", "category": "Drilling", "status": "active"}),
        post("/master-data/vendors", {"vendor_code": "V-OILSV", "vendor_name": "Atlantic Oilfield Services", "category": "Drilling", "status": "active"}),
    ]
    services = [
        ("RIG-DAY", "Rig day rate", vendors[0], 21000),
        ("MUD-LOG", "Mud logging", vendors[1], 3200),
        ("DIR-DRL", "Directional drilling", vendors[1], 8600),
    ]
    service_rows = []
    for code, name, vendor, rate in services:
        row = post("/master-data/services", {
            "service_code": code, "service_name": name, "service_category": "Drilling Services",
            "provider_type": "Third Party Services", "vendor_id": vendor["id"], "description": name,
        })
        service_rows.append((row, vendor, rate))
    rigs = [
        post("/rig-well/rigs", {"rig_code": "RIG-01", "rig_name": "Delta Explorer", "remarks": ""}),
        post("/rig-well/rigs", {"rig_code": "RIG-02", "rig_name": "Atlantic Pioneer", "remarks": ""}),
    ]
    block = post("/rig-well/blocks", {"block_code": "OML-88", "block_name": "OML 88", "description": ""})

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    plans = [
        # code, name, rig, planned days, recorded days, shape
        ("WELL-A", "Agbami North 1", rigs[0], 40, 30, "steady"),
        ("WELL-B", "Bonga East 2", rigs[0], 36, 30, "creep"),
        ("WELL-C", "Chota Deep 3", rigs[1], 34, 26, "spike"),
        ("WELL-D", "Dibi West 4", rigs[1], 24, 26, "overrun"),
        ("WELL-E", "Egina South 5", rigs[1], 30, 0, "idle"),
    ]
    for code, name, rig, planned, recorded, shape in plans:
        well = post("/rig-well/wells", {
            "rig_id": rig["id"], "block_id": block["id"], "well_code": code, "well_name": name,
            "well_location": "Niger Delta", "objective": "Development", "remarks": "",
        })
        first_leg = planned // 2
        put(f"/rig-well/wells/{well['id']}/configuration", {
            "depth_unit": "m",
            "sections": [
                {"hole_section_id": holes[0]["id"], "from_depth": "0", "to_depth": "1200", "remarks": "",
                 "phases": [{"phase_id": phase["id"], "days": str(first_leg), "remarks": ""}]},
                {"hole_section_id": holes[1]["id"], "from_depth": "1200", "to_depth": "3100", "remarks": "",
                 "phases": [{"phase_id": phase["id"], "days": str(planned - first_leg), "remarks": ""}]},
            ],
        })
        post(f"/rig-well/wells/{well['id']}/transition", {"action": "configure", "remarks": "Plan checked"})

        def sub(sub_code: str, activity: dict) -> dict:
            return post("/rig-well/sub-activities", {
                "well_id": well["id"], "sub_activity_code": f"{code}-{sub_code}",
                "sub_activity_name": f"{activity['name']} step", "activity_id": activity["id"],
                "responsible_party": "Operations team", "description": "Execute the planned work step.",
            })

        sub_plan, sub_upa, sub_npt = sub("D1", act_plan), sub("U1", act_upa), sub("N1", act_npt)
        afe = post("/afe/afes", {
            "rig_id": rig["id"], "well_id": well["id"], "afe_code": f"AFE-{code[-1]}01",
            "afe_name": f"{name} drilling", "afe_type": "Drilling", "remarks": "",
        })
        estimate_services = []
        for index, (service, _vendor, rate) in enumerate(service_rows):
            for leg, hole in enumerate(holes):
                days = first_leg if leg == 0 else planned - first_leg
                estimate_services.append({
                    "client_key": f"svc-{index}-{leg}", "service_id": service["id"], "charging_basis": "Day Rate",
                    "hole_section_id": hole["id"], "phase_id": phase["id"], "currency": "USD", "service_amount": "0",
                    "remarks": "", "rates": [{"category": "Operation", "unit_rate": str(rate)}],
                    "charges": [{"category": "Operation", "quantity": str(days), "quantity_unit": "days"}],
                    "section_rates": [],
                })
        put(f"/afe/afes/{afe['id']}/estimate", {
            "services": estimate_services,
            "consumables": [{
                "client_key": "bulk-mud", "category": "Mud Chemicals", "hole_section_id": holes[0]["id"],
                "phase_id": phase["id"], "drill_bit_id": None, "quantity": "1", "override_rate": None,
                "estimated_amount": "90000", "currency": "USD", "remarks": "Bulk chemicals allowance",
            }],
            "tangibles": [], "standard_currency": "", "exchange_rates": [],
        })
        if not recorded:
            print(f"{code}: configured, AFE created, no actuals")
            continue

        start = end - timedelta(days=recorded - 1)
        skipped = {12, 13} if shape == "spike" else set()
        written = 0
        for offset in range(recorded):
            if offset in skipped:
                continue
            cost_day = start + timedelta(days=offset)
            hole = holes[0] if offset < first_leg else holes[1]
            created = post("/daily-cost/entries", {
                "well_id": well["id"], "afe_id": afe["id"], "cost_date": cost_day.isoformat(), "remarks": "",
            })
            entry_id = created["entry"]["id"]
            baseline = client.get(f"/daily-cost/entries/{entry_id}/baseline").json()
            rates = {}
            for rate in baseline["service_rates"]:
                if rate.get("hole_section_id") in (hole["id"], None):
                    rates.setdefault(rate["service_id"], rate)
            for rate in baseline["service_rates"]:
                rates.setdefault(rate["service_id"], rate)

            def line(service, vendor, activity, sub_activity, quantity="1", override=None, reason=""):
                item = {
                    "activity_id": activity["id"], "hole_section_id": hole["id"], "phase_id": phase["id"],
                    "sub_activity_id": sub_activity["id"], "vendor_id": vendor["id"], "quantity": quantity,
                    "quantity_unit": "days", "currency": "USD", "remarks": "", "service_id": service["id"],
                    "baseline_service_rate_id": rates[service["id"]]["id"], "charging_basis": "Day Rate",
                    "charge_category": "Operation",
                }
                if override is not None:
                    item["override_rate"] = str(override)
                    item["override_reason"] = reason
                return item

            lines = [line(service, vendor, act_plan, sub_plan) for service, vendor, _rate in service_rows[:2]]
            dd_service, dd_vendor, dd_rate = service_rows[2]
            if offset >= 4:
                lines.append(line(dd_service, dd_vendor, act_plan, sub_plan))
            noise = rng.randint(-900, 900)
            if shape == "steady":
                extra = 1500 + noise
            elif shape == "creep":
                extra = 1500 + noise + (0 if offset < 10 else (offset - 9) * 1150)
            elif shape == "spike":
                extra = 1800 + noise
            else:
                extra = 9000 + noise
            if shape == "spike" and offset == 19:
                # The well's one keying slip: 2,150 keyed as 215,000.
                extra = 215000
            lines.append(line(service_rows[1][0], service_rows[1][1], act_upa, sub_upa, override=max(extra, 200),
                              reason="Additional call-out"))
            if shape == "overrun" and offset % 3 == 0:
                lines.append(line(service_rows[0][0], service_rows[0][1], act_npt, sub_npt, override=14500 + noise,
                                  reason="Rig repair standby"))
            elif shape != "overrun" and offset % 11 == 5:
                lines.append(line(service_rows[0][0], service_rows[0][1], act_npt, sub_npt, override=6000 + noise,
                                  reason="Waiting on weather"))
            put(f"/daily-cost/entries/{entry_id}", {
                "remarks": "shift actuals", "services": lines, "consumables": [], "tangibles": [],
            })
            written += 1
        print(f"{code}: {written} daily sheets from {start} to {end}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

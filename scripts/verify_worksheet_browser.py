"""Development-only browser regressions. Run against a local IFMS test workspace.

Requires Playwright in the development environment; adds no app dependency.
Creates synthetic worksheet drafts and checks delayed HTTP responses do not
replace newer edits or present an old calculation as current.
"""

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def synthetic_payload():
    row = dict(
        month="2040-07",
        start="2040-07-01",
        end="2040-07-31",
        presentation="period",
        drawn_BASIC="24800",
        drawn_DA="14880",
        drawn_HRA="0",
        drawn_HDA="3307",
        drawn_CCA="0",
        hra_rate="20",
        salary_reference="Synthetic verified salary",
        order_reference="Synthetic approved 20%",
        history_reference="Synthetic history check: no earlier HRA",
        deduction_reference="Synthetic no extra deductions",
        history_reviewed=True,
        deductions_reviewed=True,
    )
    for h in ("BASIC", "DA", "HRA", "HDA", "CCA"):
        row["prior_" + h] = "0"
    for h in ("GPF", "SI", "CM_CORONA", "I_TAX"):
        row["ded_" + h] = "0"
    return dict(
        employee_code="SYN-RACE",
        employee_name="Synthetic Response Check",
        kind="hra",
        rounding="rupee",
        template_id="jodhpur_classic",
        include_hda=False,
        rows=[row],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8810")
    parser.add_argument(
        "--output", default="/tmp/ifms-worksheet-browser-regressions.json"
    )
    args = parser.parse_args()
    checks = {}
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url + "/suite/")
        page.get_by_role("button", name="Excel Arrear Maker", exact=True).click()
        page.wait_for_function("worksheetState.schema !== null")
        response = page.request.post(
            args.url + "/suite/api/worksheets", data={"payload": synthetic_payload()}
        )
        assert response.status == 201, response.text()
        ident = response.json()["id"]
        page.evaluate(
            'async id => { const saved=await api("worksheets/"+id);worksheetSet(saved.payload,saved); }',
            ident,
        )
        page.get_by_role("button", name="Sanctioned changes", exact=True).click()
        # This intercept delays the actual HTTP response after the server has saved it.
        page.evaluate(
            """() => {
          const original=window.fetch;
          window.holdWorksheetResponse=null; window.releaseWorksheetResponse=null;
          window.fetch=async (...args)=>{
            const response=await original(...args);
            if(window.holdWorksheetResponse && String(args[0]).includes(window.holdWorksheetResponse) && args[1]?.method==='POST') {
              window.holdWorksheetResponse=null;
              await new Promise(resolve=>window.releaseWorksheetResponse=resolve);
            }
            return response;
          };
        }"""
        )
        page.evaluate('id => window.holdWorksheetResponse="worksheets/"+id', ident)
        page.get_by_role("button", name="Save draft", exact=True).click()
        page.wait_for_function("window.releaseWorksheetResponse !== null")
        page.locator("[data-key=hra_rate]").fill("21")
        page.evaluate("window.releaseWorksheetResponse()")
        page.wait_for_function('!document.getElementById("worksheetSave").disabled')
        assert (
            page.locator("[data-key=hra_rate]").input_value() == "21"
        ), "Save response overwrote the edit made during saving"
        assert (
            page.evaluate("worksheetState.dirty") is True
        ), "Newer edit was marked saved"
        checks["newer_edits_survive_save_response"] = True
        page.evaluate(
            'window.releaseWorksheetResponse=null;window.holdWorksheetResponse="worksheets/calculate"'
        )
        page.get_by_role("button", name="Check and calculate", exact=True).click()
        page.wait_for_function("window.releaseWorksheetResponse !== null")
        page.locator("[data-key=hra_rate]").fill("22")
        page.evaluate("window.releaseWorksheetResponse()")
        page.wait_for_function(
            '!document.getElementById("worksheetCalculate").disabled'
        )
        assert (
            page.evaluate("worksheetState.result") is None
        ), "Stale calculation shown as current"
        assert page.locator("[data-key=hra_rate]").input_value() == "22"
        checks["stale_calculation_response_is_discarded"] = True
        checks["browser_errors"] = errors
        assert not errors, errors
        browser.close()
    Path(args.output).write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()

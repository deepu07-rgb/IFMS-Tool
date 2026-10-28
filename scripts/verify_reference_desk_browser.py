"""Development browser smoke for typed references and persistent floating panels.

Run against a local test workspace. Creates only synthetic reference text; does
not alter salary records or seed real financial rules. Playwright is a development
capability, not a production dependency.
"""

import argparse
import json
from pathlib import Path
import uuid
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8812")
    parser.add_argument("--output", default="/tmp/ifms-reference-desk-browser.json")
    args = parser.parse_args()
    checks = {}
    errors = []
    marker = "SYNTHETIC-REFERENCE-" + uuid.uuid4().hex[:8]
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url + "/suite/")
        page.get_by_role("button", name="Important Documents", exact=True).click()
        page.locator("#documentEditor [name=title]").fill(marker)
        page.locator("#documentEditor [name=body]").fill(
            "Synthetic typed rule for browser regression; no real financial authority."
        )
        with page.expect_response(
            lambda r: "/api/library/documents" in r.url and r.request.method == "POST"
        ) as reply:
            page.get_by_role("button", name="Save document", exact=True).click()
        assert reply.value.status == 201, reply.value.text()
        ident = reply.value.json()["id"]
        checks["typed_rule_save_201"] = True
        page.locator("#documentSearch [name=q]").fill(marker)
        page.locator("#documentSearch button").click()
        card = page.locator(f'[data-pin-kind=document][data-pin-id="{ident}"]')
        card.wait_for()
        card.get_by_role("button", name="Pin beside work", exact=True).click()
        panel = page.locator(f'.reference-window[data-reference-id="{ident}"]')
        panel.wait_for()
        assert marker in panel.inner_text()
        before = panel.bounding_box()
        handle = panel.locator(".reference-window-header").bounding_box()
        page.mouse.move(handle["x"] + 60, handle["y"] + 15)
        page.mouse.down()
        page.mouse.move(handle["x"] - 100, handle["y"] + 45, steps=6)
        page.mouse.up()
        assert panel.bounding_box()["x"] < before["x"] - 50
        checks["drag_reference"] = True
        page.get_by_role("button", name="Excel Arrear Maker", exact=True).click()
        assert panel.is_visible()
        checks["module_navigation_keeps_panel"] = True
        page.reload()
        panel.wait_for()
        checks["reload_restores_panel"] = True
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(250)
        box = panel.bounding_box()
        assert (
            box["x"] >= 0
            and box["y"] >= 0
            and box["x"] + box["width"] <= 391
            and box["y"] + box["height"] <= 845
        )
        checks["mobile_geometry_reachable"] = True
        checks["browser_errors"] = errors
        assert not errors, errors
        browser.close()
    Path(args.output).write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()

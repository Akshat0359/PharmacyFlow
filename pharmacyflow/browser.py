from playwright.async_api import async_playwright
from .config import settings
from urllib.parse import urlsplit


async def transact(prepared: dict, fault=None):
    trace_dir = settings().data_dir / "browser"
    trace_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # JWT capabilities must not enter Playwright trace archives (which record headers).
        # Store sanitized browser steps as audit events; no raw network trace is retained.
        context = await browser.new_context(
            extra_http_headers={"Authorization": "Bearer " + prepared["token"]}
        )
        origin = urlsplit(settings().mock_url)

        async def restrict(route):
            target = urlsplit(route.request.url)
            if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                await route.abort("blockedbyclient")
            else:
                await route.continue_()

        await context.route("**/*", restrict)
        page = await context.new_page()
        try:
            page.set_default_timeout(2500)
            response = await page.goto(settings().mock_url, wait_until="domcontentloaded")
            if response.status == 401:
                raise PermissionError("Mock session expired")
            if fault == "browser_crash":
                await browser.close()
                raise RuntimeError("Injected browser disconnection")
            if (
                await page.get_by_label("Patient", exact=True).input_value()
                != prepared["action"]["patient_id"]
            ):
                raise ValueError("UI patient mismatch")
            await page.get_by_role("button", name="Record request", exact=True).click()
            receipt = page.get_by_test_id("receipt")
            await receipt.wait_for()
            if await receipt.get_attribute("data-hash") != prepared["action_hash"]:
                raise ValueError("Saved UI action mismatch")
            return {
                "id": await receipt.get_attribute("data-request"),
                "status": await receipt.inner_text(),
                "action_hash": prepared["action_hash"],
            }
        finally:
            await context.close()
            await browser.close()

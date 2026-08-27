from fastapi.testclient import TestClient


def test_admin_page_and_assets_are_served(client: TestClient) -> None:
    page = client.get("/admin")

    assert page.status_code == 200
    assert "收藏汇 · 账户管理" in page.text
    assert 'href="/static/admin.css"' in page.text
    assert 'src="/static/admin.js"' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"

    stylesheet = client.get("/static/admin.css")
    script = client.get("/static/admin.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "sessionStorage" in script.text
    assert "充值" in script.text

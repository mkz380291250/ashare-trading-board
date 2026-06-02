from fastapi.testclient import TestClient
from app.main import create_app
from app.api.routes_market import get_price_provider
from app.data.prices import DictPriceProvider


def test_bars_latest_close():
    app = create_app()
    app.dependency_overrides[get_price_provider] = lambda: DictPriceProvider({"X": 9.9})
    client = TestClient(app)
    r = client.get("/api/price/X")
    assert r.status_code == 200
    assert r.json() == {"code": "X", "close": 9.9}

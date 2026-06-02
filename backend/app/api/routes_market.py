from fastapi import APIRouter, Depends, HTTPException
from app.data.prices import PriceProvider, DictPriceProvider

router = APIRouter(prefix="/api", tags=["market"])


def get_price_provider() -> PriceProvider:
    # MVP placeholder; replaced by a qlib-backed provider later.
    return DictPriceProvider({})


@router.get("/price/{code}")
def price(code: str, pp: PriceProvider = Depends(get_price_provider)):
    try:
        return {"code": code, "close": pp.latest_close(code)}
    except KeyError:
        raise HTTPException(404, f"no price for {code}")

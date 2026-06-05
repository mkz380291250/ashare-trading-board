import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_session
from app.data.names import NameLookup
from app.screener.pool import WatchPool

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.get("/picks")
def picks(s: Session = Depends(get_session)):
    pool = WatchPool(s).list()
    names = NameLookup(s).map([p.code for p in pool])
    out = []
    for p in pool:
        out.append({
            "code": p.code, "name": names.get(p.code, ""), "theme": p.theme,
            "first_selected_on": p.first_selected_on.isoformat(),
            "entry_close": p.entry_close, "trigger": json.loads(p.trigger or "{}"),
            "ret_t1": p.ret_t1, "ret_t3": p.ret_t3,
            "ret_t5": p.ret_t5, "ret_t10": p.ret_t10,
        })
    return out

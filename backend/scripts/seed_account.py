import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.api.deps import get_session
from app.db.models import Account
from app.config import get_settings


def main():
    s = next(get_session())
    if s.query(Account).filter_by(name="main").first() is None:
        s.add(Account(name="main", cash=float(get_settings().initial_cash))); s.commit()
        print("seeded main account")
    else:
        print("main account already exists")


if __name__ == "__main__":
    main()

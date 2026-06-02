import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.db.database import make_engine, Base
import app.db.models  # noqa: F401


def main():
    engine = make_engine()
    Base.metadata.create_all(engine)
    print("tables created")


if __name__ == "__main__":
    main()

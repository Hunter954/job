import os


def _normalize_database_url(url: str) -> str:
    """Normaliza DATABASE_URL.

    Railway e alguns providers usam `postgres://`, mas o SQLAlchemy espera `postgresql://`.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # Railway normalmente fornece DATABASE_URL
    _db_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("JOBBOARD_DATABASE_URL")
        or "sqlite:///" + os.path.join(BASE_DIR, "instance", "app.db")
    )
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(_db_url)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True

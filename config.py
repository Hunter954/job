import os


def _normalize_database_url(url: str) -> str:
    """Normaliza DATABASE_URL para o SQLAlchemy.

    - Railway (e outros) podem fornecer `postgres://`
    - Em alguns ambientes (ex.: Python 3.13), `psycopg2` pode falhar por depender de libpq
      do sistema. Por isso usamos `psycopg` (v3) e forçamos o dialeto `postgresql+psycopg`.
    """
    if not url:
        return url

    # SQLite: não mexe
    if url.startswith("sqlite:"):
        return url

    # Converte esquemas comuns para o driver psycopg (v3)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)

    if url.startswith("postgresql://") and "postgresql+" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)

    return url

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

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

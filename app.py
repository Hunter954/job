from flask import Flask
from config import Config
from extensions import db, migrate, login_manager
from auth import auth_bp
from main import main_bp
from candidate import candidate_bp
from company import company_bp
from admin import admin_bp
from payments import payments_bp
from chat import chat_bp
from models import User

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError


def _ensure_schema():
    """Best-effort schema patcher for first deploys / legacy DBs.

    - create_all() does NOT add new columns to existing tables.
    - Railway Postgres often starts empty or may have old schema from earlier deploys.

    This function tries to add missing columns used by the app, without dropping data.
    """
    insp = inspect(db.engine)
    dialect = db.engine.dialect.name  # 'postgresql', 'sqlite', etc.

    def _cols(table_name: str):
        try:
            return {c["name"] for c in insp.get_columns(table_name)}
        except Exception:
            return set()

    def _add_column(table: str, col: str, ddl_type: str, default_sql: str | None = None):
        cols = _cols(table)
        if col in cols:
            return

        default_part = f" DEFAULT {default_sql}" if default_sql else ""
        if dialect == "postgresql":
            ddl = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col}" {ddl_type}{default_part};'
        else:
            # SQLite: no IF NOT EXISTS; try and ignore if fails
            ddl = f'ALTER TABLE "{table}" ADD COLUMN "{col}" {ddl_type}{default_part};'

        try:
            db.session.execute(text(ddl))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()

    # Columns used in queries / screens (minimum set to prevent 500s)
    _add_column("company_profile", "is_approved", "BOOLEAN", "false")
    _add_column("company_profile", "is_sponsored", "BOOLEAN", "false")
    _add_column("company_profile", "sponsored_until", "TIMESTAMP")

    _add_column("job", "is_active", "BOOLEAN", "true")
    _add_column("job", "is_sponsored", "BOOLEAN", "false")
    _add_column("job", "sponsored_until", "TIMESTAMP")
    _add_column("job", "created_at", "TIMESTAMP")

    _add_column("candidate_profile", "is_public", "BOOLEAN", "true")
    _add_column("candidate_profile", "is_sponsored", "BOOLEAN", "false")
    _add_column("candidate_profile", "sponsored_until", "TIMESTAMP")

    _add_column("user", "is_premium", "BOOLEAN", "false")
    _add_column("user", "is_active", "BOOLEAN", "true")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        if not user_id:
            return None
        return User.query.get(int(user_id))

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(candidate_bp, url_prefix="/candidato")
    app.register_blueprint(company_bp, url_prefix="/empresa")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(payments_bp)
    app.register_blueprint(chat_bp)

    # Railway/produção: garantir que as tabelas existam no primeiro deploy.
    # create_all() é idempotente (não apaga dados), apenas cria o que falta.
    # _ensure_schema() tenta adicionar colunas faltantes em bancos antigos.
    with app.app_context():
        db.create_all()
        _ensure_schema()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)

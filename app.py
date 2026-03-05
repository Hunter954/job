import os
import shutil

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
    # Novos campos do perfil da empresa (evita 500 quando o banco é antigo)
    _add_column("company_profile", "cep", "VARCHAR(20)")
    _add_column("company_profile", "state", "VARCHAR(30)")
    _add_column("company_profile", "neighborhood", "VARCHAR(120)")
    _add_column("company_profile", "house_number", "VARCHAR(30)")
    _add_column("company_profile", "segment", "VARCHAR(120)")
    _add_column("company_profile", "company_size", "VARCHAR(60)")
    _add_column("company_profile", "founded_year", "INTEGER")

    _add_column("job", "is_active", "BOOLEAN", "true")
    _add_column("job", "is_sponsored", "BOOLEAN", "false")
    _add_column("job", "sponsored_until", "TIMESTAMP")
    _add_column("job", "created_at", "TIMESTAMP")

    _add_column("candidate_profile", "is_public", "BOOLEAN", "true")
    _add_column("candidate_profile", "is_sponsored", "BOOLEAN", "false")
    _add_column("candidate_profile", "sponsored_until", "TIMESTAMP")

    _add_column("user", "is_premium", "BOOLEAN", "false")
    _add_column("user", "is_active", "BOOLEAN", "true")


def _ensure_persistent_uploads(app: Flask):
    """Railway (e similares) usam filesystem efêmero.

    Para não perder imagens em redeploy, use um Volume montado em /data
    e aponte /static/uploads -> /data/uploads via symlink.

    - Mantém compatibilidade com os templates atuais (url_for('static', ...)).
    - Não exige alterar candidate.py/company.py.
    """
    uploads_target = os.environ.get("UPLOADS_DIR", "/data/uploads")

    # Só ativa se /data existir (quando você adicionar um Volume no Railway)
    data_root = os.path.dirname(uploads_target.rstrip("/"))
    if not os.path.isdir(data_root):
        return

    os.makedirs(uploads_target, exist_ok=True)
    os.makedirs(os.path.join(uploads_target, "companies"), exist_ok=True)

    static_uploads = os.path.join(app.root_path, "static", "uploads")
    static_dir = os.path.dirname(static_uploads)
    os.makedirs(static_dir, exist_ok=True)

    # Se já for symlink, ok
    if os.path.islink(static_uploads):
        return

    # Se existir uma pasta antiga, copia pro destino antes de trocar
    if os.path.isdir(static_uploads):
        try:
            if os.listdir(static_uploads):
                for item in os.listdir(static_uploads):
                    src = os.path.join(static_uploads, item)
                    dst = os.path.join(uploads_target, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
        except Exception:
            pass

        try:
            shutil.rmtree(static_uploads)
        except Exception:
            pass

    # Cria symlink /static/uploads -> /data/uploads
    try:
        os.symlink(uploads_target, static_uploads)
    except FileExistsError:
        pass


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Persistência de uploads em produção (Railway Volume em /data)
    _ensure_persistent_uploads(app)

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

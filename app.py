from flask import Flask
from config import Config
from extensions import db, migrate, login_manager
from auth import auth_bp
from main import main_bp
from candidate import candidate_bp
from company import company_bp
from admin import admin_bp
from models import User

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

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)

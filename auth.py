from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user
from extensions import db
from models import User, CandidateProfile, CompanyProfile
from forms import LoginForm, CandidateRegisterForm, CompanyRegisterForm

auth_bp = Blueprint("auth", __name__, template_folder="templates")


@auth_bp.route("/escolher-tipo")
def choose_type():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    return render_template("auth/choose_type.html")


@auth_bp.route("/registro/candidato", methods=["GET", "POST"])
def register_candidate():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = CandidateRegisterForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(email=form.email.data.lower()).first()
        if existing:
            flash("E-mail já cadastrado.", "danger")
        else:
            user = User(
                email=form.email.data.lower(),
                role="candidate",
                full_name=form.full_name.data.strip(),
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()

            profile = CandidateProfile(
                user_id=user.id,
                cpf=form.cpf.data.strip(),
            )
            db.session.add(profile)
            db.session.commit()
            login_user(user)
            flash("Conta de candidato criada com sucesso! Complete seu perfil profissional.", "success")
            return redirect(url_for("candidate.complete_profile"))
    return render_template("auth/register_candidate.html", form=form)


@auth_bp.route("/registro/empresa", methods=["GET", "POST"])
def register_company():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = CompanyRegisterForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(email=form.email.data.lower()).first()
        if existing:
            flash("E-mail já cadastrado.", "danger")
        else:
            user = User(
                email=form.email.data.lower(),
                role="company",
                company_name=form.company_name.data.strip(),
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()

            profile = CompanyProfile(
                user_id=user.id,
                cnpj=form.cnpj.data.strip(),
            )
            db.session.add(profile)
            db.session.commit()
            login_user(user)
            flash("Conta de empresa criada com sucesso! Complete o perfil da empresa.", "success")
            return redirect(url_for("company.dashboard"))
    return render_template("auth/register_company.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Se já está logado, manda direto pro painel
    if current_user.is_authenticated:
        return redirect_after_login(current_user)

    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        password = form.password.data

        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            flash("E-mail ou senha inválidos.", "danger")
            return redirect(url_for("auth.login"))

        if not user.is_active:
            flash("Sua conta está desativada. Fale com o suporte.", "warning")
            return redirect(url_for("auth.login"))

        login_user(user, remember=form.remember.data if hasattr(form, "remember") else False)
        
        flash("Login realizado com sucesso! Bem-vindo de volta. 👋", "success")


        # se veio um ?next=/alguma/rota, respeita
        next_page = request.args.get("next")
        if next_page:
            return redirect(next_page)

        # senão, manda pro painel conforme o tipo de usuário
        return redirect_after_login(user)

    return render_template("auth/login.html", form=form)


def redirect_after_login(user: User):
    """Decide pra onde mandar o usuário depois do login."""
    if user.role == "candidate":
        return redirect(url_for("candidate.dashboard"))
    elif user.role == "company":
        return redirect(url_for("company.dashboard"))  # ajuste se o nome for outro
    elif user.role == "admin":
        return redirect(url_for("admin.dashboard"))    # opcional

    # fallback: manda pra home
    return redirect(url_for("main.index"))


@auth_bp.route("/logout")
def logout():
    from flask_login import logout_user
    from flask import redirect, url_for, flash

    logout_user()
    flash("Você saiu da sua conta. Até logo!", "info")
    return redirect(url_for("main.index"))


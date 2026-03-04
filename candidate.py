from datetime import datetime
import os
import uuid
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user

from werkzeug.utils import secure_filename
from extensions import db
from models import CandidateProfile, Job, Application, CompanyInterest, Notification, CandidateExperience
from forms import CandidateProfileForm

candidate_bp = Blueprint("candidate", __name__, template_folder="templates")




# -------------------------------------------------------------------
# Upload de foto (avatar) do candidato
# -------------------------------------------------------------------
ALLOWED_AVATAR_EXTS = {"png", "jpg", "jpeg", "webp"}

def _allowed_avatar(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_AVATAR_EXTS

def _avatar_upload_folder() -> str:
    # Salva em: <app_root>/static/uploads
    return os.path.join(current_app.root_path, "static", "uploads")

# -------------------------------------------------------------------
# Decorator: garante que só candidatos acessem as rotas
# -------------------------------------------------------------------
def candidate_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "candidate":
            flash("Acesso permitido apenas para candidatos.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    return wrapper


# -------------------------------------------------------------------
# DASHBOARD
# -------------------------------------------------------------------
@candidate_bp.route("/dashboard")
@login_required
@candidate_required
def dashboard():
    """Painel principal do candidato (visão geral)."""
    profile = current_user.candidate_profile

    if not profile:
        flash("Crie seu perfil de candidato primeiro.", "warning")
        return redirect(url_for("candidate.profile"))

    # % de completude do perfil
    completion_fields = [
        "address",
        "city",
        "birthdate",
        "phone",
        "profession",
        "experience_years",
        "skills",
        "bio",
    ]
    total = len(completion_fields)
    filled = sum(
        1
        for field in completion_fields
        if getattr(profile, field, None) not in (None, "", 0)
    )
    completion_percent = int((filled / total) * 100) if total else 0

    # Candidaturas
    applications_query = (
        Application.query.filter_by(candidate_id=profile.id)
        .order_by(Application.created_at.desc())
    )
    applications = applications_query.limit(10).all()
    applications_count = applications_query.count()

    # Entrevistas (baseadas em CompanyInterest com status de entrevista)
    interviews_query = CompanyInterest.query.filter_by(candidate_id=profile.id)
    if hasattr(CompanyInterest, "status"):
        interviews_query = interviews_query.filter(
            CompanyInterest.status.in_(
                ["entrevista_marcada", "entrevista_confirmada", "confirmada"]
            )
        )
    interviews_count = interviews_query.count()

    # Empresas interessadas
    interests_query = (
        CompanyInterest.query.filter_by(candidate_id=profile.id)
        .order_by(CompanyInterest.created_at.desc())
    )
    interests = interests_query.limit(10).all()
    interests_count = interests_query.count()

    # Visualizações do perfil
    views_count = getattr(profile, "views_count", 0) or 0

    # Vagas recomendadas
    jobs_query = Job.query
    if hasattr(Job, "is_active"):
        jobs_query = jobs_query.filter(Job.is_active.is_(True))

    if profile.city and hasattr(Job, "city"):
        jobs_query = jobs_query.filter(Job.city == profile.city)

    order_cols = []
    if hasattr(Job, "is_sponsored"):
        order_cols.append(Job.is_sponsored.desc())
    if hasattr(Job, "created_at"):
        order_cols.append(Job.created_at.desc())
    if order_cols:
        jobs_query = jobs_query.order_by(*order_cols)

    recommended_jobs = jobs_query.limit(3).all()

    return render_template(
        "candidate/dashboard.html",
        profile=profile,
        completion_percent=completion_percent,
        applications=applications,
        applications_count=applications_count,
        interviews_count=interviews_count,
        views_count=views_count,
        interests=interests,
        interests_count=interests_count,
        recommended_jobs=recommended_jobs,
    )


# -------------------------------------------------------------------
# MEU PERFIL (edição inline)
# -------------------------------------------------------------------
from datetime import datetime

# ... seus outros imports ...
from models import CandidateProfile, Job, Application, CompanyInterest, Notification, CandidateExperience

@candidate_bp.route("/perfil", methods=["GET", "POST"])
@login_required
@candidate_required
def profile():
    """
    Aba 'Perfil Profissional':
    - Dados profissionais
    - Experiências profissionais
    - Controle de visibilidade do perfil
    """
    profile = current_user.candidate_profile

    if not profile:
        profile = CandidateProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    form = CandidateProfileForm()  # só para CSRF

    if request.method == "POST":
        action = request.form.get("action", "save_profile")

        # ---------- Salvar dados do perfil profissional ----------
        if action == "save_profile":
            # Nome / cidade / estado só mudam em "Meus Dados"
            profile.profession = request.form.get("profession", "").strip() or None
            profile.education_level = request.form.get("education_level", "").strip() or None
            profile.availability = request.form.get("availability", "").strip() or None

            profile.skills = request.form.get("skills", "").strip() or None
            profile.languages = request.form.get("languages", "").strip() or None
            profile.bio = request.form.get("bio", "").strip() or None


            # ---------- Upload de foto (avatar) ----------
            file = request.files.get("avatar")
            if file and file.filename:
                if not _allowed_avatar(file.filename):
                    flash("Formato de imagem inválido. Use PNG, JPG, JPEG ou WEBP.", "danger")
                    return redirect(url_for("candidate.profile"))

                os.makedirs(_avatar_upload_folder(), exist_ok=True)

                safe = secure_filename(file.filename)
                ext = safe.rsplit(".", 1)[1].lower()
                new_name = f"{uuid.uuid4().hex}.{ext}"
                save_path = os.path.join(_avatar_upload_folder(), new_name)
                file.save(save_path)

                # remove avatar antigo (se existir)
                if profile.avatar_filename:
                    old_path = os.path.join(_avatar_upload_folder(), profile.avatar_filename)
                    try:
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    except Exception:
                        pass

                profile.avatar_filename = new_name
            profile.is_completed = True
            db.session.commit()
            flash("Perfil profissional atualizado com sucesso!", "success")
            return redirect(url_for("candidate.profile"))

        # ---------- Salvar SOMENTE a foto (avatar) ----------
        elif action == "save_avatar":
            file = request.files.get("avatar")
            if not file or not file.filename:
                flash("Selecione uma imagem para salvar.", "warning")
                return redirect(url_for("candidate.profile"))

            if not _allowed_avatar(file.filename):
                flash("Formato de imagem inválido. Use PNG, JPG, JPEG ou WEBP.", "danger")
                return redirect(url_for("candidate.profile"))

            os.makedirs(_avatar_upload_folder(), exist_ok=True)

            safe = secure_filename(file.filename)
            ext = safe.rsplit(".", 1)[1].lower()
            new_name = f"{uuid.uuid4().hex}.{ext}"
            save_path = os.path.join(_avatar_upload_folder(), new_name)
            file.save(save_path)

            # remove avatar antigo (se existir)
            if profile.avatar_filename:
                old_path = os.path.join(_avatar_upload_folder(), profile.avatar_filename)
                try:
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass

            profile.avatar_filename = new_name
            db.session.commit()
            flash("Foto de perfil atualizada com sucesso!", "success")
            return redirect(url_for("candidate.profile"))

        # ---------- Adicionar experiência profissional ----------
        elif action == "add_experience":
            from datetime import date

            role = request.form.get("exp_role", "").strip()
            company_name = request.form.get("exp_company", "").strip()

            start_month = request.form.get("exp_start_month")
            start_year = request.form.get("exp_start_year")
            end_month = request.form.get("exp_end_month")
            end_year = request.form.get("exp_end_year")

            current_flag = request.form.get("exp_current") == "on"

            if not role or not company_name or not (start_month and start_year):
                flash("Preencha cargo, empresa e o período de início da experiência.", "warning")
                return redirect(url_for("candidate.profile"))

            # monta datas a partir de mês/ano
            start_date = None
            try:
                start_date = date(int(start_year), int(start_month), 1)
            except (ValueError, TypeError):
                start_date = None

            end_date = None
            if not current_flag and end_month and end_year:
                try:
                    end_date = date(int(end_year), int(end_month), 1)
                except (ValueError, TypeError):
                    end_date = None

            exp = CandidateExperience(
                candidate_id=profile.id,
                role=role,
                company_name=company_name,
                start_date=start_date,
                end_date=end_date,
                is_current=current_flag,
            )
            db.session.add(exp)
            db.session.commit()
            flash("Experiência profissional adicionada!", "success")
            return redirect(url_for("candidate.profile"))

        # ---------- Remover experiência ----------
        elif action == "delete_experience":
            exp_id = request.form.get("experience_id")
            if exp_id:
                exp = CandidateExperience.query.get(exp_id)
                if exp and exp.candidate_id == profile.id:
                    db.session.delete(exp)
                    db.session.commit()
                    flash("Experiência removida.", "info")
            return redirect(url_for("candidate.profile"))

        # ---------- Ativar / Desativar visibilidade do perfil ----------
        elif action == "toggle_visibility":
            # Se está ATIVADO e quer DESATIVAR: não valida nada, só desliga.
            if profile.is_public:
                profile.is_public = False
                db.session.commit()
                flash(
                    "Seu perfil foi DESATIVADO e não aparecerá mais na home nem na busca.",
                    "info",
                )
                return redirect(url_for("candidate.profile"))

            # Se está DESATIVADO e quer ATIVAR: valida os dados obrigatórios.
            required_personal = [
                "cpf",
                "cep",  # ✅ se você quer CEP obrigatório para ativar (recomendado)
                "address",
                "neighborhood",
                "house_number",
                "city",
                "state",
                "birthdate",
                "phone",
                "gender",
            ]

            missing_personal = [
                field for field in required_personal
                if getattr(profile, field, None) in (None, "", 0)
            ]

            if missing_personal:
                flash(
                    "Para ativar seu perfil, preencha todos os campos em 'Meus Dados'.",
                    "warning",
                )
                return redirect(url_for("candidate.personal_data"))

            required_professional = [
                "profession",
                "education_level",
                "availability",
            ]
            missing_prof = [
                field for field in required_professional
                if getattr(profile, field, None) in (None, "", 0)
            ]

            if missing_prof:
                flash(
                    "Complete seu Perfil Profissional antes de ativar o perfil.",
                    "warning",
                )
                return redirect(url_for("candidate.profile"))

            profile.is_public = True
            db.session.commit()
            flash(
                "Seu perfil agora está ATIVADO e pode aparecer na home e nas buscas.",
                "success",
            )
            return redirect(url_for("candidate.profile"))


    # ----- % de completude do perfil profissional -----
    completion_fields = [
        "profession",
        "education_level",
        "availability",
        "skills",
        "languages",
        "bio",
    ]
    total = len(completion_fields)
    filled = sum(
        1
        for field in completion_fields
        if getattr(profile, field, None) not in (None, "", 0)
    )
    completion_percent = int((filled / total) * 100) if total else 0

    # ----- estatísticas rápidas -----
    applications_query = (
        Application.query.filter_by(candidate_id=profile.id)
        .order_by(Application.created_at.desc())
    )
    applications_count = applications_query.count()

    interviews_query = CompanyInterest.query.filter_by(candidate_id=profile.id)
    if hasattr(CompanyInterest, "status"):
        interviews_query = interviews_query.filter(
            CompanyInterest.status.in_(
                ["entrevista_marcada", "entrevista_confirmada", "confirmada"]
            )
        )
    interviews_count = interviews_query.count()

    interests_query = (
        CompanyInterest.query.filter_by(candidate_id=profile.id)
        .order_by(CompanyInterest.created_at.desc())
    )
    interests_count = interests_query.count()

    views_count = getattr(profile, "views_count", 0) or 0

    # ----- experiências -----
    experiences = profile.experiences.order_by(
        CandidateExperience.start_date.desc()
    ).all()

    last_experience = None
    if experiences:
        current = [e for e in experiences if e.is_current]
        if current:
            last_experience = current[0]
        else:
            last_experience = experiences[0]

    current_year = datetime.utcnow().year

    return render_template(
        "candidate/profile.html",
        profile=profile,
        form=form,
        completion_percent=completion_percent,
        applications_count=applications_count,
        interviews_count=interviews_count,
        views_count=views_count,
        interests_count=interests_count,
        experiences=experiences,
        last_experience=last_experience,
        current_year=current_year,
    )







@candidate_bp.route("/perfil/completar", methods=["GET", "POST"])
@login_required
@candidate_required
def complete_profile():
    """
    Todos os botões 'Completar Perfil' agora levam para a nova sessão /perfil.
    Mantemos essa rota só para compatibilidade.
    """
    return redirect(url_for("candidate.profile"))
    
@candidate_bp.route("/dados", methods=["GET", "POST"])
@login_required
@candidate_required
def personal_data():
    """
    Aba 'Meus Dados' com informações pessoais:
    nome, CPF, CEP, endereço, número, bairro, cidade, estado, telefone, nascimento, sexo.
    """
    profile = current_user.candidate_profile

    if not profile:
        profile = CandidateProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    form = CandidateProfileForm()  # só pra CSRF

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if full_name:
            current_user.full_name = full_name

        # --- NOVO: CEP ---
        profile.cep = request.form.get("cep", "").strip() or None

        profile.cpf = request.form.get("cpf", "").strip() or None
        profile.address = request.form.get("address", "").strip() or None
        profile.house_number = request.form.get("house_number", "").strip() or None
        profile.city = request.form.get("city", "").strip() or None
        profile.state = request.form.get("state", "").strip() or None
        profile.neighborhood = request.form.get("neighborhood", "").strip() or None
        profile.phone = request.form.get("phone", "").strip() or None

        # Data de nascimento (input type="date" = YYYY-MM-DD)
        birth_str = request.form.get("birthdate", "").strip()
        if birth_str:
            try:
                profile.birthdate = datetime.strptime(birth_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Sexo
        gender = request.form.get("gender", "").strip()
        profile.gender = gender or None  # 'M', 'F' ou None

        db.session.commit()
        flash("Dados pessoais atualizados com sucesso!", "success")
        return redirect(url_for("candidate.personal_data"))

    # ----- % de completude geral -----
    completion_fields = [
        "city",
        "phone",
        "profession",
        "experience_years",
        "skills",
        "bio",
    ]
    total = len(completion_fields)
    filled = sum(
        1
        for field in completion_fields
        if getattr(profile, field, None) not in (None, "", 0)
    )
    completion_percent = int((filled / total) * 100) if total else 0

    # ----- estatísticas rápidas -----
    applications_query = (
        Application.query.filter_by(candidate_id=profile.id)
        .order_by(Application.created_at.desc())
    )
    applications_count = applications_query.count()

    interviews_query = CompanyInterest.query.filter_by(candidate_id=profile.id)
    if hasattr(CompanyInterest, "status"):
        interviews_query = interviews_query.filter(
            CompanyInterest.status.in_(
                ["entrevista_marcada", "entrevista_confirmada", "confirmada"]
            )
        )
    interviews_count = interviews_query.count()

    interests_query = (
        CompanyInterest.query.filter_by(candidate_id=profile.id)
        .order_by(CompanyInterest.created_at.desc())
    )
    interests_count = interests_query.count()

    views_count = getattr(profile, "views_count", 0) or 0

    return render_template(
        "candidate/personal_data.html",
        profile=profile,
        form=form,
        completion_percent=completion_percent,
        applications_count=applications_count,
        interviews_count=interviews_count,
        interests_count=interests_count,
        views_count=views_count,
    )





# -------------------------------------------------------------------
# CANDIDATAR EM UMA VAGA
# -------------------------------------------------------------------
from datetime import datetime  # garante que isso esteja no topo do arquivo

@candidate_bp.route("/vagas/<int:job_id>/candidatar")
@login_required
@candidate_required
def apply(job_id):
    job = Job.query.get_or_404(job_id)
    profile = current_user.candidate_profile

    # precisa ter perfil completo
    if not profile.is_completed:
        flash("Complete seu perfil profissional antes de se candidatar.", "warning")
        return redirect(url_for("candidate.profile"))

    # ---- LIMITE DE 3 CANDIDATURAS POR MÊS PARA NÃO-PREMIUM ----
    if not current_user.is_premium:
        now = datetime.utcnow()
        start_of_month = datetime(now.year, now.month, 1)

        monthly_count = (
            Application.query
            .filter(
                Application.candidate_id == profile.id,
                Application.created_at >= start_of_month,
            )
            .count()
        )

        if monthly_count >= 3:
            flash(
                "Você já realizou o limite de 3 candidaturas gratuitas neste mês. "
                "Torne-se Premium para se candidatar ilimitadamente.",
                "warning",
            )
            return redirect(url_for("candidate.applications"))

    # já se candidatou a essa vaga?
    existing = Application.query.filter_by(
        candidate_id=profile.id, job_id=job.id
    ).first()
    if existing:
        flash("Você já se candidatou a esta vaga.", "info")
        return redirect(url_for("candidate.applications"))

    # cria candidatura
    application = Application(candidate_id=profile.id, job_id=job.id)
    db.session.add(application)

    # Notificação para a empresa
    if job.company_profile and job.company_profile.user:
        notif = Notification(
            user_id=job.company_profile.user.id,
            message=f"Novo candidato na vaga {job.title}.",
            type="nova_candidatura",
        )
        db.session.add(notif)

    db.session.commit()

    flash(
        "Você se candidatou a essa vaga! "
        "Suas candidaturas aparecerão na sessão 'Candidaturas' do seu painel.",
        "success",
    )
    return redirect(url_for("candidate.applications"))

    
    
@candidate_bp.route("/candidaturas/<int:application_id>/cancelar", methods=["POST"])
@login_required
@candidate_required
def cancel_application(application_id):
    """Candidato cancela (descandidata) enquanto ainda não há entrevista marcada."""
    profile = current_user.candidate_profile
    application = Application.query.get_or_404(application_id)

    if application.candidate_id != profile.id:
        flash("Candidatura não pertence a você.", "danger")
        return redirect(url_for("candidate.applications"))

    # Só deixa cancelar se não tiver entrevista marcada
    if application.interview_datetime is not None or application.status == "entrevista_marcada":
        flash(
            "Não é possível descandidatar após a entrevista ser marcada.",
            "warning",
        )
        return redirect(url_for("candidate.applications"))

    # Mantém o registro por histórico (em vez de deletar)
    application.status = "cancelada_pelo_candidato"
    db.session.commit()
    flash("Você se descandidatou dessa vaga.", "info")
    return redirect(url_for("candidate.applications"))




# -------------------------------------------------------------------
# CANDIDATURAS
# -------------------------------------------------------------------
@candidate_bp.route("/candidaturas")
@login_required
@candidate_required
def applications():
    profile = current_user.candidate_profile

    if not profile:
        flash("Crie seu perfil de candidato primeiro.", "warning")
        return redirect(url_for("candidate.profile"))

    applications_query = (
        Application.query.filter_by(candidate_id=profile.id)
        .order_by(Application.created_at.desc())
    )

    # NÃO mostrar aqui as que já estão em fase de entrevista/oferta
    if hasattr(Application, "status"):
        interview_statuses = ["entrevista_marcada", "entrevista_confirmada", "entrevista_realizada", "oferta"]
        applications_query = applications_query.filter(
            ~Application.status.in_(interview_statuses)
        )

    applications = applications_query.all()
    applications_count = applications_query.count()

    # % completude (igual você já usa)
    completion_fields = [
        "city",
        "phone",
        "profession",
        "experience_years",
        "skills",
        "bio",
    ]
    total = len(completion_fields)
    filled = sum(
        1
        for field in completion_fields
        if getattr(profile, field, None) not in (None, "", 0)
    )
    completion_percent = int((filled / total) * 100) if total else 0

    # entrevistas (contagem)
    if hasattr(Application, "status"):
        interviews_statuses = ["entrevista_marcada", "entrevista_confirmada", "entrevista_realizada", "oferta"]
        interviews_count = (
            Application.query.filter(
                Application.candidate_id == profile.id,
                Application.status.in_(interviews_statuses),
            ).count()
        )
    else:
        interviews_count = 0

    interests_query = (
        CompanyInterest.query.filter_by(candidate_id=profile.id)
        .order_by(CompanyInterest.created_at.desc())
    )
    interests_count = interests_query.count()

    views_count = getattr(profile, "views_count", 0) or 0

    return render_template(
        "candidate/applications.html",
        profile=profile,
        applications=applications,
        completion_percent=completion_percent,
        applications_count=applications_count,
        interviews_count=interviews_count,
        interests_count=interests_count,
        views_count=views_count,
    )



# -------------------------------------------------------------------
# ENTREVISTAS
# -------------------------------------------------------------------
@candidate_bp.route("/entrevistas")
@login_required
@candidate_required
def interviews():
    """Lista de entrevistas agendadas para o candidato."""
    profile = current_user.candidate_profile

    if not profile:
        flash("Crie seu perfil de candidato primeiro.", "warning")
        return redirect(url_for("candidate.profile"))

    # entrevistas = candidaturas em certos status
    interviews_statuses = ["entrevista_marcada", "entrevista_confirmada", "entrevista_realizada", "oferta"]

    interviews = (
        Application.query
        .filter(
            Application.candidate_id == profile.id,
            Application.status.in_(interviews_statuses),
        )
        .order_by(Application.interview_datetime.desc().nullslast())
        .all()
    )

    # estatísticas para os cards do topo / header
    applications_count = (
        Application.query.filter_by(candidate_id=profile.id).count()
    )

    interviews_count = len(interviews)

    interests_count = (
        CompanyInterest.query.filter_by(candidate_id=profile.id).count()
    )

    views_count = getattr(profile, "views_count", 0) or 0

    # completude
    completion_fields = [
        "city",
        "phone",
        "profession",
        "experience_years",
        "skills",
        "bio",
    ]
    total = len(completion_fields)
    filled = sum(
        1
        for field in completion_fields
        if getattr(profile, field, None) not in (None, "", 0)
    )
    completion_percent = int((filled / total) * 100) if total else 0

    return render_template(
        "candidate/interviews.html",
        profile=profile,
        interviews=interviews,
        completion_percent=completion_percent,
        applications_count=applications_count,
        interviews_count=interviews_count,
        interests_count=interests_count,
        views_count=views_count,
    )

@candidate_bp.route("/entrevistas/<int:application_id>/confirmar", methods=["POST"])
@login_required
@candidate_required
def confirm_interview(application_id):
    """Candidato confirma presença na entrevista."""
    app_obj = Application.query.get_or_404(application_id)
    profile = current_user.candidate_profile

    # segurança: a candidatura tem que ser dele
    if app_obj.candidate_id != profile.id:
        flash("Você não tem permissão para confirmar esta entrevista.", "danger")
        return redirect(url_for("candidate.interviews"))

    app_obj.candidate_confirmed = True
    # se quiser mudar o status também:
    if app_obj.status == "entrevista_marcada":
        app_obj.status = "entrevista_confirmada"

    db.session.commit()
    flash("Presença confirmada com sucesso. Boa entrevista! 🚀", "success")
    return redirect(url_for("candidate.interviews"))


# -------------------------------------------------------------------
# CONVITES / INTERESSES
# -------------------------------------------------------------------
@candidate_bp.route("/convites")
@login_required
@candidate_required
def interests():
    profile = current_user.candidate_profile
    interests = (
        CompanyInterest.query.filter_by(candidate_id=profile.id)
        .order_by(CompanyInterest.created_at.desc())
        .all()
    )
    return render_template("candidate/interests.html", interests=interests)


@candidate_bp.route("/convites/<int:interest_id>/ver")
@login_required
@candidate_required
def view_interest(interest_id):
    """Detalhe de um convite / interesse de empresa."""
    interest = CompanyInterest.query.get_or_404(interest_id)
    if interest.candidate_id != current_user.candidate_profile.id:
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("candidate.interests"))

    return render_template("candidate/interest_detail.html", interest=interest)


@candidate_bp.route("/convites/<int:interest_id>/confirmar")
@login_required
@candidate_required
def confirm_interest(interest_id):
    """Confirma presença em uma entrevista (CompanyInterest)."""
    interest = CompanyInterest.query.get_or_404(interest_id)
    if interest.candidate_id != current_user.candidate_profile.id:
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("candidate.interests"))

    interest.candidate_confirmed = True
    if hasattr(CompanyInterest, "status"):
        interest.status = "entrevista_confirmada"

    db.session.commit()
    flash("Presença confirmada. Boa entrevista!", "success")
    return redirect(url_for("candidate.interviews"))


# -------------------------------------------------------------------
# CONFIGURAÇÕES
# -------------------------------------------------------------------
from werkzeug.security import check_password_hash, generate_password_hash

@candidate_bp.route("/configuracoes", methods=["GET", "POST"])
@login_required
@candidate_required
def settings():
    """Configurações do candidato (aba Configurações)."""
    profile = current_user.candidate_profile

    if not profile:
        flash("Crie seu perfil de candidato primeiro.", "warning")
        return redirect(url_for("candidate.profile"))

    # form só para CSRF
    form = CandidateProfileForm()

    if request.method == "POST":
        action = request.form.get("action")

        # --- Atualizar e-mail ---
        if action == "update_email":
            new_email = request.form.get("email", "").strip()
            if not new_email:
                flash("Informe um e-mail válido.", "warning")
            else:
                current_user.email = new_email
                db.session.commit()
                flash("E-mail atualizado com sucesso!", "success")
            return redirect(url_for("candidate.settings"))

        # --- Atualizar telefone ---
        if action == "update_phone":
            new_phone = request.form.get("phone", "").strip()
            profile.phone = new_phone or None
            db.session.commit()
            flash("Telefone atualizado com sucesso!", "success")
            return redirect(url_for("candidate.settings"))

        # --- Atualizar senha ---
        if action == "update_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            # validações básicas
            if not current_password or not new_password or not confirm_password:
                flash("Preencha todos os campos de senha.", "warning")
                return redirect(url_for("candidate.settings"))

            if new_password != confirm_password:
                flash("A nova senha e a confirmação não conferem.", "warning")
                return redirect(url_for("candidate.settings"))

            if len(new_password) < 6:
                flash("A nova senha deve ter pelo menos 6 caracteres.", "warning")
                return redirect(url_for("candidate.settings"))

            # verifica senha atual
            senha_ok = False

            # se o modelo User tiver método check_password / set_password
            if hasattr(current_user, "check_password"):
                if current_user.check_password(current_password):
                    senha_ok = True
                    if hasattr(current_user, "set_password"):
                        current_user.set_password(new_password)
                    else:
                        # fallback: assume atributo password_hash
                        current_user.password_hash = generate_password_hash(new_password)

            # fallback: usa password_hash direto
            elif hasattr(current_user, "password_hash"):
                if check_password_hash(current_user.password_hash, current_password):
                    senha_ok = True
                    current_user.password_hash = generate_password_hash(new_password)

            if not senha_ok:
                flash("Senha atual incorreta.", "danger")
                return redirect(url_for("candidate.settings"))

            db.session.commit()
            flash("Senha alterada com sucesso!", "success")
            return redirect(url_for("candidate.settings"))

    # ----- % de completude -----
    completion_fields = [
        "city",
        "phone",
        "profession",
        "experience_years",
        "skills",
        "bio",
    ]
    total = len(completion_fields)
    filled = sum(
        1
        for field in completion_fields
        if getattr(profile, field, None) not in (None, "", 0)
    )
    completion_percent = int((filled / total) * 100) if total else 0

    # ----- estatísticas -----
    applications_query = (
        Application.query.filter_by(candidate_id=profile.id)
        .order_by(Application.created_at.desc())
    )
    applications_count = applications_query.count()

    interviews_query = CompanyInterest.query.filter_by(candidate_id=profile.id)
    if hasattr(CompanyInterest, "status"):
        interviews_query = interviews_query.filter(
            CompanyInterest.status.in_(
                ["entrevista_marcada", "entrevista_confirmada", "confirmada"]
            )
        )
    interviews_count = interviews_query.count()

    interests_query = (
        CompanyInterest.query.filter_by(candidate_id=profile.id)
        .order_by(CompanyInterest.created_at.desc())
    )
    interests_count = interests_query.count()

    views_count = getattr(profile, "views_count", 0) or 0

    return render_template(
        "candidate/settings.html",
        profile=profile,
        form=form,
        completion_percent=completion_percent,
        applications_count=applications_count,
        interviews_count=interviews_count,
        interests_count=interests_count,
        views_count=views_count,
    )



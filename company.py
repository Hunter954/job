from datetime import datetime
from functools import wraps
import re

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os

from extensions import db
from models import (
    User,
    CompanyProfile,
    CandidateProfile,
    CandidateExperience,
    Job,
    Application,
    CompanyInterest,
    Notification,
)

from forms import CompanyProfileForm

# Blueprint da empresa
company_bp = Blueprint("company", __name__, template_folder="templates")


def _save_company_logo(file_storage):
    """Salva logo em /static/uploads/companies e retorna o filename."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    filename = secure_filename(file_storage.filename)
    if not filename:
        return None
    upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads", "companies")
    os.makedirs(upload_dir, exist_ok=True)
    # evita colisão simples
    base, ext = os.path.splitext(filename)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{base}_{stamp}{ext}" if ext else f"{base}_{stamp}"
    file_storage.save(os.path.join(upload_dir, filename))
    return filename

# --- Match por vagas (recomendação baseada nas vagas ativas da empresa) ---
def _extract_keywords(text: str):
    if not text:
        return set()
    words = re.findall(r"\w+", str(text).lower())
    stop = {
        "de","da","do","das","dos","a","o","e","em","para","com",
        "na","no","nas","nos","que","por","um","uma","ao","aos","às",
        "as","os","se","sua","seu","suas","seus","como","mais","menos"
    }
    return {w for w in words if w not in stop and len(w) > 2}


def _candidate_matches_jobs(candidate, jobs):
    job_kw = set()
    for job in jobs:
        job_kw |= _extract_keywords(getattr(job, "title", "") or "")
        job_kw |= _extract_keywords(getattr(job, "description", "") or "")
        job_kw |= _extract_keywords(getattr(job, "requirements", "") or "")

    if not job_kw:
        return False

    cand_text = " ".join([
        getattr(candidate, "profession", "") or "",
        getattr(candidate, "skills", "") or "",
        getattr(candidate, "bio", "") or "",
    ])
    cand_kw = _extract_keywords(cand_text)
    return len(job_kw.intersection(cand_kw)) > 0



def company_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "company":
            flash("Acesso permitido apenas para empresas.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    return wrapper


@company_bp.route("/dashboard")
@login_required
@company_required
def dashboard():
    """
    Painel principal da EMPRESA (Visão Geral).

    - Cards de métricas (vagas, candidaturas, interesses)
    - Lista de candidatos interessados (CompanyInterest)
    - Candidatos recomendados (candidatos públicos em destaque)
    """
    profile = current_user.company_profile
    if not profile:
        flash("Complete o perfil da sua empresa primeiro.", "warning")
        return redirect(url_for("company.profile"))

    # ---------- Métricas de vagas ----------
    jobs_query = Job.query.filter_by(company_id=profile.id)
    total_jobs_count = jobs_query.count()
    active_jobs_count = jobs_query.filter_by(is_active=True).count()

    # Últimas vagas cadastradas
    recent_jobs = jobs_query.order_by(Job.created_at.desc()).limit(5).all()

    # ---------- Candidaturas recebidas ----------
    applications_count = (
        Application.query.join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == profile.id)
        .count()
    )

    # ---------- Candidatos interessados ----------
    interests_query = (
        CompanyInterest.query.filter_by(company_id=profile.id)
        .order_by(CompanyInterest.created_at.desc())
    )
    interests = interests_query.limit(20).all()
    interests_count = interests_query.count()

    # ---------- Candidatos recomendados (match com vagas ativas) ----------
    active_jobs = Job.query.filter_by(company_id=profile.id, is_active=True).all()

    recommended_candidates = (
        CandidateProfile.query
        .filter_by(is_public=True)
        .all()
    )
    # filtra por match real com as vagas ativas
    recommended_candidates = [c for c in recommended_candidates if _candidate_matches_jobs(c, active_jobs)]
    # limita a 4 (mesmo comportamento visual)
    recommended_candidates = recommended_candidates[:4]

    # ---------- Entrevistas ----------
    interviews_count = (
        Application.query.join(Job, Application.job_id == Job.id)
        .filter(
            Job.company_id == profile.id,
            Application.status.in_(["entrevista_marcada", "entrevista_realizada", "interview", "oferta"]),
        )
        .count()
    )


    # ---------- Dados auxiliares para o modal de perfil (CV) ----------
    def _calc_age(birthdate):
        if not birthdate:
            return None
        try:
            today = datetime.utcnow().date()
            bd = birthdate if hasattr(birthdate, "year") else None
            if not bd:
                return None
            return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        except Exception:
            return None

    def _mask_name(full_name: str | None):
        if not full_name:
            return "Candidato"
        parts = [p for p in full_name.split() if p.strip()]
        if len(parts) == 0:
            return "Candidato"
        if len(parts) == 1:
            return parts[0]
        first = parts[0]
        last_initial = parts[-1][0]
        return f"{first} {last_initial}******"

    EDUCATION_MAP = {
        "fundamental": "Ensino Fundamental",
        "medio": "Ensino Médio",
        "médio": "Ensino Médio",
        "tecnico": "Curso Técnico",
        "técnico": "Curso Técnico",
        "superior": "Ensino Superior",
        "graduacao": "Ensino Superior",
        "graduação": "Ensino Superior",
        "pos": "Pós-graduação",
        "pós": "Pós-graduação",
        "pos_graduacao": "Pós-graduação",
        "mestrado": "Mestrado",
        "doutorado": "Doutorado",
    }

    candidate_ages = {}
    masked_names = {}
    education_display = {}
    candidate_experiences = {}

    for c in recommended_candidates:
        # idade
        candidate_ages[c.id] = _calc_age(getattr(c, "birthdate", None))

        # nome (premium vê completo; não-premium vê mascarado)
        full_name = None
        if getattr(c, "user", None) and getattr(c.user, "full_name", None):
            full_name = c.user.full_name
        masked_names[c.id] = _mask_name(full_name)

        # escolaridade (mostra o texto completo digitado, se existir)
        edu_text = getattr(c, "education", None) or getattr(c, "schooling", None)
        if edu_text:
            education_display[c.id] = edu_text
        else:
            level = (getattr(c, "education_level", None) or "").strip()
            education_display[c.id] = EDUCATION_MAP.get(level.lower(), level)

        # experiências
        exps = (
            CandidateExperience.query
            .filter_by(candidate_id=c.id)
            .order_by(CandidateExperience.start_date.desc().nullslast(), CandidateExperience.id.desc())
            .all()
        )
        candidate_experiences[c.id] = exps

    current_year = datetime.utcnow().year

    return render_template(
        "company/dashboard.html",
        profile=profile,
        jobs_count=total_jobs_count,
        interviews_count=interviews_count,
        # métricas
        total_jobs_count=total_jobs_count,
        active_jobs_count=active_jobs_count,
        applications_count=applications_count,
        interests_count=interests_count,
        # listas
        recent_jobs=recent_jobs,
        interests=interests,
        recommended_candidates=recommended_candidates,
        # utilidades
        # modal CV
        is_premium=getattr(current_user, 'is_premium', False),
        candidate_ages=candidate_ages,
        masked_names=masked_names,
        education_display=education_display,
        candidate_experiences=candidate_experiences,
        current_year=current_year,
    )


@company_bp.route("/candidatos")
@login_required
@company_required
def candidates():
    """Lista de candidatos que se candidataram às vagas da empresa."""
    profile = current_user.company_profile
    if not profile:
        flash("Complete o perfil da empresa antes de gerenciar candidatos.", "warning")
        return redirect(url_for("company.dashboard"))

    # todas as candidaturas para vagas dessa empresa
    applications = (
        Application.query
        .join(Job, Application.job_id == Job.id)
        .filter(Job.company_id == profile.id)
        .order_by(Application.created_at.desc())
        .all()
    )

    # contadores pra cards do topo (se você já usa em outras telas)
    total_jobs = Job.query.filter_by(company_id=profile.id).count()
    total_apps = len(applications)

    interviews_count = (
        Application.query
        .join(Job, Application.job_id == Job.id)
        .filter(
            Job.company_id == profile.id,
            Application.status.in_(["entrevista_marcada", "entrevista_realizada", "oferta"]),
        )
        .count()
    )

    return render_template(
        "company/candidates.html",
        profile=profile,
        applications=applications,
        total_jobs=total_jobs,
        total_apps=total_apps,
        interviews_count=interviews_count,
    )


@company_bp.route("/entrevistas")
@login_required
@company_required
def interviews():
    """Aba Entrevistas: lista candidaturas com entrevista marcada/realizada."""
    profile = current_user.company_profile
    if not profile:
        flash("Complete o perfil da empresa antes de acessar entrevistas.", "warning")
        return redirect(url_for("company.dashboard"))

    interviews = (
        Application.query
        .join(Job, Application.job_id == Job.id)
        .filter(
            Job.company_id == profile.id,
            Application.status.in_(
                [
                    "entrevista_marcada",
                    "entrevista_realizada",
                    "interview",
                    "oferta",
                ]
            ),
        )
        .order_by(Application.interview_datetime.desc().nullslast(), Application.created_at.desc())
        .all()
    )

    return render_template("company/interviews.html", profile=profile, interviews=interviews)


@company_bp.route("/candidaturas/<int:application_id>/agendar", methods=["POST"])
@login_required
@company_required
def schedule_application_interview(application_id):
    """Empresa agenda entrevista para uma candidatura (candidato se candidatou em uma vaga)."""
    application = Application.query.get_or_404(application_id)
    company_profile = current_user.company_profile

    # segurança: a vaga tem que ser da empresa logada
    if not application.job or application.job.company_id != company_profile.id:
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("company.candidates"))

    date_str = request.form.get("interview_date")  # formato YYYY-MM-DD
    time_str = request.form.get("interview_time")  # formato HH:MM
    location = request.form.get("interview_location", "").strip()

    if not date_str or not time_str or not location:
        flash("Preencha data, horário e local da entrevista.", "warning")
        return redirect(url_for("company.candidates"))

    try:
        interview_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        flash("Data ou horário inválidos.", "danger")
        return redirect(url_for("company.candidates"))

    application.interview_datetime = interview_dt
    application.interview_location = location
    application.status = "entrevista_marcada"

    # notificar candidato
    if application.candidate_profile and application.candidate_profile.user:
        notif = Notification(
            user_id=application.candidate_profile.user.id,
            message=f"Sua candidatura na vaga {application.job.title} teve entrevista marcada.",
            type="entrevista_marcada",
        )
        db.session.add(notif)

    db.session.commit()
    flash("Entrevista marcada com sucesso!", "success")
    return redirect(url_for("company.candidates"))


@company_bp.route("/candidatos/<int:candidate_id>/contatar", methods=["POST"])
@login_required
@company_required
def contact_candidate(candidate_id):
    """
    Empresa clica em 'Contatar' em um candidato na home.
    Cria um CompanyInterest e uma notificação para o candidato.
    """
    company_profile = current_user.company_profile
    if not company_profile:
        flash("Complete o perfil da sua empresa antes de contatar candidatos.", "warning")
        return redirect(url_for("company.dashboard"))

    candidate = CandidateProfile.query.get_or_404(candidate_id)

    # evita duplicar interesse
    existing = CompanyInterest.query.filter_by(
        company_id=company_profile.id,
        candidate_id=candidate.id,
    ).first()
    if existing:
        flash("Você já demonstrou interesse neste candidato.", "info")
        return redirect(url_for("main.index", _anchor="profissionais"))

    interest = CompanyInterest(
        company_id=company_profile.id,
        candidate_id=candidate.id,
        status="convite_enviado",
        notes="Interesse enviado pela home (botão Contatar).",
    )
    db.session.add(interest)

    # notificação para o candidato
    if candidate.user:
        notif = Notification(
            user_id=candidate.user.id,
            message=f"A empresa {current_user.company_name or 'uma empresa'} demonstrou interesse no seu perfil.",
            type="interesse_empresa",
        )
        db.session.add(notif)

    db.session.commit()
    flash("Seu interesse foi enviado para o candidato.", "success")
    return redirect(url_for("main.index", _anchor="profissionais"))


# ========= SESSÃO VAGAS =========
@company_bp.route("/vagas", methods=["GET", "POST"])
@login_required
@company_required
def jobs():
    """Sessão de Vagas: cadastro, edição e listagem das vagas da empresa."""
    profile = current_user.company_profile
    if not profile:
        profile = CompanyProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    jobs_query = Job.query.filter_by(company_id=profile.id).order_by(Job.created_at.desc())
    jobs_list = jobs_query.all()
    jobs_count = jobs_query.count()

    edit_job = None
    edit_id = request.args.get("edit", type=int)
    if edit_id:
        edit_job = Job.query.get_or_404(edit_id)
        if edit_job.company_id != profile.id:
            flash("Você não tem permissão para editar esta vaga.", "danger")
            return redirect(url_for("company.jobs") + "#jobs-list")

    def _parse_salary(raw: str):
        if not raw:
            return None, None
        s = raw.strip()
        # aceita "R$ 1.620,00" ou "1620" etc.
        s = s.replace("R$", "").replace("\u00a0", " ").strip()
        # se tiver só dígitos, trata como reais (ex: 1620)
        only_digits = re.sub(r"\D", "", s)
        if only_digits and re.fullmatch(r"\d+", s.replace(" ", "")) or re.fullmatch(r"\d+", only_digits):
            # nosso input no front formata em centavos, então aqui priorizamos o valor já formatado.
            pass
        # remove separador de milhar e ajusta decimal
        s = s.replace(".", "").replace(",", ".")
        try:
            v = float(s)
            return v, v
        except Exception:
            return None, None

    if request.method == "POST":
        if not profile.is_approved:
            flash(
                "Sua empresa ainda não foi aprovada pelo Admin. Assim que aprovada, você poderá cadastrar e publicar vagas.",
                "warning",
            )
            return redirect(url_for("company.jobs") + "#job-form")

        title = request.form.get("title", "").strip()
        city = request.form.get("city", "").strip()
        employment_type = request.form.get("employment_type", "").strip() or None
        work_regime = request.form.get("work_regime", "").strip() or None
        salary_range = request.form.get("salary_range", "").strip()
        description = request.form.get("description", "").strip() or None
        job_id = request.form.get("job_id", type=int)

        if not title or not city:
            flash("Informe pelo menos a função e a cidade da vaga.", "warning")
            return redirect(url_for("company.jobs") + "#job-form")

        salary_min, salary_max = _parse_salary(salary_range)

        if job_id:
            job = Job.query.get_or_404(job_id)
            if job.company_id != profile.id:
                flash("Você não tem permissão para editar esta vaga.", "danger")
                return redirect(url_for("company.jobs") + "#jobs-list")

            job.title = title
            job.city = city
            job.employment_type = employment_type
            job.work_regime = work_regime
            job.salary_min = salary_min
            job.salary_max = salary_max
            job.description = description

            db.session.commit()
            flash("Vaga atualizada com sucesso!", "success")
            return redirect(url_for("company.jobs") + f"#job-card-{job.id}")

        # criar nova vaga
        job = Job(
            company_id=profile.id,
            title=title,
            city=city,
            employment_type=employment_type,
            work_regime=work_regime,
            salary_min=salary_min,
            salary_max=salary_max,
            description=description,
            is_active=True,
        )
        db.session.add(job)
        db.session.commit()
        flash("Vaga cadastrada com sucesso!", "success")
        return redirect(url_for("company.jobs") + f"#job-card-{job.id}")

    return render_template(
        "company/jobs.html",
        profile=profile,
        jobs=jobs_list,
        jobs_count=jobs_count,
        edit_job=edit_job
    )


@company_bp.route("/vagas/<int:job_id>/delete", methods=["POST"])
@login_required
@company_required
def delete_job(job_id):
    """Exclui uma vaga da empresa."""
    profile = current_user.company_profile
    job = Job.query.get_or_404(job_id)

    if not profile or job.company_id != profile.id:
        flash("Você não tem permissão para excluir esta vaga.", "danger")
        return redirect(url_for("company.jobs") + "#jobs-list")

    db.session.delete(job)
    db.session.commit()
    flash("Vaga excluída com sucesso.", "success")
    return redirect(url_for("company.jobs") + "#jobs-list")


@company_bp.route("/vagas/<int:job_id>/toggle", methods=["POST"])
@login_required
@company_required
def toggle_job(job_id):
    """Liga/desliga a vaga para aparecer (ou não) na home/buscas."""
    profile = current_user.company_profile
    job = Job.query.get_or_404(job_id)

    if job.company_id != profile.id:
        flash("Você não tem permissão para alterar esta vaga.", "danger")
        return redirect(url_for("company.jobs"))

    job.is_active = not bool(job.is_active)
    db.session.commit()

    if job.is_active:
        flash("Vaga ativada. Ela voltará a aparecer nas listagens.", "success")
    else:
        flash("Vaga desativada. Ela não aparecerá mais na home nem nas buscas.", "info")

    return redirect(url_for("company.jobs"))
    
    
@company_bp.route("/configuracoes", methods=["GET", "POST"])
@login_required
@company_required
def settings():
    """Configurações da empresa (aba Configurações)."""
    profile = current_user.company_profile
    if not profile:
        profile = CompanyProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    # aqui depois você pode colocar troca de senha da empresa, dados de faturamento, etc
    return render_template("company/settings.html", profile=profile)


@company_bp.route("/empresa", methods=["GET", "POST"])
@login_required
@company_required
def company_data():
    """Dados da empresa (tela 'Empresa' do painel)."""
    profile = current_user.company_profile
    if not profile:
        profile = CompanyProfile(user_id=current_user.id, cnpj=f"pending-{current_user.id}")
        db.session.add(profile)
        db.session.commit()

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()

        # ---- Salvar apenas a foto/logomarca ----
        if action == "logo":
            logo_file = request.files.get("logo")
            saved = _save_company_logo(logo_file)
            if saved:
                profile.logo_filename = saved
                db.session.commit()
                flash("Logomarca atualizada!", "success")
            else:
                flash("Selecione uma imagem válida para enviar.", "warning")
            return redirect(url_for("company.company_data"))

        # ---- Salvar informações ----
        # Nome, email e CNPJ NÃO podem ser alterados aqui.
        profile.phone = (request.form.get("phone") or "").strip()
        profile.website = (request.form.get("website") or "").strip()
        profile.cep = (request.form.get("cep") or "").strip()
        profile.address = (request.form.get("address") or "").strip()
        profile.house_number = (request.form.get("house_number") or "").strip()
        profile.neighborhood = (request.form.get("neighborhood") or "").strip()
        profile.city = (request.form.get("city") or "").strip()
        profile.state = (request.form.get("state") or "").strip().upper()
        profile.segment = (request.form.get("segment") or "").strip()
        profile.company_size = (request.form.get("company_size") or "").strip()

        founded_year_raw = (request.form.get("founded_year") or "").strip()
        if founded_year_raw:
            if founded_year_raw.isdigit():
            profile.founded_year = int(founded_year_raw)
        else:
            flash("Ano de fundação inválido. Use apenas números (ex: 2018).", "warning")
            profile.founded_year = None

                flash("Ano de fundação inválido. Use apenas números (ex: 2018).", "warning")
        else:
            profile.founded_year = None

        profile.description = (request.form.get("description") or "").strip()
        profile.is_completed = True

        db.session.commit()
        flash("Dados da empresa atualizados!", "success")
        return redirect(url_for("company.company_data"))

    return render_template("company/company_data.html", profile=profile)


@company_bp.route("/perfil", methods=["GET", "POST"])
@login_required
@company_required
def profile():
    """Completar/editar perfil da empresa."""
    profile = current_user.company_profile
    if not profile:
        # fallback: em teoria é criado no registro. Mantemos um placeholder único.
        profile = CompanyProfile(user_id=current_user.id, cnpj=f"pending-{current_user.id}")
        db.session.add(profile)
        db.session.commit()

    form = CompanyProfileForm(obj=profile)
    if form.validate_on_submit():
        profile.address = form.address.data
        profile.city = form.city.data
        profile.phone = form.phone.data
        profile.website = form.website.data
        profile.description = form.description.data

        # upload logo (opcional)
        logo_file = request.files.get("logo")
        saved = _save_company_logo(logo_file)
        if saved:
            profile.logo_filename = saved

        profile.is_completed = True
        db.session.commit()
        flash("Perfil da empresa atualizado!", "success")
        return redirect(url_for("company.dashboard"))

    return render_template("company/complete_profile.html", form=form)

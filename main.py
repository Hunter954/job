from flask import Blueprint, render_template, abort
from sqlalchemy import func
from flask_login import current_user
from models import Job, CandidateProfile

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    # ✅ SOMENTE perfis ativados (is_public=True)
    candidates = (
        CandidateProfile.query
        .filter(CandidateProfile.is_public.is_(True))
        .order_by(CandidateProfile.id.desc())
        .limit(8)
        .all()
    )

    # ✅ Vagas ativas + sem "vaga fantasma" (título não vazio)
    jobs = (
        Job.query
        .filter(Job.is_active.is_(True))
        .filter(Job.title.isnot(None))
        .filter(func.trim(Job.title) != "")
        .order_by(Job.created_at.desc())
        .limit(8)
        .all()
    )

    return render_template("index.html", candidates=candidates, jobs=jobs)





@main_bp.route("/vagas")
def job_list():
    jobs = (
        Job.query
        .filter(Job.is_active.is_(True))
        .filter(Job.title.isnot(None))
        .filter(func.trim(Job.title) != "")
        .order_by(Job.is_sponsored.desc(), Job.created_at.desc())
        .all()
    )
    return render_template("jobs/list.html", jobs=jobs)


@main_bp.route("/vagas/<int:job_id>")
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    # Não permitir acessar vaga inativa ou 'fantasma'
    if not job.is_active or not job.title or not job.title.strip():
        abort(404)
    can_view_full = False
    if current_user.is_authenticated and current_user.role == "candidate" and current_user.is_premium:
        can_view_full = True
    return render_template("jobs/detail.html", job=job, can_view_full=can_view_full)

from functools import wraps

from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from models import User, CompanyProfile, CandidateProfile, Job, Application, Payment

from sqlalchemy import func


admin_bp = Blueprint("admin", __name__, template_folder="templates")


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Acesso permitido apenas para administradores.", "danger")
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)

    return wrapper


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    counts = {
        "users": User.query.count(),
        "candidates": User.query.filter_by(role="candidate").count(),
        "companies": User.query.filter_by(role="company").count(),
        "jobs": Job.query.count(),
        "applications": Application.query.count(),
        "premium": User.query.filter_by(is_premium=True).count(),
    }
    latest_jobs = Job.query.order_by(Job.created_at.desc()).limit(10).all()
    latest_users = User.query.order_by(User.created_at.desc()).limit(10).all()

    # Série 7 dias para gráficos (Chart.js)
    today = datetime.utcnow().date()
    start = today - timedelta(days=6)

    def _series(model, dt_field):
        rows = (
            db.session.query(func.date(dt_field), func.count())
            .filter(dt_field >= start)
            .group_by(func.date(dt_field))
            .order_by(func.date(dt_field))
            .all()
        )
        mapping = {r[0].isoformat(): int(r[1]) for r in rows}
        labels = [(start + timedelta(days=i)).isoformat() for i in range(7)]
        data = [mapping.get(d, 0) for d in labels]
        return labels, data

    labels, users_7d = _series(User, User.created_at)
    _, jobs_7d = _series(Job, Job.created_at)
    _, apps_7d = _series(Application, Application.created_at)

    charts = {
        "labels": labels,
        "users": users_7d,
        "jobs": jobs_7d,
        "applications": apps_7d,
    }
    return render_template(
        "admin/dashboard.html",
        counts=counts,
        latest_jobs=latest_jobs,
        latest_users=latest_users,
        charts=charts,
    )


@admin_bp.route("/usuarios")
@login_required
@admin_required
def users():
    role = request.args.get("role")
    q = User.query
    if role in {"candidate", "company", "admin"}:
        q = q.filter_by(role=role)
    users_list = q.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users_list, role=role)


@admin_bp.route("/usuarios/<int:user_id>/toggle-active", methods=["POST"])
@login_required
@admin_required
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Você não pode desativar seu próprio usuário.", "warning")
        return redirect(url_for("admin.users"))
    user.is_active = not bool(user.is_active)
    db.session.commit()
    flash("Status do usuário atualizado.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/usuarios/<int:user_id>/toggle-premium", methods=["POST"])
@login_required
@admin_required
def toggle_user_premium(user_id):
    user = User.query.get_or_404(user_id)
    user.is_premium = not bool(user.is_premium)
    db.session.commit()
    flash("Premium atualizado.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/vagas")
@login_required
@admin_required
def jobs():
    jobs_list = Job.query.order_by(Job.created_at.desc()).all()
    return render_template("admin/jobs.html", jobs=jobs_list)


@admin_bp.route("/vagas/<int:job_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_job(job_id):
    job = Job.query.get_or_404(job_id)
    job.is_active = not bool(job.is_active)
    db.session.commit()
    flash("Vaga atualizada.", "success")
    return redirect(request.referrer or url_for("admin.jobs"))


@admin_bp.route("/vagas/<int:job_id>/toggle-sponsored", methods=["POST"])
@login_required
@admin_required
def toggle_job_sponsored(job_id):
    job = Job.query.get_or_404(job_id)
    job.is_sponsored = not bool(job.is_sponsored)
    db.session.commit()
    flash("Destaque da vaga atualizado.", "success")
    return redirect(request.referrer or url_for("admin.jobs"))


@admin_bp.route("/vagas/<int:job_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    flash("Vaga removida.", "success")
    return redirect(request.referrer or url_for("admin.jobs"))


@admin_bp.route("/empresas")
@login_required
@admin_required
def companies():
    companies_list = CompanyProfile.query.order_by(CompanyProfile.id.desc()).all()
    return render_template("admin/companies.html", companies=companies_list)


@admin_bp.route("/empresas/<int:company_id>/toggle-approved", methods=["POST"])
@login_required
@admin_required
def toggle_company_approved(company_id):
    company = CompanyProfile.query.get_or_404(company_id)
    company.is_approved = not bool(company.is_approved)
    db.session.commit()
    flash("Status de aprovação da empresa atualizado.", "success")
    return redirect(request.referrer or url_for("admin.companies"))


@admin_bp.route("/candidatos")
@login_required
@admin_required
def candidates():
    candidates_list = CandidateProfile.query.order_by(CandidateProfile.id.desc()).all()
    return render_template("admin/candidates.html", candidates=candidates_list)


@admin_bp.route("/pagamentos")
@login_required
@admin_required
def payments():
    payments_list = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template("admin/payments.html", payments=payments_list)


@admin_bp.route("/pagamentos/<int:payment_id>/mark-paid", methods=["POST"])
@login_required
@admin_required
def mark_payment_paid(payment_id):
    pay = Payment.query.get_or_404(payment_id)
    if pay.status != "paid":
        pay.status = "paid"
        pay.paid_at = datetime.utcnow()
        # Ativa premium para o usuário
        user = User.query.get(pay.user_id)
        if user:
            user.is_premium = True
        db.session.commit()
    flash("Pagamento confirmado e Premium liberado.", "success")
    return redirect(request.referrer or url_for("admin.payments"))

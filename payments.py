import os
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Payment


payments_bp = Blueprint("payments", __name__, url_prefix="/premium")


def _brl_to_cents(value: str) -> int:
    try:
        # aceita "29,90" ou "29.90"
        v = float(value.replace(",", "."))
        return int(round(v * 100))
    except Exception:
        return 0


@payments_bp.route("/planos")
def plans():
    """Página pública com planos."""
    # valores simples (pode virar tabela Plan depois)
    return render_template(
        "premium/plans.html",
        candidate_monthly_cents=1990,
        company_monthly_cents=4990,
    )


@payments_bp.route("/assinar", methods=["POST"])
@login_required
def subscribe():
    """Cria uma cobrança Pix simplificada (manual)."""

    amount_cents = int(request.form.get("amount_cents", "0"))
    if amount_cents <= 0:
        flash("Valor inválido.", "danger")
        return redirect(url_for("payments.plans"))

    pix_key = os.getenv("PIX_KEY") or os.getenv("PIX_CHAVE") or ""
    if not pix_key:
        # ainda deixa criar, mas avisa
        flash(
            "PIX_KEY não configurada no servidor. Configure nas Variáveis do Railway para exibir a chave Pix.",
            "warning",
        )

    # payload básico (não é BR Code oficial, mas serve para cópia/cola manual)
    payload = f"PIX|{pix_key}|{amount_cents}|{current_user.email}|{uuid.uuid4()}"

    pay = Payment(
        user_id=current_user.id,
        amount_cents=amount_cents,
        status="pending",
        pix_key=pix_key,
        pix_payload=payload,
    )
    db.session.add(pay)
    db.session.commit()

    return redirect(url_for("payments.checkout", payment_id=pay.id))


@payments_bp.route("/checkout/<int:payment_id>")
@login_required
def checkout(payment_id: int):
    pay = Payment.query.get_or_404(payment_id)
    if pay.user_id != current_user.id and current_user.role != "admin":
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("main.index"))

    return render_template("premium/checkout.html", payment=pay)


@payments_bp.route("/status")
@login_required
def status():
    payments = (
        Payment.query.filter_by(user_id=current_user.id)
        .order_by(Payment.created_at.desc())
        .all()
    )
    return render_template("premium/status.html", payments=payments)

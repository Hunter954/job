import json
import os
import uuid
from datetime import datetime

import requests
from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app, abort
from flask_login import current_user, login_required

from extensions import db
from models import Payment, User


payments_bp = Blueprint("payments", __name__, url_prefix="/premium")

# Preços (BRL)
CANDIDATE_PRICE_CENTS = 990
COMPANY_PRICE_CENTS = 1990


def _safe_json_loads(s: str):
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


def _create_tribopay_charge(amount_cents: int, reference: str, description: str):
    """Cria cobrança Pix via TriboPay (modo API).

    Variáveis:
    - TRIBOPAY_API_KEY
    - TRIBOPAY_CREATE_CHARGE_URL

    Se não estiver configurado, retorna None.
    """
    api_key = os.getenv("TRIBOPAY_API_KEY")
    create_url = os.getenv("TRIBOPAY_CREATE_CHARGE_URL")

    if not api_key or not create_url:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "amount": round(amount_cents / 100, 2),
        "currency": "BRL",
        "reference": reference,
        "description": description,
        "expires_in": 1800,
    }

    resp = requests.post(create_url, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _tribopay_checkout_url_for_plan(plan: str) -> str:
    """Checkout link do produto na TriboPay.

    Você cria 2 produtos no painel e pega o link do checkout.

    Variáveis:
    - TRIBOPAY_PRODUCT_CANDIDATE_URL
    - TRIBOPAY_PRODUCT_COMPANY_URL
    """
    if plan == "candidate":
        return (os.getenv("TRIBOPAY_PRODUCT_CANDIDATE_URL") or "").strip()
    return (os.getenv("TRIBOPAY_PRODUCT_COMPANY_URL") or "").strip()


@payments_bp.route("/planos")
def plans():
    return render_template(
        "premium/plans.html",
        candidate_monthly_cents=CANDIDATE_PRICE_CENTS,
        company_monthly_cents=COMPANY_PRICE_CENTS,
    )


@payments_bp.route("/assinar", methods=["POST"])
@login_required
def subscribe():
    plan = request.form.get("plan")

    if plan not in {"candidate", "company"}:
        flash("Plano inválido.", "danger")
        return redirect(url_for("payments.plans"))

    amount_cents = CANDIDATE_PRICE_CENTS if plan == "candidate" else COMPANY_PRICE_CENTS

    # referência interna (vamos usar pra encontrar o Payment no webhook)
    reference = f"prem_{plan}_{current_user.id}_{uuid.uuid4().hex[:10]}"
    description = f"Premium {plan} - {current_user.email}"

    provider = "manual"
    charge_data = None

    # 0) Preferência: checkout de produto da TriboPay (mais simples e garante que o webhook dispare)
    checkout_url = _tribopay_checkout_url_for_plan(plan)

    # 1) Tenta API de Pix (se configurada)
    if not checkout_url:
        try:
            charge_data = _create_tribopay_charge(amount_cents, reference, description)
            if charge_data:
                provider = "tribopay"
        except Exception as e:
            current_app.logger.warning("TriboPay charge failed: %s", e)
            charge_data = None

    # 2) Fallback manual (PIX_KEY)
    pix_key = os.getenv("PIX_KEY") or os.getenv("PIX_CHAVE") or ""

    meta = {
        "provider": provider,
        "plan": plan,
        "reference": reference,
        "amount_cents": amount_cents,
        "tribopay": charge_data or {},
        "pix_key": pix_key,
        "checkout_url": checkout_url,
    }

    # Cria o registro local SEMPRE (para reconciliar via webhook)
    pay = Payment(
        user_id=current_user.id,
        amount_cents=amount_cents,
        status="pending",
        pix_key=pix_key,
        pix_payload=json.dumps(meta, ensure_ascii=False),
    )
    db.session.add(pay)
    db.session.commit()

    # Se tiver link de checkout, redireciona o usuário para pagar na TriboPay
    # Passamos referência para o webhook conseguir casar (quando a TriboPay suporta querystrings)
    if checkout_url:
        sep = "&" if "?" in checkout_url else "?"
        # Alguns checkouts aceitam parâmetros livres; se a TriboPay não usar, não atrapalha.
        redirect_url = (
            f"{checkout_url}{sep}external_reference={reference}&reference={reference}"
            f"&email={current_user.email}"
        )
        return redirect(redirect_url)

    # Se foi pela API, vai pro nosso checkout mostrar QR/brcode
    if provider == "tribopay":
        return redirect(url_for("payments.checkout", payment_id=pay.id))

    # Manual
    if not pix_key:
        flash(
            "PIX_KEY não configurada. Configure uma chave Pix nas Variáveis do Railway para o modo manual (ou configure a integração TriboPay).",
            "warning",
        )

    meta["brcode"] = f"PIX|{pix_key}|{amount_cents}|{current_user.email}|{reference}"
    pay.pix_payload = json.dumps(meta, ensure_ascii=False)
    db.session.commit()

    return redirect(url_for("payments.checkout", payment_id=pay.id))


@payments_bp.route("/checkout/<int:payment_id>")
@login_required
def checkout(payment_id: int):
    pay = Payment.query.get_or_404(payment_id)
    if pay.user_id != current_user.id and current_user.role != "admin":
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("main.index"))

    meta = _safe_json_loads(pay.pix_payload)

    tribo = (meta.get("tribopay") or {}) if isinstance(meta, dict) else {}

    brcode = (
        tribo.get("brcode")
        or tribo.get("pixCopiaECola")
        or tribo.get("copiaecola")
        or meta.get("brcode")
        or ""
    )

    qrcode = tribo.get("qrcode") or tribo.get("qrCode") or tribo.get("qrcodeImage") or ""

    return render_template(
        "premium/checkout.html",
        payment=pay,
        meta=meta,
        brcode=brcode,
        qrcode=qrcode,
    )


@payments_bp.route("/status")
@login_required
def status():
    payments = (
        Payment.query.filter_by(user_id=current_user.id)
        .order_by(Payment.created_at.desc())
        .all()
    )
    return render_template("premium/status.html", payments=payments)


@payments_bp.route("/tribopay/webhook", methods=["GET", "POST"])
def tribopay_webhook():
    # GET para teste/healthcheck
    if request.method == "GET":
        return {"ok": True, "message": "Webhook online"}, 200

    expected = os.getenv("TRIBOPAY_WEBHOOK_TOKEN")

    # aceita Bearer token ou token em querystring
    token = ""
    auth = request.headers.get("Authorization", "")
    if auth:
        token = auth.replace("Bearer", "").strip()
    if not token:
        token = request.args.get("token", "").strip()

    if expected and token != expected:
        return {"ok": False, "error": "unauthorized"}, 401

    data = request.get_json(silent=True)
    if not data:
        data = request.form.to_dict() or {}

    current_app.logger.info("TriboPay webhook payload: %s", data)

    status = (data.get("status") or data.get("payment_status") or data.get("situacao") or "").lower()
    reference = (
        data.get("reference")
        or data.get("ref")
        or data.get("external_reference")
        or data.get("externalReference")
        or data.get("referencia")
    )
    charge_id = data.get("id") or data.get("charge_id") or data.get("txid") or data.get("transaction_id")

    is_paid = status in {"paid", "pago", "approved", "aprovado", "confirmed", "confirmado", "completed", "concluido"}

    if not is_paid:
        return {"ok": True}, 200

    pay = None
    if reference:
        pay = (
            Payment.query.filter(Payment.pix_payload.ilike(f"%{reference}%"))
            .order_by(Payment.id.desc())
            .first()
        )

    if not pay and charge_id:
        pay = (
            Payment.query.filter(Payment.pix_payload.ilike(f"%{charge_id}%"))
            .order_by(Payment.id.desc())
            .first()
        )

    if not pay:
        current_app.logger.warning(
            "Webhook paid but payment not found. reference=%s charge_id=%s", reference, charge_id
        )
        return {"ok": True}, 200

    if pay.status != "paid":
        pay.status = "paid"
        pay.paid_at = datetime.utcnow()

        user = User.query.get(pay.user_id)
        if user:
            user.is_premium = True

        db.session.commit()

    return {"ok": True}, 200

import json
import os
import uuid
from datetime import datetime, timedelta

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
    """Cria cobrança Pix via TriboPay.

    Como a TriboPay pode mudar endpoints/contrato, este método é "config-driven":

    - TRIBOPAY_API_KEY: token
    - TRIBOPAY_CREATE_CHARGE_URL: endpoint completo para criar cobrança
      (ex.: https://.../charges)

    Espera que o endpoint retorne um JSON com alguns campos comuns, por exemplo:
    - id/charge_id/txid
    - brcode/pixCopiaECola
    - qrcode/qrcodeImage (base64 ou url)

    Se não estiver configurado, retorna None e o sistema cai no modo manual (PIX_KEY).
    """
    api_key = os.getenv("TRIBOPAY_API_KEY")
    create_url = os.getenv("TRIBOPAY_CREATE_CHARGE_URL")

    if not api_key or not create_url:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Payload genérico (ajuste se a documentação da TriboPay pedir outro formato)
    payload = {
        "amount": round(amount_cents / 100, 2),
        "currency": "BRL",
        "reference": reference,
        "description": description,
        "expires_in": 1800,  # 30min
    }

    resp = requests.post(create_url, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


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

    # referência interna
    reference = f"prem_{plan}_{current_user.id}_{uuid.uuid4().hex[:10]}"
    description = f"Premium {plan} - {current_user.email}"

    provider = "manual"
    charge_data = None

    # 1) Tenta TriboPay (automático)
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
    }

    if provider == "manual":
        if not pix_key:
            flash(
                "PIX_KEY não configurada. Configure uma chave Pix nas Variáveis do Railway para o modo manual (ou configure TRIBOPAY_API_KEY e TRIBOPAY_CREATE_CHARGE_URL para modo automático).",
                "warning",
            )
        # payload simples para copia/cola (modo manual)
        meta["brcode"] = f"PIX|{pix_key}|{amount_cents}|{current_user.email}|{reference}"

    pay = Payment(
        user_id=current_user.id,
        amount_cents=amount_cents,
        status="pending",
        pix_key=pix_key,
        pix_payload=json.dumps(meta, ensure_ascii=False),
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

    meta = _safe_json_loads(pay.pix_payload)

    # tenta extrair brcode/qrcode de formatos comuns
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


@payments_bp.route("/tribopay/webhook", methods=["POST"])
def tribopay_webhook():
    """Webhook para confirmação automática.

    Configure no painel da TriboPay para apontar para:
      https://SEU_DOMINIO/premium/tribopay/webhook

    E defina um token/segredo (se a TriboPay permitir) e coloque em:
      TRIBOPAY_WEBHOOK_TOKEN

    O handler aceita formatos diferentes. O importante é conseguir:
    - referência (reference) OU charge_id/txid
    - status pago
    """

    expected = os.getenv("TRIBOPAY_WEBHOOK_TOKEN")
    if expected:
        auth = request.headers.get("Authorization", "")
        # aceita "Bearer xxx" ou token direto
        token = auth.replace("Bearer", "").strip() if auth else ""
        if token != expected:
            abort(401)

    data = request.get_json(silent=True) or {}

    # tentativa de leitura bem tolerante
    status = (data.get("status") or data.get("payment_status") or "").lower()
    reference = data.get("reference") or data.get("ref") or data.get("external_reference")
    charge_id = data.get("id") or data.get("charge_id") or data.get("txid")

    is_paid = status in {"paid", "approved", "confirmed", "completed"}

    if not is_paid:
        return {"ok": True}, 200

    pay = None
    if reference:
        # busca pelo reference dentro do pix_payload (json string)
        pay = Payment.query.filter(Payment.pix_payload.ilike(f"%{reference}%")).order_by(Payment.id.desc()).first()

    if not pay and charge_id:
        pay = Payment.query.filter(Payment.pix_payload.ilike(f"%{charge_id}%")).order_by(Payment.id.desc()).first()

    if not pay:
        # não achou, mas não falha o webhook
        current_app.logger.warning("Webhook paid but payment not found. reference=%s charge_id=%s", reference, charge_id)
        return {"ok": True}, 200

    if pay.status != "paid":
        pay.status = "paid"
        pay.paid_at = datetime.utcnow()

        meta = _safe_json_loads(pay.pix_payload)
        plan = meta.get("plan") if isinstance(meta, dict) else None

        user = User.query.get(pay.user_id)
        if user:
            user.is_premium = True
            # opcional: você pode travar premium por role aqui
            # if plan == 'company' and user.role != 'company': ...

        db.session.commit()

    return {"ok": True}, 200

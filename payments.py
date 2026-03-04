import json
import os
import uuid
import base64
import io
from datetime import datetime, timedelta

import requests
from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app, abort, jsonify
from flask_login import current_user, login_required

from extensions import db
from models import Payment, User

try:
    import segno
except Exception:  # pragma: no cover
    segno = None


payments_bp = Blueprint("payments", __name__, url_prefix="/premium")

# Preços (BRL)
CANDIDATE_PRICE_CENTS = 990
COMPANY_PRICE_CENTS = 1990


def _safe_json_loads(s: str):
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


def _make_qr_data_uri(payload: str) -> str:
    """Gera QRCode (data URI png) a partir do BR Code / Pix copia e cola.

    Usa 'segno' (pure python). Se não estiver instalado, retorna string vazia.
    """
    if not payload or not segno:
        return ""
    try:
        qr = segno.make(payload, error="m")
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=6, border=2)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as e:  # pragma: no cover
        current_app.logger.warning("QR generation failed: %s", e)
        return ""


def _create_tribopay_charge(amount_cents: int, reference: str, description: str):
    """Cria cobrança Pix via TriboPay (modo API).

    Este método continua "config-driven":
    - TRIBOPAY_API_KEY: token
    - TRIBOPAY_CREATE_CHARGE_URL: endpoint completo para criar cobrança Pix

    Espera JSON com campos comuns:
    - id/charge_id/txid/transaction_id
    - brcode/pixCopiaECola/copiaecola
    - qrcode/qrcodeImage/qrCode (base64 ou url)

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
        "expires_in": 1800,  # 30min
    }

    resp = requests.post(create_url, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _get_redirect_checkout_url(plan: str) -> str:
    """Se você preferir a experiência de checkout TriboPay (link), configure:
    - TRIBOPAY_PRODUCT_CANDIDATE_URL
    - TRIBOPAY_PRODUCT_COMPANY_URL
    """
    if plan == "candidate":
        return os.getenv("TRIBOPAY_PRODUCT_CANDIDATE_URL", "").strip()
    return os.getenv("TRIBOPAY_PRODUCT_COMPANY_URL", "").strip()


@payments_bp.route("/planos")
def plans():
    return render_template(
        "premium/plans.html",
        candidate_monthly_cents=CANDIDATE_PRICE_CENTS,
        company_monthly_cents=COMPANY_PRICE_CENTS,
        use_redirect_checkout=bool(_get_redirect_checkout_url("candidate") or _get_redirect_checkout_url("company")),
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

    # 0) Se você configurou checkout por link, você pode optar por redirecionar.
    # Mas a "versão profissional" mantém o usuário no site com QR/copia e cola,
    # então o redirect é usado apenas como fallback quando a API não está configurada.
    redirect_url = _get_redirect_checkout_url(plan)

    # 1) Tenta TriboPay API (automático - fica no site)
    try:
        charge_data = _create_tribopay_charge(amount_cents, reference, description)
        if charge_data:
            provider = "tribopay_api"
    except Exception as e:
        current_app.logger.warning("TriboPay API charge failed: %s", e)
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
        "redirect_checkout": redirect_url,
    }

    if provider == "manual":
        # Se tiver redirect de checkout, a gente salva o Payment pendente e manda o usuário pro link.
        if redirect_url:
            provider = meta["provider"] = "tribopay_redirect"
        else:
            if not pix_key:
                flash(
                    "PIX_KEY não configurada. Configure uma chave Pix nas Variáveis do Railway (ou configure a API/checkout da TriboPay).",
                    "warning",
                )
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

    # Redireciona apenas no caso do checkout por link
    if meta.get("provider") == "tribopay_redirect" and redirect_url:
        return redirect(redirect_url)

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

    # Se a API não retornou QR, mas temos brcode, geramos localmente
    qrcode_data_uri = ""
    if not qrcode and brcode:
        qrcode_data_uri = _make_qr_data_uri(brcode)

    # Expires (30 min) para UX
    expires_at = pay.created_at + timedelta(minutes=30) if pay.created_at else None

    return render_template(
        "premium/checkout.html",
        payment=pay,
        meta=meta,
        brcode=brcode,
        qrcode=qrcode,
        qrcode_data_uri=qrcode_data_uri,
        expires_at=expires_at,
        poll_url=url_for("payments.payment_poll", payment_id=pay.id),
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


@payments_bp.route("/api/poll/<int:payment_id>", methods=["GET"])
@login_required
def payment_poll(payment_id: int):
    """Endpoint de polling para a UI atualizar sem recarregar (versão profissional)."""
    pay = Payment.query.get_or_404(payment_id)
    if pay.user_id != current_user.id and current_user.role != "admin":
        return jsonify({"ok": False, "error": "forbidden"}), 403

    return jsonify({
        "ok": True,
        "payment_id": pay.id,
        "status": pay.status,
        "paid_at": pay.paid_at.isoformat() if getattr(pay, "paid_at", None) else None,
        "is_premium": bool(getattr(current_user, "is_premium", False)),
    }), 200


@payments_bp.route("/tribopay/webhook", methods=["GET", "POST"])
def tribopay_webhook():
    """Webhook para confirmação automática (tolerante e testável).

    Configure no painel da TriboPay para apontar para:
      https://SEU_DOMINIO/premium/tribopay/webhook?token=SEU_TOKEN

    Defina o token em:
      TRIBOPAY_WEBHOOK_TOKEN
    """
    if request.method == "GET":
        return {"ok": True, "message": "Webhook online"}, 200

    expected = os.getenv("TRIBOPAY_WEBHOOK_TOKEN", "").strip()
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
    reference = data.get("reference") or data.get("ref") or data.get("external_reference") or data.get("referencia")
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

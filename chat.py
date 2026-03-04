from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Conversation, Message, User, Job


chat_bp = Blueprint("chat", __name__, url_prefix="/chat")


def _can_access(conv: Conversation) -> bool:
    if not current_user.is_authenticated:
        return False
    if current_user.role == "admin":
        return True
    return current_user.id in [conv.company_user_id, conv.candidate_user_id]


@chat_bp.route("/")
@login_required
def inbox():
    # lista de conversas do usuário
    q = Conversation.query
    if current_user.role != "admin":
        q = q.filter(
            (Conversation.company_user_id == current_user.id)
            | (Conversation.candidate_user_id == current_user.id)
        )
    conversations = q.order_by(Conversation.created_at.desc()).all()
    return render_template("chat/inbox.html", conversations=conversations)


@chat_bp.route("/start", methods=["POST"])
@login_required
def start():
    """Cria (ou retorna) uma conversa entre empresa e candidato."""
    candidate_user_id = int(request.form.get("candidate_user_id", "0"))
    job_id = request.form.get("job_id")
    job_id = int(job_id) if job_id else None

    if current_user.role not in ["company", "admin"]:
        flash("Apenas empresas podem iniciar conversas.", "danger")
        return redirect(url_for("chat.inbox"))

    candidate = User.query.get_or_404(candidate_user_id)
    if candidate.role != "candidate":
        flash("Usuário inválido.", "danger")
        return redirect(url_for("chat.inbox"))

    conv = Conversation.query.filter_by(
        company_user_id=current_user.id,
        candidate_user_id=candidate_user_id,
        job_id=job_id,
    ).first()
    if not conv:
        conv = Conversation(
            company_user_id=current_user.id,
            candidate_user_id=candidate_user_id,
            job_id=job_id,
        )
        db.session.add(conv)
        db.session.commit()

    return redirect(url_for("chat.thread", conversation_id=conv.id))


@chat_bp.route("/<int:conversation_id>", methods=["GET", "POST"])
@login_required
def thread(conversation_id: int):
    conv = Conversation.query.get_or_404(conversation_id)
    if not _can_access(conv):
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("chat.inbox"))

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("Mensagem vazia.", "warning")
            return redirect(url_for("chat.thread", conversation_id=conversation_id))
        msg = Message(
            conversation_id=conv.id,
            sender_user_id=current_user.id,
            body=body,
        )
        db.session.add(msg)
        db.session.commit()
        return redirect(url_for("chat.thread", conversation_id=conversation_id))

    messages = conv.messages.order_by(Message.created_at.asc()).all()

    other = conv.candidate_user if current_user.id == conv.company_user_id else conv.company_user
    return render_template(
        "chat/thread.html",
        conversation=conv,
        messages=messages,
        other_user=other,
    )

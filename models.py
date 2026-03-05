from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # candidate, company, admin
    full_name = db.Column(db.String(120))
    company_name = db.Column(db.String(120))
    is_premium = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    candidate_profile = db.relationship(
        "CandidateProfile", backref="user", uselist=False
    )
    company_profile = db.relationship(
        "CompanyProfile", backref="user", uselist=False
    )
    notifications = db.relationship(
        "Notification", backref="user", lazy="dynamic"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


class CandidateProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )

    # Dados pessoais
    cpf = db.Column(db.String(20), unique=True, nullable=True)

    cep = db.Column(db.String(9))  # ✅ NOVO: "00000-000"

    address = db.Column(db.String(255))
    city = db.Column(db.String(120))
    birthdate = db.Column(db.Date)
    phone = db.Column(db.String(30))
    gender = db.Column(db.String(10))            # 'M' ou 'F'
    state = db.Column(db.String(2))
    neighborhood = db.Column(db.String(120))
    house_number = db.Column(db.String(20))

    # Perfil profissional
    profession = db.Column(db.String(120))
    education_level = db.Column(db.String(50))
    languages = db.Column(db.Text)
    availability = db.Column(db.String(20))
    experience_years = db.Column(db.Integer)
    skills = db.Column(db.Text)
    bio = db.Column(db.Text)
    avatar_filename = db.Column(db.String(255))
    is_completed = db.Column(db.Boolean, default=False)

    # Destaque / patrocínio
    is_sponsored = db.Column(db.Boolean, default=False)
    sponsored_until = db.Column(db.DateTime)

    # Visibilidade em listagens (home / busca)
    is_public = db.Column(db.Boolean, default=True)

    # Métricas
    views_count = db.Column(db.Integer, default=0)

    applications = db.relationship(
        "Application", backref="candidate_profile", lazy="dynamic"
    )
    company_interests = db.relationship(
        "CompanyInterest", backref="candidate_profile", lazy="dynamic"
    )
    experiences = db.relationship(
        "CandidateExperience",
        backref="candidate_profile",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def initials(self) -> str:
        if self.user and self.user.full_name:
            parts = self.user.full_name.strip().split()
            if not parts:
                return ""
            if len(parts) == 1:
                return parts[0][0:2].upper()
            return (parts[0][0] + parts[-1][0]).upper()
        return ""

    def age(self):
        """Idade calculada a partir de birthdate (em anos)."""
        if not self.birthdate:
            return None
        today = datetime.utcnow().date()
        years = today.year - self.birthdate.year
        if (today.month, today.day) < (self.birthdate.month, self.birthdate.day):
            years -= 1
        return years

    def __repr__(self) -> str:
        if self.user and self.user.full_name:
            return f"<CandidateProfile {self.user.full_name}>"
        return f"<CandidateProfile {self.id}>"


class CandidateExperience(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(
        db.Integer,
        db.ForeignKey("candidate_profile.id"),
        nullable=False,
    )

    role = db.Column(db.String(120))            # Cargo
    company_name = db.Column(db.String(150))    # Empresa
    start_date = db.Column(db.Date)             # Início (usando YYYY-MM no form)
    end_date = db.Column(db.Date, nullable=True)  # Fim
    is_current = db.Column(db.Boolean, default=False)  # Emprego atual

    def period_label(self) -> str:
        """Retorna período formatado tipo '01/2020 - Atual'."""
        if not self.start_date:
            return ""
        start_str = self.start_date.strftime("%m/%Y")
        if self.is_current or not self.end_date:
            return f"{start_str} - Atual"
        end_str = self.end_date.strftime("%m/%Y")
        return f"{start_str} - {end_str}"

    def __repr__(self) -> str:
        return f"<CandidateExperience cand={self.candidate_id} role={self.role}>"


class CompanyProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    cnpj = db.Column(db.String(30), unique=True, nullable=False)
    # Dados da empresa (estilo "Meus Dados" do candidato)
    cep = db.Column(db.String(9))
    state = db.Column(db.String(2))
    neighborhood = db.Column(db.String(120))
    house_number = db.Column(db.String(20))
    segment = db.Column(db.String(120))
    company_size = db.Column(db.String(60))
    founded_year = db.Column(db.String(10))
    address = db.Column(db.String(255))
    city = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    website = db.Column(db.String(255))
    description = db.Column(db.Text)
    logo_filename = db.Column(db.String(255))
    is_completed = db.Column(db.Boolean, default=False)
    # Aprovação (moderação/admin)
    is_approved = db.Column(db.Boolean, default=False)
    is_sponsored = db.Column(db.Boolean, default=False)
    sponsored_until = db.Column(db.DateTime)

    jobs = db.relationship("Job", backref="company_profile", lazy="dynamic")

    def __repr__(self) -> str:
        if self.user and self.user.company_name:
            return f"<CompanyProfile {self.user.company_name}>"
        return f"<CompanyProfile {self.id}>"


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer, db.ForeignKey("company_profile.id"), nullable=False
    )
    title = db.Column(db.String(150), nullable=False)
    city = db.Column(db.String(120), nullable=False)

    employment_type = db.Column(db.String(30))  # CLT, PJ, Freelancer

    work_regime = db.Column(db.String(30))  # Presencial, Home Office, Híbrido, etc.

    salary_min = db.Column(db.Float)
    salary_max = db.Column(db.Float)
    description = db.Column(db.Text)
    requirements = db.Column(db.Text)
    benefits = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    is_sponsored = db.Column(db.Boolean, default=False)
    sponsored_until = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    applications = db.relationship(
        "Application", backref="job", lazy="dynamic"
    )

    def __repr__(self) -> str:
        return f"<Job {self.title}>"


class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(
        db.Integer, db.ForeignKey("candidate_profile.id"), nullable=False
    )
    job_id = db.Column(
        db.Integer, db.ForeignKey("job.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(
        db.String(30),
        default="enviado",
    )  # enviado, em_analise, entrevista_marcada, rejeitado, contratado
    interview_datetime = db.Column(db.DateTime)
    interview_location = db.Column(db.String(255))
    company_notes = db.Column(db.Text)
    candidate_confirmed = db.Column(db.Boolean, default=False)

    def __repr__(self) -> str:
        return f"<Application cand={self.candidate_id} job={self.job_id}>"


class CompanyInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer, db.ForeignKey("company_profile.id"), nullable=False
    )
    candidate_id = db.Column(
        db.Integer, db.ForeignKey("candidate_profile.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(
        db.String(30),
        default="convite_enviado",
    )  # convite_enviado, entrevista_marcada, entrevista_confirmada, fechado
    interview_datetime = db.Column(db.DateTime)
    interview_location = db.Column(db.String(255))
    notes = db.Column(db.Text)
    candidate_confirmed = db.Column(db.Boolean, default=False)

    company_profile = db.relationship("CompanyProfile", backref="interests")

    def __repr__(self) -> str:
        return f"<CompanyInterest comp={self.company_id} cand={self.candidate_id}>"


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    message = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Notification {self.message[:20]}>"


class Conversation(db.Model):
    """Canal de chat 1:1 entre empresa e candidato (opcionalmente ligado a uma vaga)."""

    id = db.Column(db.Integer, primary_key=True)
    company_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    candidate_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    company_user = db.relationship("User", foreign_keys=[company_user_id])
    candidate_user = db.relationship("User", foreign_keys=[candidate_user_id])
    job = db.relationship("Job")

    messages = db.relationship(
        "Message",
        backref="conversation",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversation.id"), nullable=False
    )
    sender_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship("User")


class Payment(db.Model):
    """Pagamento (Pix) simplificado para ativação Premium.

    OBS: Integração automática com PSP pode ser adicionada depois via webhook.
    Por enquanto, o admin pode marcar como pago.
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending, paid, cancelled
    pix_key = db.Column(db.String(120))
    pix_payload = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)

    user = db.relationship("User")

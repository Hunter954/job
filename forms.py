from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, TextAreaField, IntegerField, FloatField, DateField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional

class LoginForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired()])
    remember_me = BooleanField("Lembrar-me")
    submit = SubmitField("Entrar")


class CandidateRegisterForm(FlaskForm):
    full_name = StringField("Nome completo", validators=[DataRequired(), Length(max=120)])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    cpf = StringField("CPF", validators=[DataRequired(), Length(max=20)])
    password = PasswordField("Senha", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Confirmar senha", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Criar conta de candidato")


class CompanyRegisterForm(FlaskForm):
    company_name = StringField("Nome da empresa", validators=[DataRequired(), Length(max=120)])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    cnpj = StringField("CNPJ", validators=[DataRequired(), Length(max=30)])
    password = PasswordField("Senha", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Confirmar senha", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Criar conta de empresa")


class CandidateProfileForm(FlaskForm):
    address = StringField("Endereço", validators=[DataRequired(), Length(max=255)])
    city = StringField("Cidade", validators=[DataRequired(), Length(max=120)])
    birthdate = DateField("Data de nascimento", validators=[DataRequired()], format="%Y-%m-%d")
    phone = StringField("Telefone", validators=[DataRequired(), Length(max=30)])
    profession = StringField("Profissão", validators=[DataRequired(), Length(max=120)])
    experience_years = IntegerField("Tempo de profissão (anos)", validators=[Optional()])
    skills = TextAreaField("Habilidades", validators=[Optional()])
    bio = TextAreaField("Breve descrição", validators=[Optional()])
    submit = SubmitField("Salvar perfil")


class CompanyProfileForm(FlaskForm):
    address = StringField("Endereço", validators=[DataRequired(), Length(max=255)])
    city = StringField("Cidade", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Telefone", validators=[DataRequired(), Length(max=30)])
    website = StringField("Site", validators=[Optional(), Length(max=255)])
    description = TextAreaField("Descrição da empresa", validators=[Optional()])
    submit = SubmitField("Salvar perfil")


class JobForm(FlaskForm):
    title = StringField("Título da vaga", validators=[DataRequired(), Length(max=150)])
    city = StringField("Cidade", validators=[DataRequired(), Length(max=120)])
    salary_min = FloatField("Salário mínimo", validators=[Optional()])
    salary_max = FloatField("Salário máximo", validators=[Optional()])
    description = TextAreaField("Descrição da vaga", validators=[Optional()])
    requirements = TextAreaField("Requisitos", validators=[Optional()])
    benefits = TextAreaField("Benefícios", validators=[Optional()])
    submit = SubmitField("Salvar vaga")

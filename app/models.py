"""Modelo de dados.

Convenções:
- Datas/horas de registro são gravadas em UTC (naive) e convertidas para o
  fuso configurado apenas na exibição.
- Entidades expostas em URLs usam ``public_id`` (UUID) — nunca o ID sequencial.
- O CPF do responsável não é armazenado em claro: guardamos um HMAC-SHA256
  (para localização) e apenas os 2 últimos dígitos (para exibição mascarada).
"""
import uuid
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Situacao:
    AGUARDANDO = "AGUARDANDO"            # derivada: não há registro
    AUTORIZADO = "AUTORIZADO"
    NAO_AUTORIZADO = "NAO_AUTORIZADO"
    CANCELADO = "CANCELADO"              # cancelada pela unidade escolar
    ENCERRADO = "ENCERRADO"              # derivada: passeio encerrado sem resposta

    RESPOSTAS_RESPONSAVEL = {AUTORIZADO, NAO_AUTORIZADO}
    # Situações que o responsável pode registrar (CANCELADO = cancelar a própria resposta).
    PERMITIDAS_RESPONSAVEL = {AUTORIZADO, NAO_AUTORIZADO, CANCELADO}
    ROTULOS = {
        AGUARDANDO: "Aguardando autorização",
        AUTORIZADO: "Autorizado",
        NAO_AUTORIZADO: "Não autorizado",
        CANCELADO: "Autorização cancelada",
        ENCERRADO: "Passeio encerrado",
    }


# ---------------------------------------------------------------------------
# Cadastros básicos
# ---------------------------------------------------------------------------
class Escola(db.Model):
    __tablename__ = "escola"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    codigo = db.Column(db.String(30), unique=True, nullable=False)

    turmas = db.relationship("Turma", back_populates="escola", order_by="Turma.ano, Turma.nome")


class Turma(db.Model):
    __tablename__ = "turma"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(40), nullable=False)       # ex.: "Turma A"
    ano = db.Column(db.String(40), nullable=False)        # ex.: "6º Ano"
    escola_id = db.Column(db.Integer, db.ForeignKey("escola.id"), nullable=False, index=True)

    escola = db.relationship("Escola", back_populates="turmas")

    @property
    def descricao(self) -> str:
        return f"{self.ano} — {self.nome}"


class Responsavel(db.Model):
    __tablename__ = "responsavel"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_uuid)
    nome = db.Column(db.String(160), nullable=False)
    cpf_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    cpf_final = db.Column(db.String(2), nullable=False)
    # Segundo fator opcional (hash, nunca em claro).
    data_nascimento_hash = db.Column(db.String(64))
    email = db.Column(db.String(160))
    telefone = db.Column(db.String(30))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=utcnow)

    vinculos = db.relationship("ResponsavelAluno", back_populates="responsavel")

    @property
    def cpf_mascarado(self) -> str:
        return f"***.***.***-{self.cpf_final}"


class Aluno(db.Model):
    __tablename__ = "aluno"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_uuid)
    matricula = db.Column(db.String(30), unique=True, nullable=False)
    nome = db.Column(db.String(160), nullable=False)
    data_nascimento = db.Column(db.Date)
    sexo = db.Column(db.String(1))  # "M"/"F" — apenas para concordância do texto
    escola_id = db.Column(db.Integer, db.ForeignKey("escola.id"), nullable=False, index=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turma.id"), nullable=False, index=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)

    escola = db.relationship("Escola")
    turma = db.relationship("Turma")
    vinculos = db.relationship("ResponsavelAluno", back_populates="aluno")

    @property
    def iniciais(self) -> str:
        partes = [p for p in self.nome.split() if len(p) > 2 or p[0].isupper()]
        return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


class ResponsavelAluno(db.Model):
    __tablename__ = "responsavel_aluno"
    __table_args__ = (db.UniqueConstraint("responsavel_id", "aluno_id", name="uq_responsavel_aluno_par"),)
    id = db.Column(db.Integer, primary_key=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("aluno.id"), nullable=False, index=True)
    tipo_vinculo = db.Column(db.String(30), nullable=False, default="Responsável")  # Pai, Mãe, Tutor...
    # Regra administrativa: somente vínculos com responsavel_legal=True
    # podem registrar autorização. Os demais não visualizam o aluno.
    responsavel_legal = db.Column(db.Boolean, nullable=False, default=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)

    responsavel = db.relationship("Responsavel", back_populates="vinculos")
    aluno = db.relationship("Aluno", back_populates="vinculos")


# ---------------------------------------------------------------------------
# Passeios
# ---------------------------------------------------------------------------
passeio_turma = db.Table(
    "passeio_turma",
    db.Column("passeio_id", db.Integer, db.ForeignKey("passeio.id"), primary_key=True),
    db.Column("turma_id", db.Integer, db.ForeignKey("turma.id"), primary_key=True),
)

TEXTO_DECLARACAO_PADRAO = (
    "Declaro, na condição de responsável legal, que autorizo o(s) aluno(s) identificado(s) "
    "neste documento a participar do passeio escolar descrito acima, estando ciente das "
    "informações, horários e condições apresentadas pela unidade escolar."
)
TEXTO_TERMO_PADRAO = (
    "Declaro que sou responsável legal pelo(s) aluno(s) selecionado(s) e confirmo esta autorização."
)


class Passeio(db.Model):
    __tablename__ = "passeio"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_uuid)
    nome = db.Column(db.String(160), nullable=False)
    descricao = db.Column(db.Text)
    destino = db.Column(db.String(200), nullable=False)
    data = db.Column(db.Date, nullable=False)
    hora_saida = db.Column(db.Time, nullable=False)
    hora_retorno = db.Column(db.Time, nullable=False)
    local_saida = db.Column(db.String(200), nullable=False)
    transporte = db.Column(db.String(200))
    orientacoes = db.Column(db.Text)
    data_limite = db.Column(db.DateTime, nullable=False)  # horário local
    permite_alteracao = db.Column(db.Boolean, nullable=False, default=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    texto_declaracao = db.Column(db.Text, nullable=False, default=TEXTO_DECLARACAO_PADRAO)
    # Texto do checkbox obrigatório no modal de confirmação.
    texto_termo = db.Column(db.Text, nullable=False, default=TEXTO_TERMO_PADRAO, server_default=TEXTO_TERMO_PADRAO)
    # Horas, após cada resposta, em que o responsável ainda pode alterar/cancelar.
    # None = pode alterar até o prazo final (data_limite).
    prazo_alteracao_horas = db.Column(db.Integer)
    imagem = db.Column(db.String(80))  # arquivo em instance/uploads (tela inicial e card)
    # Ilustração pronta (galeria em static/img/eventos) usada quando não há imagem enviada.
    ilustracao = db.Column(db.String(30), nullable=False, default="cinema", server_default="cinema")
    versao_texto = db.Column(db.Integer, nullable=False, default=1)
    criado_em = db.Column(db.DateTime, nullable=False, default=utcnow)

    turmas = db.relationship("Turma", secondary=passeio_turma, order_by="Turma.ano, Turma.nome")
    participantes = db.relationship("PasseioAluno", back_populates="passeio", cascade="all, delete-orphan")

    @property
    def versao_texto_rotulo(self) -> str:
        return f"v{self.versao_texto}"


class PasseioAluno(db.Model):
    __tablename__ = "passeio_aluno"
    __table_args__ = (db.UniqueConstraint("passeio_id", "aluno_id", name="uq_passeio_aluno_par"),)
    id = db.Column(db.Integer, primary_key=True)
    passeio_id = db.Column(db.Integer, db.ForeignKey("passeio.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("aluno.id"), nullable=False, index=True)

    passeio = db.relationship("Passeio", back_populates="participantes")
    aluno = db.relationship("Aluno")


# ---------------------------------------------------------------------------
# Autorizações
# ---------------------------------------------------------------------------
class Autorizacao(db.Model):
    """Estado ATUAL da resposta para um aluno em um passeio (1 por par)."""
    __tablename__ = "autorizacao"
    __table_args__ = (db.UniqueConstraint("passeio_id", "aluno_id", name="uq_autorizacao_passeio_aluno"),)
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_uuid)
    passeio_id = db.Column(db.Integer, db.ForeignKey("passeio.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("aluno.id"), nullable=False, index=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"), nullable=False, index=True)
    situacao = db.Column(db.String(20), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=utcnow)
    versao_texto = db.Column(db.Integer, nullable=False)
    origem = db.Column(db.String(30), nullable=False, default="WEB_RESPONSAVEL")
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(300))
    documento_id = db.Column(db.Integer, db.ForeignKey("documento.id"))

    passeio = db.relationship("Passeio")
    aluno = db.relationship("Aluno")
    responsavel = db.relationship("Responsavel")
    documento = db.relationship("Documento", foreign_keys=[documento_id])
    historico = db.relationship("AutorizacaoHistorico", back_populates="autorizacao",
                                order_by="AutorizacaoHistorico.data_hora")

    @property
    def protocolo(self):
        return self.documento.protocolo if self.documento else None

    @property
    def codigo_validacao(self):
        return self.documento.codigo_validacao if self.documento else None


class AutorizacaoHistorico(db.Model):
    """Trilha imutável de todas as mudanças de situação."""
    __tablename__ = "autorizacao_historico"
    id = db.Column(db.Integer, primary_key=True)
    autorizacao_id = db.Column(db.Integer, db.ForeignKey("autorizacao.id"), nullable=False, index=True)
    situacao_anterior = db.Column(db.String(20))
    situacao_nova = db.Column(db.String(20), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=utcnow)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"))
    admin_id = db.Column(db.Integer, db.ForeignKey("admin_usuario.id"))
    documento_id = db.Column(db.Integer, db.ForeignKey("documento.id"))
    motivo = db.Column(db.String(300))
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(300))

    autorizacao = db.relationship("Autorizacao", back_populates="historico")


class Documento(db.Model):
    """Comprovante PDF de UMA operação (pode conter vários alunos)."""
    __tablename__ = "documento"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_uuid)
    protocolo = db.Column(db.String(20), unique=True, nullable=False)
    codigo_validacao = db.Column(db.String(14), unique=True, nullable=False, index=True)
    passeio_id = db.Column(db.Integer, db.ForeignKey("passeio.id"), nullable=False, index=True)
    responsavel_id = db.Column(db.Integer, db.ForeignKey("responsavel.id"), nullable=False, index=True)
    data_registro = db.Column(db.DateTime, nullable=False, default=utcnow)
    versao_texto = db.Column(db.Integer, nullable=False)
    # Fotografia imutável dos dados impressos (passeio, responsável, alunos).
    # Garante que o PDF possa ser regenerado de forma idêntica (mesmo hash),
    # mesmo que o cadastro do passeio seja alterado depois.
    conteudo = db.Column(db.JSON, nullable=False)
    arquivo = db.Column(db.String(200))
    hash_sha256 = db.Column(db.String(64))
    data_geracao = db.Column(db.DateTime)

    passeio = db.relationship("Passeio")
    responsavel = db.relationship("Responsavel")
    itens = db.relationship("DocumentoItem", back_populates="documento", order_by="DocumentoItem.id")


class DocumentoItem(db.Model):
    """Fotografia da situação de cada aluno no momento da emissão."""
    __tablename__ = "documento_item"
    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey("documento.id"), nullable=False, index=True)
    autorizacao_id = db.Column(db.Integer, db.ForeignKey("autorizacao.id"), nullable=False, index=True)
    situacao = db.Column(db.String(20), nullable=False)

    documento = db.relationship("Documento", back_populates="itens")
    autorizacao = db.relationship("Autorizacao")


class ProtocoloSequencia(db.Model):
    __tablename__ = "protocolo_sequencia"
    ano = db.Column(db.Integer, primary_key=True)
    ultimo = db.Column(db.Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Administração, auditoria e segurança
# ---------------------------------------------------------------------------
class AdminUsuario(db.Model):
    __tablename__ = "admin_usuario"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    login = db.Column(db.String(60), unique=True, nullable=False)
    # E-mail do Supabase Authentication (modo Supabase). Senha fica só no Supabase.
    email = db.Column(db.String(160), unique=True)
    # Somente no modo local (desenvolvimento/testes).
    senha_hash = db.Column(db.String(256))
    # None = acesso a toda a rede; preenchido = restrito à escola.
    escola_id = db.Column(db.Integer, db.ForeignKey("escola.id"))
    ativo = db.Column(db.Boolean, nullable=False, default=True)

    escola = db.relationship("Escola")

    def definir_senha(self, senha: str) -> None:
        self.senha_hash = generate_password_hash(senha)

    def conferir_senha(self, senha: str) -> bool:
        return bool(self.senha_hash) and check_password_hash(self.senha_hash, senha)


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    ator_tipo = db.Column(db.String(20), nullable=False)   # RESPONSAVEL | ADMIN | PUBLICO | SISTEMA
    ator_id = db.Column(db.Integer)
    acao = db.Column(db.String(40), nullable=False, index=True)
    alvo = db.Column(db.String(120))
    detalhes = db.Column(db.JSON)
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(300))


class Midia(db.Model):
    """Imagens enviadas pelo painel, guardadas no banco (PNG já validado e regravado)."""
    __tablename__ = "midia"
    nome = db.Column(db.String(60), primary_key=True)
    dados = db.Column(db.LargeBinary, nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=utcnow)


class Configuracao(db.Model):
    """Parâmetros gerais editáveis pelo painel (nome da instituição, brasão, etc.)."""
    __tablename__ = "configuracao"
    chave = db.Column(db.String(60), primary_key=True)
    valor = db.Column(db.Text)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class TentativaAcesso(db.Model):
    """Base para limitação de tentativas (IP e CPF)."""
    __tablename__ = "tentativa_acesso"
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(100), nullable=False, index=True)  # "ip:..." | "cpf:<hash>" | "val:ip"
    sucesso = db.Column(db.Boolean, nullable=False, default=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

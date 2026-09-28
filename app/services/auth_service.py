"""Autenticação do responsável com segundo fator plugável.

O conhecimento do CPF NÃO é autenticação forte. Em produção configure
``AUTH_SEGUNDO_FATOR`` com um provedor adicional. Para acrescentar um novo
provedor (SMS, e-mail, token, Gov.br), crie uma subclasse de
``SegundoFator`` e registre-a em ``PROVEDORES``. Provedores que exigem uma
etapa extra (ex.: envio de código) podem usar ``iniciar()`` para disparar o
código e ``verificar()`` para conferi-lo; as rotas já tratam o campo
``segundo_fator`` de forma genérica.
"""
from dataclasses import dataclass, field

from flask import current_app

from .. import audit
from ..extensions import db
from ..models import Aluno, Responsavel, ResponsavelAluno
from ..security import (client_ip, cpf_aceito, excedeu_limite, hash_cpf, hash_segredo,
                        normalizar_cpf, registrar_tentativa)

MSG_CPF_INVALIDO = "CPF inválido. Verifique os números informados."
MSG_NAO_ENCONTRADO = "Não encontramos alunos vinculados a este CPF."
MSG_DADOS_NAO_CONFEREM = "Não foi possível confirmar os dados informados. Verifique e tente novamente."
MSG_BLOQUEADO = "Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente."


# ---------------------------------------------------------------------------
# Provedores de segundo fator
# ---------------------------------------------------------------------------
class SegundoFator:
    nome = "base"
    # Campos adicionais exibidos na tela de acesso: (name, label, type, placeholder)
    campos: list[tuple[str, str, str, str]] = []
    # Quando True a mensagem de "não encontrado" é genérica (anti-enumeração).
    mensagem_generica = True

    def verificar(self, responsavel: Responsavel, dados: dict) -> bool:
        raise NotImplementedError


class SemSegundoFator(SegundoFator):
    """Somente CPF — adequado apenas para protótipo/demonstração."""
    nome = "nenhum"
    campos = []
    mensagem_generica = False

    def verificar(self, responsavel, dados):
        return True


class DataNascimentoFator(SegundoFator):
    nome = "data_nascimento"
    campos = [("data_nascimento", "Sua data de nascimento", "date", "")]

    def verificar(self, responsavel, dados):
        valor = (dados.get("data_nascimento") or "").strip()  # AAAA-MM-DD
        if not valor or not responsavel.data_nascimento_hash:
            return False
        import hmac
        return hmac.compare_digest(hash_segredo(valor), responsavel.data_nascimento_hash)


PROVEDORES = {p.nome: p for p in (SemSegundoFator, DataNascimentoFator)}


def provedor_atual() -> SegundoFator:
    nome = current_app.config["AUTH_SEGUNDO_FATOR"]
    classe = PROVEDORES.get(nome)
    if classe is None:
        raise RuntimeError(f"AUTH_SEGUNDO_FATOR desconhecido: {nome}")
    return classe()


# ---------------------------------------------------------------------------
# Fluxo de autenticação
# ---------------------------------------------------------------------------
@dataclass
class Resultado:
    ok: bool
    responsavel: Responsavel | None = None
    erro: str | None = None
    status: int = 200
    dicas: list[str] = field(default_factory=list)


def possui_alunos_ativos(resp: Responsavel) -> bool:
    return db.session.query(ResponsavelAluno.id).join(Aluno).filter(
        ResponsavelAluno.responsavel_id == resp.id,
        ResponsavelAluno.ativo.is_(True),
        ResponsavelAluno.responsavel_legal.is_(True),
        Aluno.ativo.is_(True),
    ).first() is not None


def autenticar(cpf_digitado: str, dados: dict) -> Resultado:
    cfg = current_app.config
    cpf = normalizar_cpf(cpf_digitado)
    chave_ip = f"ip:{client_ip()}"

    if excedeu_limite(chave_ip, cfg["LIMITE_TENTATIVAS_IP"]):
        audit.registrar(audit.Acao.LOGIN_BLOQUEADO, "PUBLICO", detalhes={"motivo": "limite_ip"})
        return Resultado(False, erro=MSG_BLOQUEADO, status=429)

    if not cpf_aceito(cpf):
        registrar_tentativa(chave_ip, False)
        return Resultado(False, erro=MSG_CPF_INVALIDO, status=400)

    cpf_h = hash_cpf(cpf)
    chave_cpf = f"cpf:{cpf_h}"
    if excedeu_limite(chave_cpf, cfg["LIMITE_TENTATIVAS_CPF"]):
        audit.registrar(audit.Acao.LOGIN_BLOQUEADO, "PUBLICO", detalhes={"motivo": "limite_cpf"})
        return Resultado(False, erro=MSG_BLOQUEADO, status=429)

    provedor = provedor_atual()
    resp = Responsavel.query.filter_by(cpf_hash=cpf_h, ativo=True).first()
    valido = resp is not None and possui_alunos_ativos(resp) and provedor.verificar(resp, dados)

    if not valido:
        registrar_tentativa(chave_ip, False)
        registrar_tentativa(chave_cpf, False)
        audit.registrar(audit.Acao.LOGIN_FALHA, "PUBLICO", detalhes={"segundo_fator": provedor.nome})
        dicas = ["Caso seus dados estejam desatualizados, entre em contato com a unidade escolar."]
        msg = MSG_DADOS_NAO_CONFEREM if provedor.mensagem_generica else MSG_NAO_ENCONTRADO
        return Resultado(False, erro=msg, status=404 if not provedor.mensagem_generica else 401, dicas=dicas)

    registrar_tentativa(chave_ip, True)
    audit.registrar(audit.Acao.LOGIN_RESPONSAVEL, "RESPONSAVEL", resp.id,
                    detalhes={"segundo_fator": provedor.nome})
    return Resultado(True, responsavel=resp)

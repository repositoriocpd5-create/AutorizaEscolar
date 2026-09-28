"""API REST (JSON). Toda rota do responsável valida sessão e vínculo no backend."""
from flask import Blueprint, abort, jsonify, request, session, url_for

from .. import audit
from ..formatacao import data_br, data_hora_local_br, data_hora_utc_br, hora_br, rotulo_situacao
from ..models import Autorizacao, Documento
from ..security import csrf_token, iniciar_sessao_responsavel, responsavel_atual, responsavel_obrigatorio
from ..services import auth_service
from ..services.autorizacao_service import ErroNegocio, registrar_respostas
from ..services.passeio_service import (alunos_do_responsavel, estado_passeio, itens_do_responsavel,
                                        passeio_por_public_id, passeios_do_responsavel)
from .public import consultar_validacao, enviar_pdf

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Serializadores (somente dados necessários; nunca IDs internos)
# ---------------------------------------------------------------------------
def _passeio_json(p):
    e = estado_passeio(p)
    return {
        "id": p.public_id, "nome": p.nome, "descricao": p.descricao, "destino": p.destino,
        "data": data_br(p.data), "hora_saida": hora_br(p.hora_saida), "hora_retorno": hora_br(p.hora_retorno),
        "local_saida": p.local_saida, "transporte": p.transporte, "orientacoes": p.orientacoes,
        "data_limite": data_hora_local_br(p.data_limite), "permite_alteracao": p.permite_alteracao,
        "aberto": e.aberto, "encerrado": e.encerrado, "versao_texto": p.versao_texto,
    }


def _aluno_json(a):
    return {"id": a.public_id, "nome": a.nome, "ano": a.turma.ano, "turma": a.turma.nome,
            "escola": a.escola.nome}


def _item_json(item):
    aut = item.autorizacao
    dados = {"aluno": _aluno_json(item.aluno), "situacao": item.situacao,
             "situacao_rotulo": rotulo_situacao(item.situacao),
             "pode_responder": item.pode_responder, "pode_alterar": item.pode_alterar, "aviso": item.aviso,
             "respondido_por_outro_responsavel": item.respondido_por_outro, "autorizacao": None}
    if aut:
        dados["autorizacao"] = {"id": aut.public_id, "data_hora": data_hora_utc_br(aut.data_hora)}
        if not item.respondido_por_outro and aut.documento:
            dados["autorizacao"].update(protocolo=aut.protocolo,
                                        documento_id=aut.documento.public_id,
                                        pdf_url=url_for("public.documento_pdf", public_id=aut.documento.public_id))
    return dados


def _passeio_do_responsavel(public_id):
    p = passeio_por_public_id(public_id)
    if p is None or p not in passeios_do_responsavel(responsavel_atual()):
        abort(404)
    return p


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------
@bp.post("/auth/responsavel")
def auth_responsavel():
    corpo = request.get_json(silent=True) or {}
    r = auth_service.autenticar(str(corpo.get("cpf", "")), corpo)
    if not r.ok:
        return jsonify(erro=r.erro, dicas=r.dicas), r.status
    iniciar_sessao_responsavel(r.responsavel)
    return jsonify(ok=True, redirecionar=url_for("public.painel"), csrf=csrf_token())


@bp.post("/auth/sair")
def auth_sair():
    session.clear()
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Responsável
# ---------------------------------------------------------------------------
@bp.get("/responsavel/me")
@responsavel_obrigatorio(api=True)
def me():
    r = responsavel_atual()
    return jsonify(nome=r.nome, cpf=r.cpf_mascarado)


@bp.get("/responsavel/me/alunos")
@responsavel_obrigatorio(api=True)
def meus_alunos():
    return jsonify(alunos=[_aluno_json(a) for a in alunos_do_responsavel(responsavel_atual())])


@bp.get("/passeios/ativos")
@responsavel_obrigatorio(api=True)
def passeios_ativos():
    return jsonify(passeios=[_passeio_json(p) for p in passeios_do_responsavel(responsavel_atual())])


@bp.get("/passeios/<public_id>")
@responsavel_obrigatorio(api=True)
def passeio_detalhe(public_id):
    return jsonify(_passeio_json(_passeio_do_responsavel(public_id)))


@bp.get("/passeios/<public_id>/meus-alunos")
@responsavel_obrigatorio(api=True)
def passeio_meus_alunos(public_id):
    p = _passeio_do_responsavel(public_id)
    resp = responsavel_atual()
    audit.registrar(audit.Acao.CONSULTA_ALUNOS, "RESPONSAVEL", resp.id, alvo=f"passeio:{p.public_id}")
    return jsonify(passeio=_passeio_json(p), alunos=[_item_json(i) for i in itens_do_responsavel(p, resp)])


@bp.post("/passeios/<public_id>/autorizacoes")
@responsavel_obrigatorio(api=True)
def registrar(public_id):
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify(erro="Requisição inválida."), 400
    try:
        res = registrar_respostas(responsavel_atual(), public_id, corpo.get("autorizacoes"),
                                  corpo.get("declaracao_aceita"))
    except ErroNegocio as e:
        return jsonify(erro=e.mensagem), e.status
    doc = res.documento
    return jsonify(
        ok=True, protocolo=doc.protocolo, codigo_validacao=doc.codigo_validacao,
        registrado_em=data_hora_utc_br(doc.data_registro), documento_id=doc.public_id,
        pdf_disponivel=bool(doc.hash_sha256),
        redirecionar=url_for("public.documento", public_id=doc.public_id, novo=1),
        pdf_url=url_for("public.documento_pdf", public_id=doc.public_id),
    ), 201


def _autorizacao_do_responsavel(public_id) -> Autorizacao:
    resp = responsavel_atual()
    aut = Autorizacao.query.filter_by(public_id=public_id).first()
    meus = {a.id for a in alunos_do_responsavel(resp)}
    if aut is None or aut.aluno_id not in meus:
        abort(404)
    return aut


@bp.get("/autorizacoes/<public_id>")
@responsavel_obrigatorio(api=True)
def autorizacao(public_id):
    aut = _autorizacao_do_responsavel(public_id)
    proprio = aut.responsavel_id == responsavel_atual().id
    return jsonify(id=aut.public_id, aluno=_aluno_json(aut.aluno), passeio=aut.passeio.nome,
                   situacao=aut.situacao, situacao_rotulo=rotulo_situacao(aut.situacao),
                   data_hora=data_hora_utc_br(aut.data_hora), versao_texto=aut.versao_texto,
                   protocolo=aut.protocolo if proprio else None,
                   historico=[{"de": h.situacao_anterior, "para": h.situacao_nova,
                               "data_hora": data_hora_utc_br(h.data_hora)} for h in aut.historico])


@bp.get("/autorizacoes/<public_id>/pdf")
@responsavel_obrigatorio(api=True)
def autorizacao_pdf(public_id):
    aut = _autorizacao_do_responsavel(public_id)
    doc = aut.documento
    if doc is None or doc.responsavel_id != responsavel_atual().id:
        abort(404)
    return enviar_pdf(doc, "RESPONSAVEL", responsavel_atual().id)


@bp.get("/documentos/<public_id>/pdf")
@responsavel_obrigatorio(api=True)
def documento_pdf(public_id):
    doc = Documento.query.filter_by(public_id=public_id).first()
    if doc is None or doc.responsavel_id != responsavel_atual().id:
        abort(404)
    return enviar_pdf(doc, "RESPONSAVEL", responsavel_atual().id)


# ---------------------------------------------------------------------------
# Validação pública
# ---------------------------------------------------------------------------
@bp.get("/validar/<codigo>")
def validar(codigo):
    status, dados = consultar_validacao(codigo)
    if status == 200:
        return jsonify(dados)
    if status == 429:
        return jsonify(erro="Muitas consultas. Aguarde alguns minutos."), 429
    return jsonify(valido=False, erro="Documento não encontrado."), 404

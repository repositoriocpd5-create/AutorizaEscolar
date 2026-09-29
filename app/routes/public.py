"""Páginas do responsável e página pública de validação."""
import io
import re

from flask import (Blueprint, Response, abort, current_app, redirect, render_template, request,
                   send_file, session, url_for)

from .. import audit
from ..models import Documento, Situacao
from ..security import client_ip, excedeu_limite, registrar_tentativa, responsavel_atual, responsavel_obrigatorio
from ..services import config_service, documento_service, midia_service
from ..services.auth_service import provedor_atual
from ..services.autorizacao_service import status_documento
from ..services.passeio_service import (estado_passeio, itens_do_responsavel, passeio_por_public_id,
                                        passeios_do_responsavel)

bp = Blueprint("public", __name__)

RE_CODIGO = re.compile(r"^[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$")


@bp.get("/")
def login():
    if responsavel_atual():
        return redirect(url_for("public.painel"))
    destaque = config_service.passeio_destaque()
    imagem_url, foto = config_service.imagem_inicial()
    return render_template(
        "login.html", campos_extra=provedor_atual().campos,
        titulo=destaque.nome if destaque else config_service.obter("titulo_sistema"),
        subtitulo=config_service.obter("subtitulo"),
        login_chamada=config_service.obter("login_chamada"),
        login_apoio=config_service.obter("login_apoio"),
        imagem_url=imagem_url, imagem_personalizada=foto)


@bp.get("/midia/<nome>")
def midia(nome):
    """Imagens enviadas pelo painel (já validadas e regravadas em PNG)."""
    dados = midia_service.dados(nome)
    if dados is None:
        abort(404)
    # Nome contém token aleatório e nunca é reaproveitado: pode ficar em cache.
    return send_file(io.BytesIO(dados), mimetype="image/png", max_age=86400)


@bp.post("/sair")
def sair():
    resp = responsavel_atual()
    if resp:
        audit.registrar(audit.Acao.LOGOUT, "RESPONSAVEL", resp.id)
    session.clear()
    return redirect(url_for("public.login"))


@bp.get("/painel")
@responsavel_obrigatorio()
def painel():
    resp = responsavel_atual()
    passeios = passeios_do_responsavel(resp)
    if len(passeios) == 1:
        return redirect(url_for("public.passeio", public_id=passeios[0].public_id))
    return render_template("painel.html", passeios=[(p, estado_passeio(p)) for p in passeios])


@bp.get("/passeios/<public_id>")
@responsavel_obrigatorio()
def passeio(public_id):
    resp = responsavel_atual()
    p = passeio_por_public_id(public_id)
    # O passeio precisa envolver ao menos um aluno vinculado a este responsável.
    if p is None or p not in passeios_do_responsavel(resp):
        abort(404)
    itens = itens_do_responsavel(p, resp)
    audit.registrar(audit.Acao.CONSULTA_ALUNOS, "RESPONSAVEL", resp.id, alvo=f"passeio:{p.public_id}")
    return render_template("passeio.html", passeio=p, estado=estado_passeio(p), itens=itens,
                           mais_de_um=len(passeios_do_responsavel(resp)) > 1, Situacao=Situacao)


def _documento_do_responsavel(public_id) -> Documento:
    resp = responsavel_atual()
    doc = Documento.query.filter_by(public_id=public_id).first()
    # Somente o autor do registro pode acessar o comprovante.
    if doc is None or doc.responsavel_id != resp.id:
        abort(404)
    return doc


@bp.get("/documentos/<public_id>")
@responsavel_obrigatorio()
def documento(public_id):
    doc = _documento_do_responsavel(public_id)
    vigente, rotulo = status_documento(doc)
    return render_template("documento.html", doc=doc, novo=request.args.get("novo") == "1",
                           vigente=vigente, rotulo=rotulo, Situacao=Situacao)


@bp.get("/documentos/<public_id>/pdf")
@responsavel_obrigatorio()
def documento_pdf(public_id):
    doc = _documento_do_responsavel(public_id)
    return enviar_pdf(doc, "RESPONSAVEL", responsavel_atual().id)


def enviar_pdf(doc: Documento, ator_tipo: str, ator_id: int) -> Response:
    dados = documento_service.obter_pdf(doc)
    baixar = request.args.get("download") == "1"
    audit.registrar(audit.Acao.PDF_DOWNLOAD, ator_tipo, ator_id, alvo=f"documento:{doc.public_id}",
                    detalhes={"protocolo": doc.protocolo, "modo": "download" if baixar else "visualizar"})
    nome = f"autorizacao-{doc.protocolo}.pdf"
    return Response(dados, mimetype="application/pdf", headers={
        "Content-Disposition": f'{"attachment" if baixar else "inline"}; filename="{nome}"',
        "Cache-Control": "no-store",
    })


# ---------------------------------------------------------------------------
# Validação pública
# ---------------------------------------------------------------------------
def consultar_validacao(codigo: str):
    """Retorna (status_http, dados_minimos | None). Com limitação por IP."""
    codigo = (codigo or "").strip().upper()
    chave = f"val:{client_ip()}"
    if excedeu_limite(chave, current_app.config["LIMITE_VALIDACAO_IP"]):
        return 429, None
    if not RE_CODIGO.match(codigo):
        registrar_tentativa(chave, False)
        return 404, None
    doc = Documento.query.filter_by(codigo_validacao=codigo).first()
    if doc is None:
        registrar_tentativa(chave, False)
        return 404, None
    vigente, rotulo = status_documento(doc)
    audit.registrar(audit.Acao.VALIDACAO_DOCUMENTO, "PUBLICO", alvo=f"documento:{doc.public_id}")
    # Dados mínimos: sem CPF, sem nome completo do responsável, iniciais dos alunos.
    return 200, {
        "valido": True, "vigente": vigente, "situacao": rotulo,
        "protocolo": doc.protocolo, "passeio": doc.conteudo["passeio"]["nome"],
        "data_passeio": doc.conteudo["passeio"]["data"],
        "data_autorizacao": f'{doc.conteudo["registro"]["data"]} às {doc.conteudo["registro"]["hora"][:5]}',
        "alunos": [_nome_reduzido(a["nome"]) for a in doc.conteudo["alunos"]],
        "codigo": doc.codigo_validacao,
    }


def _nome_reduzido(nome: str) -> str:
    partes = nome.split()
    return partes[0] + (" " + " ".join(p[0] + "." for p in partes[1:] if len(p) > 2) if len(partes) > 1 else "")


@bp.get("/validar")
def validar_form():
    codigo = request.args.get("codigo", "").strip()
    if codigo:
        return redirect(url_for("public.validar", codigo=codigo.upper()))
    return render_template("validar.html", resultado=None, status=None, codigo="")


@bp.get("/validar/<codigo>")
def validar(codigo):
    status, dados = consultar_validacao(codigo)
    return render_template("validar.html", resultado=dados, status=status, codigo=codigo), \
        (200 if status == 200 else status)


@bp.get("/saude")
def saude():
    """Verificação de saúde para a hospedagem (confere a conexão com o banco)."""
    from sqlalchemy import text
    from ..extensions import db
    db.session.execute(text("SELECT 1"))
    return {"status": "ok"}


@bp.get("/privacidade")
def privacidade():
    return render_template("privacidade.html")

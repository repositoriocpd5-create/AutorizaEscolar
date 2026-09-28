"""Painel: cadastro de responsáveis (CPF) e de seus filhos (alunos)."""
from flask import abort, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Aluno
from ..security import admin_atual, permissao_obrigatoria
from ..services import cadastro_service as cad
from .admin import bp

POR_PAGINA = 25


def _resp_ou_404(public_id):
    resp = cad.responsavel_no_escopo(admin_atual(), public_id)
    if resp is None:
        abort(404)
    return resp


def _contexto(adm, **extra):
    alunos = cad.alunos_visiveis(adm).filter(Aluno.ativo.is_(True)).order_by(Aluno.nome).all()
    return dict(escolas=cad.escolas_do_escopo(adm), turmas=cad.turmas_do_escopo(adm), sugestoes_alunos=alunos,
                TIPOS_VINCULO=cad.TIPOS_VINCULO, **extra)


@bp.get("/responsaveis")
@permissao_obrigatoria("cadastros")
def responsaveis():
    adm = admin_atual()
    q, escola = request.args.get("q", ""), request.args.get("escola", "")
    consulta = cad.pesquisar(adm, q, escola)
    total = consulta.count()
    pagina = max(1, request.args.get("pagina", 1, type=int))
    total_paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)
    pagina = min(pagina, total_paginas)
    lista = consulta.offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA).all()
    return render_template("admin/responsaveis.html", lista=lista, total=total, pagina=pagina,
                           total_paginas=total_paginas, q=q, escola=escola,
                           escolas=cad.escolas_do_escopo(adm))


@bp.route("/responsaveis/novo", methods=["GET", "POST"])
@permissao_obrigatoria("cadastros")
def responsavel_novo():
    adm = admin_atual()
    erro = None
    if request.method == "POST":
        try:
            resp = cad.salvar_responsavel(adm, None, request.form)
            db.session.commit()
            flash("Responsável cadastrado. Agora vincule os filhos.", "sucesso")
            return redirect(url_for("admin.responsavel_editar", public_id=resp.public_id) + "#filhos")
        except cad.ErroCadastro as e:
            db.session.rollback()
            erro = str(e)
    return render_template("admin/responsavel_form.html", resp=None, erro=erro, form=request.form,
                           **_contexto(adm))


@bp.route("/responsaveis/<public_id>", methods=["GET", "POST"])
@permissao_obrigatoria("cadastros")
def responsavel_editar(public_id):
    adm = admin_atual()
    resp = _resp_ou_404(public_id)
    erro = None
    if request.method == "POST":
        try:
            cad.salvar_responsavel(adm, resp, request.form)
            db.session.commit()
            flash("Dados do responsável atualizados.", "sucesso")
            return redirect(url_for("admin.responsavel_editar", public_id=resp.public_id))
        except cad.ErroCadastro as e:
            db.session.rollback()
            erro = str(e)
            resp = _resp_ou_404(public_id)
    return render_template("admin/responsavel_form.html", resp=resp, erro=erro, form=request.form if erro else None,
                           historico=cad.possui_historico(resp), **_contexto(adm))


@bp.post("/responsaveis/<public_id>/filhos")
@permissao_obrigatoria("cadastros")
def responsavel_filhos(public_id):
    """Vincula aluno existente, cadastra aluno novo e vincula, ou remove um vínculo."""
    adm = admin_atual()
    resp = _resp_ou_404(public_id)
    f = request.form
    acao = f.get("acao")
    try:
        if acao == "desvincular":
            cad.desvincular(adm, resp, int(f.get("vinculo_id", "0") or 0))
            msg = "Vínculo removido."
        else:
            if acao == "novo_aluno":
                aluno = cad.salvar_aluno(adm, None, f)
            else:
                aluno = cad.aluno_por_referencia(adm, f.get("aluno_ref", ""))
                if aluno is None:
                    raise cad.ErroCadastro("Aluno não encontrado. Informe a matrícula (ou escolha na lista).")
            cad.vincular(adm, resp, aluno, f.get("tipo_vinculo", ""), f.get("responsavel_legal") == "1")
            msg = f"{aluno.nome} vinculado(a) a {resp.nome}."
        db.session.commit()
        flash(msg, "sucesso")
    except cad.ErroCadastro as e:
        db.session.rollback()
        flash(str(e), "erro")
    return redirect(url_for("admin.responsavel_editar", public_id=resp.public_id) + "#filhos")


@bp.post("/responsaveis/<public_id>/vinculos/<int:vid>")
@permissao_obrigatoria("cadastros")
def responsavel_vinculo(public_id, vid):
    """Altera tipo de vínculo e se pode autorizar."""
    adm = admin_atual()
    resp = _resp_ou_404(public_id)
    v = next((x for x in resp.vinculos if x.id == vid), None)
    if v is None or (adm.escola_id and v.aluno.escola_id != adm.escola_id):
        abort(404)
    cad.vincular(adm, resp, v.aluno, request.form.get("tipo_vinculo", ""),
                 request.form.get("responsavel_legal") == "1")
    db.session.commit()
    flash("Vínculo atualizado.", "sucesso")
    return redirect(url_for("admin.responsavel_editar", public_id=resp.public_id) + "#filhos")


@bp.post("/responsaveis/<public_id>/excluir")
@permissao_obrigatoria("cadastros")
def responsavel_excluir(public_id):
    adm = admin_atual()
    resp = _resp_ou_404(public_id)
    nome = resp.nome
    try:
        resultado = cad.excluir_responsavel(adm, resp)
        db.session.commit()
    except cad.ErroCadastro as e:
        db.session.rollback()
        flash(str(e), "erro")
        return redirect(url_for("admin.responsavel_editar", public_id=public_id))
    if resultado == "excluido":
        flash(f"Responsável {nome} excluído.", "sucesso")
    else:
        flash(f"{nome} possui autorizações registradas: o cadastro foi desativado e os vínculos removidos, "
              "preservando os comprovantes e o histórico.", "sucesso")
    return redirect(url_for("admin.responsaveis"))


@bp.route("/alunos/<public_id>/editar", methods=["GET", "POST"])
@permissao_obrigatoria("cadastros")
def aluno_editar(public_id):
    adm = admin_atual()
    aluno = cad.alunos_visiveis(adm).filter(Aluno.public_id == public_id).first() or abort(404)
    voltar = request.args.get("voltar", "")
    if not voltar.startswith("/admin") or voltar.startswith("//"):
        voltar = url_for("admin.responsaveis")
    erro = None
    if request.method == "POST":
        try:
            cad.salvar_aluno(adm, aluno, request.form)
            db.session.commit()
            flash("Dados do aluno atualizados.", "sucesso")
            return redirect(voltar)
        except cad.ErroCadastro as e:
            db.session.rollback()
            erro = str(e)
            aluno = cad.alunos_visiveis(adm).filter(Aluno.public_id == public_id).first()
    return render_template("admin/aluno_form.html", aluno=aluno, erro=erro, voltar=voltar,
                           form=request.form if erro else None, **_contexto(adm))

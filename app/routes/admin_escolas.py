"""Painel: cadastro de escolas, turmas e importação do JSON da rede."""
from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from ..extensions import db
from ..models import Aluno, Escola
from ..security import admin_atual, permissao_obrigatoria
from ..services import escola_service as esc
from .admin import bp

POR_PAGINA = 30


def _escola_ou_404(eid: int) -> Escola:
    return db.session.get(Escola, eid) or abort(404)


@bp.get("/escolas")
@permissao_obrigatoria("escolas")
def escolas():
    q = request.args.get("q", "").strip()
    situacao = request.args.get("situacao", "")
    consulta = Escola.query
    if q:
        like = f"%{q.lower()}%"
        consulta = consulta.filter(or_(func.lower(Escola.nome).like(like), Escola.inep == q,
                                       func.lower(Escola.bairro).like(like), func.lower(Escola.diretor).like(like)))
    if situacao in ("ativas", "inativas"):
        consulta = consulta.filter(Escola.ativo.is_(situacao == "ativas"))
    total = consulta.count()
    pagina = max(1, request.args.get("pagina", 1, type=int))
    total_paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)
    lista = consulta.order_by(Escola.nome).offset((min(pagina, total_paginas) - 1) * POR_PAGINA).limit(POR_PAGINA).all()
    alunos_por_escola = dict(db.session.query(Aluno.escola_id, func.count(Aluno.id))
                             .filter(Aluno.ativo.is_(True)).group_by(Aluno.escola_id).all())
    return render_template("admin/escolas.html", lista=lista, total=total, pagina=pagina, total_paginas=total_paginas,
                           q=q, situacao=situacao, alunos_por_escola=alunos_por_escola)


@bp.route("/escolas/nova", methods=["GET", "POST"])
@permissao_obrigatoria("escolas")
def escola_nova():
    erro = None
    if request.method == "POST":
        try:
            e = esc.salvar(admin_atual(), None, request.form)
            db.session.commit()
            flash("Escola cadastrada. Agora cadastre as turmas.", "sucesso")
            return redirect(url_for("admin.escola_editar", eid=e.id) + "#turmas")
        except esc.ErroEscola as e:
            db.session.rollback()
            erro = str(e)
    return render_template("admin/escola_form.html", e=None, erro=erro, form=request.form, ANOS=esc.ANOS_PADRAO)


@bp.route("/escolas/<int:eid>", methods=["GET", "POST"])
@permissao_obrigatoria("escolas")
def escola_editar(eid):
    e = _escola_ou_404(eid)
    erro = None
    if request.method == "POST":
        try:
            esc.salvar(admin_atual(), e, request.form)
            db.session.commit()
            flash("Dados da escola atualizados.", "sucesso")
            return redirect(url_for("admin.escola_editar", eid=e.id))
        except esc.ErroEscola as ex:
            db.session.rollback()
            erro = str(ex)
            e = _escola_ou_404(eid)
    alunos_por_turma = dict(db.session.query(Aluno.turma_id, func.count(Aluno.id))
                            .filter(Aluno.escola_id == e.id).group_by(Aluno.turma_id).all())
    return render_template("admin/escola_form.html", e=e, erro=erro, form=request.form if erro else None,
                           ANOS=esc.ANOS_PADRAO, alunos_por_turma=alunos_por_turma)


@bp.post("/escolas/<int:eid>/turmas")
@permissao_obrigatoria("escolas")
def escola_turmas(eid):
    e = _escola_ou_404(eid)
    try:
        if request.form.get("acao") == "excluir":
            esc.excluir_turma(admin_atual(), e, request.form.get("turma_id", type=int) or 0)
            msg = "Turma excluída."
        else:
            n = esc.criar_turmas(admin_atual(), e, request.form.getlist("anos"), request.form.get("letras", ""))
            msg = f"{n} turma(s) criada(s)." if n else "Nenhuma turma nova (todas já existiam)."
        db.session.commit()
        flash(msg, "sucesso")
    except esc.ErroEscola as ex:
        db.session.rollback()
        flash(str(ex), "erro")
    return redirect(url_for("admin.escola_editar", eid=e.id) + "#turmas")


@bp.post("/escolas/<int:eid>/excluir")
@permissao_obrigatoria("escolas")
def escola_excluir(eid):
    e = _escola_ou_404(eid)
    nome = e.nome
    resultado = esc.excluir(admin_atual(), e)
    db.session.commit()
    if resultado == "excluida":
        flash(f"Escola {nome} excluída.", "sucesso")
    else:
        flash(f"{nome} possui alunos, usuários ou passeios vinculados: foi desativada (histórico preservado).",
              "sucesso")
    return redirect(url_for("admin.escolas"))


@bp.route("/escolas/importar", methods=["GET", "POST"])
@permissao_obrigatoria("escolas")
def escolas_importar():
    relatorio = None
    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione o arquivo JSON.", "erro")
        else:
            try:
                relatorio = esc.importar_arquivo(arquivo.read(5 * 1024 * 1024), admin_atual())
                db.session.commit()
            except esc.ErroEscola as ex:
                db.session.rollback()
                flash(str(ex), "erro")
    return render_template("admin/escolas_importar.html", relatorio=relatorio)

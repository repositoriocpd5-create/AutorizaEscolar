"""Painel administrativo (acesso separado, com usuário e senha)."""
import re
from datetime import datetime

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template, request,
                   session, url_for)

from .. import audit
from ..extensions import db
from ..formatacao import agora_local
from ..models import (Aluno, AdminUsuario, AuditLog, Autorizacao, Documento, Escola, Passeio,
                      PasseioAluno, Perfil, PERMISSOES, PERMISSOES_PADRAO_COMUM, PERMISSOES_SOMENTE_REDE,
                      Situacao, TEXTO_DECLARACAO_PADRAO, TEXTO_TERMO_PADRAO, Turma)
from ..security import (admin_atual, admin_obrigatorio, client_ip, excedeu_limite, permissao_obrigatoria,
                        registrar_tentativa)
from ..services import admin_auth_service, config_service, midia_service, supabase_admin
from ..services import relatorio_service as rel
from ..services.autorizacao_service import ErroNegocio, cancelar_pela_escola, revogar_varias
from ..services.passeio_service import estado_passeio, sincronizar_participantes
from .public import enviar_pdf

bp = Blueprint("admin", __name__)
POR_PAGINA = 25


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        login_ = request.form.get("login", "").strip()[:160]
        senha = request.form.get("senha", "")
        chave_ip, chave_login = f"adm-ip:{client_ip()}", f"adm:{login_.lower()[:90]}"
        if excedeu_limite(chave_ip, 10) or excedeu_limite(chave_login, 5):
            erro = "Muitas tentativas. Aguarde alguns minutos."
        else:
            resultado = admin_auth_service.autenticar(login_, senha)
            adm = resultado.admin
            if adm is not None:
                registrar_tentativa(chave_ip, True)
                session.clear()
                session.permanent = True
                session["admin_id"] = adm.id
                audit.registrar(audit.Acao.ADMIN_LOGIN, "ADMIN", adm.id)
                destino = request.args.get("proximo", "")
                # Evita redirecionamento aberto.
                if not destino.startswith("/admin") or destino.startswith("//"):
                    destino = url_for("admin.dashboard")
                return redirect(destino)
            if resultado.falha_credencial:
                registrar_tentativa(chave_ip, False)
                registrar_tentativa(chave_login, False)
            audit.registrar(audit.Acao.ADMIN_LOGIN_FALHA, "PUBLICO")
            erro = resultado.erro
    return render_template("admin/login.html", erro=erro, modo_supabase=admin_auth_service.modo_supabase())


@bp.post("/sair")
def sair():
    session.clear()
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------------------
# Dashboard e listagem
# ---------------------------------------------------------------------------
def _passeios_visiveis():
    return Passeio.query.order_by(Passeio.ativo.desc(), Passeio.data.desc()).all()


def _passeio_selecionado():
    pid = request.args.get("passeio")
    passeios = _passeios_visiveis()
    if pid:
        p = next((x for x in passeios if x.public_id == pid), None)
        if p is None:
            abort(404)
        return p, passeios
    return (passeios[0] if passeios else None), passeios


def _filtros():
    return {k: request.args.get(k, "").strip() for k in rel.FILTROS}


def _opcoes_filtro(adm, passeio=None):
    """Opções dos filtros: somente escolas/turmas participantes do passeio e no escopo do usuário."""
    turmas_q = Turma.query.join(Escola)
    if passeio is not None:
        turmas_q = turmas_q.filter(Turma.id.in_(
            db.session.query(Aluno.turma_id).join(PasseioAluno, PasseioAluno.aluno_id == Aluno.id)
            .filter(PasseioAluno.passeio_id == passeio.id)))
    if adm.escola_id:
        turmas_q = turmas_q.filter(Turma.escola_id == adm.escola_id)
    turmas = turmas_q.order_by(Turma.ano, Turma.nome, Escola.nome).all()
    escolas = sorted({t.escola for t in turmas}, key=lambda e: e.nome)
    anos = sorted({t.ano for t in turmas}, key=lambda a: (len(a), a))
    return escolas, turmas, anos


@bp.get("/")
@admin_obrigatorio
def dashboard():
    adm = admin_atual()
    passeio, passeios = _passeio_selecionado()
    if passeio is None:
        return render_template("admin/dashboard.html", passeio=None, passeios=[])
    filtros = _filtros()
    linhas = rel.consultar(passeio, filtros, adm)
    base = rel.consultar(passeio, {k: v for k, v in filtros.items() if k != "situacao"}, adm)
    pagina = max(1, request.args.get("pagina", 1, type=int))
    total_paginas = max(1, (len(linhas) + POR_PAGINA - 1) // POR_PAGINA)
    pagina = min(pagina, total_paginas)
    escolas, turmas, anos = _opcoes_filtro(adm, passeio)
    total_revogaveis = sum(1 for l in linhas if l.autorizacao and l.situacao in Situacao.RESPOSTAS_RESPONSAVEL)
    return render_template(
        "admin/dashboard.html", total_revogaveis=total_revogaveis, passeio=passeio, passeios=passeios, estado=estado_passeio(passeio),
        ind=rel.indicadores(base), linhas=linhas[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA],
        total_linhas=len(linhas), pagina=pagina, total_paginas=total_paginas, filtros=filtros,
        escolas=escolas, turmas=turmas, anos=anos, Situacao=Situacao, relatorios=rel.RELATORIOS)


@bp.get("/exportar")
@permissao_obrigatoria("exportar")
def exportar():
    adm = admin_atual()
    passeio, _ = _passeio_selecionado()
    if passeio is None:
        abort(404)
    tipo = request.args.get("relatorio", "geral")
    if tipo not in rel.RELATORIOS:
        abort(400)
    formato = request.args.get("formato", "csv")
    titulo, fixos = rel.RELATORIOS[tipo]
    filtros = {**_filtros(), **fixos}
    linhas = rel.consultar(passeio, filtros, adm)
    audit.registrar(audit.Acao.ADMIN_EXPORTACAO, "ADMIN", adm.id, alvo=f"passeio:{passeio.public_id}",
                    detalhes={"relatorio": tipo, "formato": formato, "linhas": len(linhas)})
    nome = f"{tipo}-{agora_local():%Y%m%d-%H%M}"
    if formato == "csv":
        return Response(rel.exportar_csv(linhas), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{nome}.csv"'})
    if formato == "xlsx":
        return Response(rel.exportar_xlsx(linhas, titulo, passeio),
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{nome}.xlsx"'})
    if formato == "pdf":
        return Response(rel.exportar_pdf(linhas, titulo, passeio, config_service.obter("instituicao_nome")),
                        mimetype="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{nome}.pdf"'})
    abort(400)


@bp.get("/relatorios")
@permissao_obrigatoria("exportar")
def relatorios():
    passeio, passeios = _passeio_selecionado()
    escolas, turmas, anos = _opcoes_filtro(admin_atual(), passeio)
    return render_template("admin/relatorios.html", passeio=passeio, passeios=passeios,
                           relatorios=rel.RELATORIOS, escolas=escolas, turmas=turmas, anos=anos,
                           filtros=_filtros())


@bp.get("/imprimir")
@permissao_obrigatoria("exportar")
def imprimir():
    passeio, _ = _passeio_selecionado()
    if passeio is None:
        abort(404)
    tipo = request.args.get("relatorio", "geral")
    titulo, fixos = rel.RELATORIOS.get(tipo, rel.RELATORIOS["geral"])
    linhas = rel.consultar(passeio, {**_filtros(), **fixos}, admin_atual())
    return render_template("admin/imprimir.html", passeio=passeio, titulo=titulo, linhas=linhas,
                           ind=rel.indicadores(linhas), gerado=agora_local())


# ---------------------------------------------------------------------------
# Detalhe do aluno / autorização
# ---------------------------------------------------------------------------
def _aluno_no_escopo(public_id) -> Aluno:
    aluno = Aluno.query.filter_by(public_id=public_id).first()
    adm = admin_atual()
    if aluno is None or (adm.escola_id and aluno.escola_id != adm.escola_id):
        abort(404)
    return aluno


@bp.get("/passeios/<passeio_id>/alunos/<aluno_id>")
@admin_obrigatorio
def aluno_detalhe(passeio_id, aluno_id):
    passeio = Passeio.query.filter_by(public_id=passeio_id).first_or_404()
    aluno = _aluno_no_escopo(aluno_id)
    if not PasseioAluno.query.filter_by(passeio_id=passeio.id, aluno_id=aluno.id).first():
        abort(404)
    aut = Autorizacao.query.filter_by(passeio_id=passeio.id, aluno_id=aluno.id).first()
    docs = []
    if aut:
        ids = {h.documento_id for h in aut.historico if h.documento_id}
        docs = Documento.query.filter(Documento.id.in_(ids or [0])).order_by(Documento.data_registro.desc()).all()
    return render_template("admin/aluno.html", passeio=passeio, aluno=aluno, aut=aut, docs=docs,
                           Situacao=Situacao, AdminUsuario=AdminUsuario)


@bp.post("/autorizacoes/<public_id>/cancelar")
@permissao_obrigatoria("revogar")
def cancelar(public_id):
    aut = Autorizacao.query.filter_by(public_id=public_id).first_or_404()
    _aluno_no_escopo(aut.aluno.public_id)
    try:
        cancelar_pela_escola(admin_atual(), aut, request.form.get("motivo", ""))
        flash("Autorização revogada. O responsável poderá responder novamente dentro do prazo.", "sucesso")
    except ErroNegocio as e:
        flash(e.mensagem, "erro")
    return redirect(url_for("admin.aluno_detalhe", passeio_id=aut.passeio.public_id, aluno_id=aut.aluno.public_id))


@bp.post("/autorizacoes/revogar")
@permissao_obrigatoria("revogar")
def revogar_lote():
    """Revogação de uma ou várias autorizações com um único motivo."""
    adm = admin_atual()
    f = request.form
    voltar = f.get("voltar", "")
    if not voltar.startswith("/admin") or voltar.startswith("//"):
        voltar = url_for("admin.dashboard")
    passeio = Passeio.query.filter_by(public_id=f.get("passeio", "")).first_or_404()
    if f.get("todos_filtrados") == "1":
        # Recalcula no servidor exatamente o conjunto do filtro (respeitando o escopo do usuário).
        filtros = {k: f.get(f"f_{k}", "").strip() for k in rel.FILTROS}
        auts = [l.autorizacao for l in rel.consultar(passeio, filtros, adm) if l.autorizacao]
    else:
        ids = [x for x in f.getlist("aut") if x][:LIMITE_IDS]
        auts = Autorizacao.query.filter(Autorizacao.public_id.in_(ids or ["-"]),
                                        Autorizacao.passeio_id == passeio.id).all()
    try:
        n = revogar_varias(adm, auts, f.get("motivo", ""))
        flash(f"{n} autorização(ões) revogada(s). Os responsáveis poderão responder novamente dentro do prazo.",
              "sucesso")
    except ErroNegocio as e:
        flash(e.mensagem, "erro")
    return redirect(voltar)


LIMITE_IDS = 2000


@bp.get("/documentos/<public_id>/pdf")
@admin_obrigatorio
def documento_pdf(public_id):
    doc = Documento.query.filter_by(public_id=public_id).first_or_404()
    adm = admin_atual()
    if adm.escola_id and not any(i.autorizacao.aluno.escola_id == adm.escola_id for i in doc.itens):
        abort(404)
    return enviar_pdf(doc, "ADMIN", adm.id)


# ---------------------------------------------------------------------------
# Cadastro de passeios
# ---------------------------------------------------------------------------
@bp.get("/passeios")
@admin_obrigatorio
def passeios():
    lista = [(p, estado_passeio(p), len(p.participantes)) for p in _passeios_visiveis()]
    return render_template("admin/passeios.html", lista=lista)


def _ler_form_passeio(p: Passeio) -> list[str]:
    f = request.form
    erros = []

    def obrig(campo, rotulo, maximo=200):
        v = f.get(campo, "").strip()
        if not v:
            erros.append(f"Informe: {rotulo}.")
        return v[:maximo]

    p.nome = obrig("nome", "nome", 160)
    p.descricao = f.get("descricao", "").strip() or None
    p.destino = obrig("destino", "destino")
    p.local_saida = obrig("local_saida", "local de saída")
    p.transporte = f.get("transporte", "").strip()[:200] or None
    p.orientacoes = f.get("orientacoes", "").strip() or None
    try:
        p.data = datetime.strptime(f.get("data", ""), "%Y-%m-%d").date()
        p.hora_saida = datetime.strptime(f.get("hora_saida", ""), "%H:%M").time()
        p.hora_retorno = datetime.strptime(f.get("hora_retorno", ""), "%H:%M").time()
        p.data_limite = datetime.strptime(f.get("data_limite", ""), "%Y-%m-%dT%H:%M")
    except ValueError:
        erros.append("Verifique as datas e horários informados.")
    else:
        if p.data_limite.date() > p.data:
            erros.append("O prazo para autorização deve ser anterior ou igual à data do passeio.")
    p.permite_alteracao = f.get("permite_alteracao") == "1"
    p.ativo = f.get("ativo") == "1"
    horas = f.get("prazo_alteracao_horas", "").strip()
    if horas and (not horas.isdigit() or not 1 <= int(horas) <= 24 * 90):
        erros.append("Prazo para alterar/cancelar: informe um número de horas entre 1 e 2160, ou deixe em branco.")
    p.prazo_alteracao_horas = int(horas) if horas.isdigit() and int(horas) > 0 else None
    texto = f.get("texto_declaracao", "").strip() or TEXTO_DECLARACAO_PADRAO
    termo = f.get("texto_termo", "").strip() or TEXTO_TERMO_PADRAO
    if p.id and (texto != p.texto_declaracao or termo != p.texto_termo):
        p.versao_texto = (p.versao_texto or 1) + 1  # nova versão do texto de autorização
    p.texto_declaracao = texto[:3000]
    p.texto_termo = termo[:500]
    turma_ids = [int(x) for x in f.getlist("turmas") if x.isdigit()]
    p.turmas = Turma.query.filter(Turma.id.in_(turma_ids or [0])).all()
    if not p.turmas:
        erros.append("Selecione ao menos uma turma participante.")
    return erros


@bp.route("/passeios/novo", methods=["GET", "POST"])
@bp.route("/passeios/<public_id>/editar", methods=["GET", "POST"])
@permissao_obrigatoria("passeios")
def passeio_form(public_id=None):
    p = Passeio.query.filter_by(public_id=public_id).first_or_404() if public_id else Passeio(
        texto_declaracao=TEXTO_DECLARACAO_PADRAO, texto_termo=TEXTO_TERMO_PADRAO,
        permite_alteracao=True, ativo=True, versao_texto=1)
    erros = []
    if request.method == "POST":
        with db.session.no_autoflush:
            erros = _ler_form_passeio(p)
            if not erros:
                arquivo = request.files.get("imagem")
                if arquivo and arquivo.filename:
                    try:
                        p.imagem = midia_service.salvar(arquivo, "passeio")
                    except midia_service.ErroImagem as e:
                        erros.append(str(e))
                elif request.form.get("remover_imagem") == "1":
                    p.imagem = None
                escolha = request.form.get("ilustracao", "")
                if escolha in config_service.ILUSTRACOES:
                    p.ilustracao = escolha
        if not erros:
            if not p.id:
                db.session.add(p)
            db.session.flush()
            sincronizar_participantes(p)
            audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", admin_atual().id, alvo=f"passeio:{p.public_id}",
                            detalhes={"acao": "editar_passeio" if public_id else "criar_passeio"}, commit=False)
            db.session.commit()
            if request.form.get("destaque") == "1":
                config_service.definir("passeio_destaque", p.public_id)
                db.session.commit()
            flash("Passeio salvo com sucesso.", "sucesso")
            return redirect(url_for("admin.passeios"))
        db.session.rollback()
    escolas = Escola.query.filter(Escola.ativo.is_(True), Escola.turmas.any()).order_by(Escola.nome)
    selecionadas = {int(x) for x in request.form.getlist("turmas") if x.isdigit()} if request.method == "POST" \
        else {t.id for t in p.turmas}
    return render_template("admin/passeio_form.html", p=p,
                           em_destaque=bool(p.public_id and config_service.obter("passeio_destaque") == p.public_id), erros=erros, escolas=escolas.all(),
                           selecionadas=selecionadas, form=request.form if request.method == "POST" else None)


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------
@bp.get("/auditoria")
@permissao_obrigatoria("auditoria")
def auditoria():
    pagina = max(1, request.args.get("pagina", 1, type=int))
    acao = request.args.get("acao", "")
    q = AuditLog.query
    if acao:
        q = q.filter_by(acao=acao)
    total = q.count()
    registros = q.order_by(AuditLog.id.desc()).offset((pagina - 1) * 50).limit(50).all()
    acoes = [a for a in vars(audit.Acao) if not a.startswith("_")]
    return render_template("admin/auditoria.html", registros=registros, pagina=pagina,
                           total_paginas=max(1, (total + 49) // 50), acoes=acoes, acao=acao)


# ---------------------------------------------------------------------------
# Configurações gerais (somente administradores da rede)
# ---------------------------------------------------------------------------
@bp.route("/configuracoes", methods=["GET", "POST"])
@permissao_obrigatoria("configuracoes")
def configuracoes():
    erros = []
    if request.method == "POST":
        f = request.form
        for chave in ("instituicao_nome", "titulo_sistema", "subtitulo"):
            config_service.definir(chave, f.get(chave, "")[:160])
        destaque = f.get("passeio_destaque", "")
        if destaque and not Passeio.query.filter_by(public_id=destaque).first():
            destaque = ""
        config_service.definir("passeio_destaque", destaque)
        if f.get("ilustracao_inicial") in config_service.ILUSTRACOES:
            config_service.definir("ilustracao_inicial", f.get("ilustracao_inicial"))
        for chave, prefixo, lado in (("brasao", "brasao", 512), ("imagem_inicial", "inicial", 1200)):
            arquivo = request.files.get(chave)
            if arquivo and arquivo.filename:
                try:
                    config_service.definir(chave, midia_service.salvar(arquivo, prefixo, lado))
                except midia_service.ErroImagem as e:
                    erros.append(f"{config_service.CHAVES[chave]}: {e}")
            elif f.get("remover_" + chave) == "1":
                config_service.definir(chave, "")
        if not erros:
            audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", admin_atual().id, alvo="configuracoes",
                            detalhes={"acao": "editar_configuracoes"}, commit=False)
            db.session.commit()
            flash("Configurações salvas.", "sucesso")
            return redirect(url_for("admin.configuracoes"))
        db.session.rollback()
    brasao = config_service.obter("brasao")
    inicial = config_service.obter("imagem_inicial")
    return render_template("admin/configuracoes.html", cfg=config_service.todas(), erros=erros,
                           passeios=_passeios_visiveis(),
                           brasao_personalizado=midia_service.existe(brasao),
                           imagem_inicial_url=config_service.url_midia(
                               inicial, "img/eventos/" + config_service.obter("ilustracao_inicial") + ".svg"),
                           imagem_inicial_personalizada=midia_service.existe(inicial))


# ---------------------------------------------------------------------------
# Usuários do painel: perfis (Administrador/Comum), permissões e escopo
# ---------------------------------------------------------------------------
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ler_perfil_e_acesso(u: AdminUsuario, f) -> str | None:
    """Aplica perfil, escola e permissões do formulário. Retorna mensagem de erro ou None."""
    perfil = f.get("perfil", Perfil.COMUM)
    if perfil not in Perfil.ROTULOS:
        return "Perfil inválido."
    escola_id = f.get("escola_id", "")
    escola = db.session.get(Escola, int(escola_id)) if escola_id.isdigit() else None
    if escola_id and escola is None:
        return "Unidade escolar inválida."
    u.perfil = perfil
    u.escola_id = escola.id if escola else None
    perms = set(f.getlist("permissoes")) if perfil == Perfil.COMUM else set()
    if u.escola_id:
        perms -= PERMISSOES_SOMENTE_REDE  # nunca valem para usuários de escola
    u.definir_permissoes(perms)
    return None


def _restara_admin_rede(excluindo: AdminUsuario | None = None) -> bool:
    q = AdminUsuario.query.filter_by(ativo=True, perfil=Perfil.ADMIN, escola_id=None)
    if excluindo is not None and excluindo.id:
        q = q.filter(AdminUsuario.id != excluindo.id)
    return q.count() > 0


def _contexto_usuarios(**extra):
    return dict(
        modo_supabase=admin_auth_service.modo_supabase(), supabase_admin_ok=supabase_admin.disponivel(),
        escolas=Escola.query.order_by(Escola.nome).all(), PERMISSOES=PERMISSOES,
        PERMISSOES_SOMENTE_REDE=PERMISSOES_SOMENTE_REDE, Perfil=Perfil,
        PERMISSOES_PADRAO_COMUM=PERMISSOES_PADRAO_COMUM, **extra)


def _auditar_usuario(u, acao, **detalhes):
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", admin_atual().id, alvo=f"admin:{u.id}",
                    detalhes={"acao": acao, **detalhes}, commit=False)


@bp.route("/usuarios", methods=["GET", "POST"])
@permissao_obrigatoria("usuarios")
def usuarios():
    erro = None
    supabase = admin_auth_service.modo_supabase()
    if request.method == "POST":
        f = request.form
        login_ = f.get("login", "").strip().lower()[:160 if supabase else 60]
        nome = f.get("nome", "").strip()[:120]
        senha = f.get("senha", "")
        criacao = f.get("criacao", "existente")  # existente | senha | convite
        u = AdminUsuario(nome=nome, login=login_[:60], email=login_ if supabase else None, ativo=True)
        if not login_ or not nome:
            erro = "Informe nome e " + ("e-mail." if supabase else "usuário.")
        elif supabase and not RE_EMAIL.match(login_):
            erro = "Informe um e-mail válido."
        elif AdminUsuario.query.filter((AdminUsuario.login == login_[:60]) | (AdminUsuario.email == login_)).first():
            erro = "Já existe um usuário com este login/e-mail no painel."
        elif (not supabase or criacao == "senha") and len(senha) < 10:
            erro = "A senha deve ter pelo menos 10 caracteres."
        elif supabase and criacao in ("senha", "convite") and not supabase_admin.disponivel():
            erro = "Para criar a conta no Supabase por aqui, configure SUPABASE_SECRET_KEY no servidor."
        else:
            erro = _ler_perfil_e_acesso(u, f)
        if not erro:
            try:
                if not supabase:
                    u.definir_senha(senha)
                elif criacao == "senha":
                    u.supabase_id = supabase_admin.criar_usuario(login_, senha, nome)
                elif criacao == "convite":
                    u.supabase_id = supabase_admin.convidar(login_, nome)
            except supabase_admin.ErroSupabase as e:
                erro = str(e)
        if not erro:
            db.session.add(u)
            db.session.flush()
            _auditar_usuario(u, "criar_usuario", login=login_, perfil=u.perfil, criacao=criacao,
                             escola=u.escola.codigo if u.escola else "rede", permissoes=u.permissoes)
            db.session.commit()
            msg = {"convite": "Convite enviado por e-mail.", "senha": "Conta criada no Supabase com a senha informada."}
            flash(f"Usuário {login_} cadastrado. " + msg.get(criacao if supabase else "", ""), "sucesso")
            return redirect(url_for("admin.usuarios"))
    lista = AdminUsuario.query.order_by(AdminUsuario.ativo.desc(), AdminUsuario.nome).all()
    return render_template("admin/usuarios.html", lista=lista, erro=erro, form=request.form,
                           **_contexto_usuarios())


@bp.route("/usuarios/<int:uid>", methods=["GET", "POST"])
@permissao_obrigatoria("usuarios")
def usuario_editar(uid):
    u = db.session.get(AdminUsuario, uid) or abort(404)
    proprio = u.id == admin_atual().id
    erro = None
    if request.method == "POST":
        f = request.form
        antes = {"perfil": u.perfil, "escola": u.escola_id, "permissoes": u.permissoes}
        nome = f.get("nome", "").strip()[:120]
        if not nome:
            erro = "Informe o nome."
        elif proprio:
            u.nome = nome  # não altera o próprio perfil/escopo (evita perder o acesso)
        else:
            with db.session.no_autoflush:
                erro = _ler_perfil_e_acesso(u, f)
                if not erro and antes["perfil"] == Perfil.ADMIN and antes["escola"] is None \
                        and not (u.perfil == Perfil.ADMIN and u.escola_id is None) and not _restara_admin_rede(u):
                    erro = "É necessário manter ao menos um Administrador da rede ativo."
            u.nome = nome
        if erro:
            db.session.rollback()
        else:
            _auditar_usuario(u, "editar_usuario", antes=antes,
                             depois={"perfil": u.perfil, "escola": u.escola_id, "permissoes": u.permissoes})
            db.session.commit()
            flash("Usuário atualizado.", "sucesso")
            return redirect(url_for("admin.usuarios"))
    return render_template("admin/usuario_form.html", u=u, proprio=proprio, erro=erro, **_contexto_usuarios())


@bp.post("/usuarios/<int:uid>/ativo")
@permissao_obrigatoria("usuarios")
def usuario_ativo(uid):
    u = db.session.get(AdminUsuario, uid) or abort(404)
    if u.id == admin_atual().id:
        flash("Você não pode desativar o próprio usuário.", "erro")
        return redirect(url_for("admin.usuarios"))
    novo = not u.ativo
    if not novo and u.perfil == Perfil.ADMIN and u.escola_id is None and not _restara_admin_rede(u):
        flash("É necessário manter ao menos um Administrador da rede ativo.", "erro")
        return redirect(url_for("admin.usuarios"))
    aviso = ""
    if u.email and supabase_admin.disponivel():
        try:
            u.supabase_id = u.supabase_id or supabase_admin.buscar_id(u.email)
            if u.supabase_id:
                supabase_admin.bloquear(u.supabase_id, bloqueado=not novo)
                aviso = " Também foi " + ("desbloqueado" if novo else "bloqueado") + " no Supabase."
        except supabase_admin.ErroSupabase as e:
            aviso = f" Atenção: não foi possível atualizar o Supabase ({e})."
    u.ativo = novo
    _auditar_usuario(u, "ativar" if novo else "desativar")
    db.session.commit()
    estado = "ativado" if novo else "desativado"
    flash(f"Usuário {u.email or u.login} {estado}.{aviso}", "sucesso" if "Atenção" not in aviso else "erro")
    return redirect(url_for("admin.usuarios"))


@bp.post("/usuarios/<int:uid>/senha")
@permissao_obrigatoria("usuarios")
def usuario_senha(uid):
    u = db.session.get(AdminUsuario, uid) or abort(404)
    modo = request.form.get("modo", "definir")  # definir | link
    senha = request.form.get("senha", "")
    try:
        if not admin_auth_service.modo_supabase():
            if len(senha) < 10:
                raise supabase_admin.ErroSupabase("A nova senha deve ter pelo menos 10 caracteres.")
            u.definir_senha(senha)
            msg = f"Senha de {u.login} redefinida."
        elif modo == "link":
            supabase_admin.enviar_redefinicao(u.email)
            msg = f"Link de redefinição de senha enviado para {u.email}."
        else:
            if not supabase_admin.disponivel():
                raise supabase_admin.ErroSupabase("Configure SUPABASE_SECRET_KEY para definir senhas por aqui.")
            if len(senha) < 10:
                raise supabase_admin.ErroSupabase("A nova senha deve ter pelo menos 10 caracteres.")
            u.supabase_id = u.supabase_id or supabase_admin.buscar_id(u.email)
            if not u.supabase_id:
                raise supabase_admin.ErroSupabase("Usuário não encontrado no Supabase Authentication.")
            supabase_admin.definir_senha(u.supabase_id, senha)
            msg = f"Senha de {u.email} redefinida no Supabase."
    except supabase_admin.ErroSupabase as e:
        flash(str(e), "erro")
        return redirect(url_for("admin.usuario_editar", uid=u.id))
    _auditar_usuario(u, "redefinir_senha", modo=modo)
    db.session.commit()
    flash(msg, "sucesso")
    return redirect(url_for("admin.usuario_editar", uid=u.id))


@bp.get("/definir-senha")
def definir_senha():
    """Destino dos e-mails de convite e de redefinição do Supabase. O token chega no
    fragmento da URL (#access_token=...) e é usado apenas pelo navegador."""
    return render_template("admin/definir_senha.html",
                           supabase_url=current_app.config.get("SUPABASE_URL", ""),
                           supabase_key=current_app.config.get("SUPABASE_PUBLISHABLE_KEY", ""))


# Rotas de cadastro de responsáveis/alunos (mesmo blueprint).
from . import admin_cadastros  # noqa: E402,F401
from . import admin_escolas  # noqa: E402,F401

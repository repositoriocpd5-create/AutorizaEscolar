"""Perfis, permissões, escopo e gestão de usuários do painel (inclui Supabase simulado)."""
import io
import json
import urllib.error

import pytest

from app.extensions import db
from app.models import AdminUsuario, Autorizacao, Escola, Passeio, Perfil, Situacao
from tests.test_admin_filtros import entrar_admin, get, total
from tests.test_fluxo import app, client, csrf  # noqa: F401  (fixtures)


def _criar(client, token, **dados):
    base = {"_csrf": token, "nome": "Fulano", "login": "fulano", "senha": "senha-forte-123"}
    base.update(dados)
    return client.post("/admin/usuarios", data=base)


def _sair(client):
    token = csrf(client, "/admin/")
    client.post("/admin/sair", data={"_csrf": token})


# ---------------------------------------------------------------------------
# Modo local (sem Supabase)
# ---------------------------------------------------------------------------
def test_comum_so_consulta_por_padrao(client):
    token = entrar_admin(client)
    assert _criar(client, token, perfil="COMUM").status_code == 302
    u = AdminUsuario.query.filter_by(login="fulano").one()
    assert u.perfil == Perfil.COMUM and u.lista_permissoes == set()
    _sair(client)
    entrar_admin(client, "fulano", "senha-forte-123")
    html = client.get("/admin/").get_data(as_text=True)
    assert "Total de alunos" in html
    assert "Revogar selecionados" not in html and 'formato=csv' not in html
    for url in ("/admin/relatorios", "/admin/exportar?formato=csv", "/admin/auditoria", "/admin/usuarios",
                "/admin/configuracoes", "/admin/passeios/novo"):
        assert client.get(url).status_code == 403, url
    p = Passeio.query.first()
    token = csrf(client, "/admin/")
    r = client.post("/admin/autorizacoes/revogar", data={"_csrf": token, "passeio": p.public_id,
                                                          "todos_filtrados": "1", "motivo": "tentativa"})
    assert r.status_code == 403


def test_comum_com_permissoes_marcadas(client):
    token = entrar_admin(client)
    _criar(client, token, perfil="COMUM", permissoes=["exportar", "revogar", "auditoria"])
    _sair(client)
    entrar_admin(client, "fulano", "senha-forte-123")
    assert client.get("/admin/relatorios").status_code == 200
    assert client.get("/admin/auditoria").status_code == 200
    assert client.get("/admin/usuarios").status_code == 403
    assert "Revogar selecionados" in client.get("/admin/").get_data(as_text=True)


def test_usuario_de_escola_nunca_recebe_permissoes_de_rede(client):
    token = entrar_admin(client)
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    _criar(client, token, perfil="COMUM", escola_id=str(e1.id),
           permissoes=["usuarios", "configuracoes", "passeios", "auditoria", "revogar"])
    u = AdminUsuario.query.filter_by(login="fulano").one()
    assert u.lista_permissoes == {"revogar"}
    # Administrador de escola: tudo dentro da escola, nada de rede
    _criar(client, token, login="diretor", perfil="ADMIN", escola_id=str(e1.id))
    d = AdminUsuario.query.filter_by(login="diretor").one()
    assert d.pode("revogar") and d.pode("exportar")
    assert not d.pode("usuarios") and not d.pode("configuracoes") and not d.pode("auditoria")


def test_editar_perfil_e_protecoes(client):
    token = entrar_admin(client)
    eu = AdminUsuario.query.filter_by(login="admin").one()
    _criar(client, token, perfil="COMUM")
    u = AdminUsuario.query.filter_by(login="fulano").one()
    r = client.post(f"/admin/usuarios/{u.id}", data={"_csrf": token, "nome": "Fulano de Tal", "perfil": "ADMIN",
                                                     "escola_id": ""})
    assert r.status_code == 302
    db.session.refresh(u)
    assert u.perfil == Perfil.ADMIN and u.nome == "Fulano de Tal"
    # Não altera o próprio perfil
    client.post(f"/admin/usuarios/{eu.id}", data={"_csrf": token, "nome": "Eu", "perfil": "COMUM"})
    db.session.refresh(eu)
    assert eu.perfil == Perfil.ADMIN and eu.nome == "Eu"
    # Não desativa a si mesmo
    client.post(f"/admin/usuarios/{eu.id}/ativo", data={"_csrf": token})
    db.session.refresh(eu)
    assert eu.ativo


def test_manter_ao_menos_um_admin_da_rede(client):
    token = entrar_admin(client)
    _criar(client, token, perfil="ADMIN")  # segundo admin da rede
    outro = AdminUsuario.query.filter_by(login="fulano").one()
    _sair(client)
    token = entrar_admin(client, "fulano", "senha-forte-123")
    eu = AdminUsuario.query.filter_by(login="admin").one()
    # fulano desativa o admin original: permitido (fulano continua admin da rede)
    client.post(f"/admin/usuarios/{eu.id}/ativo", data={"_csrf": token})
    db.session.refresh(eu)
    assert eu.ativo is False
    # rebaixar a si mesmo é bloqueado; e não há outro admin ativo para rebaixar
    client.post(f"/admin/usuarios/{outro.id}", data={"_csrf": token, "nome": "x", "perfil": "COMUM"})
    db.session.refresh(outro)
    assert outro.perfil == Perfil.ADMIN


def test_desativado_perde_acesso_imediatamente(client):
    token = entrar_admin(client)
    _criar(client, token, perfil="COMUM")
    u = AdminUsuario.query.filter_by(login="fulano").one()
    _sair(client)
    entrar_admin(client, "fulano", "senha-forte-123")
    assert client.get("/admin/").status_code == 200
    u.ativo = False
    db.session.commit()
    assert client.get("/admin/").status_code == 302  # sessão invalidada


# ---------------------------------------------------------------------------
# Modo Supabase com chave secreta (HTTP simulado)
# ---------------------------------------------------------------------------
@pytest.fixture()
def supabase(app, monkeypatch):
    from app.services import admin_auth_service, supabase_admin
    app.config.update(SUPABASE_URL="https://ex.supabase.co", SUPABASE_PUBLISHABLE_KEY="sb_publishable_x",
                      SUPABASE_SECRET_KEY="sb_secret_x", ADMIN_EMAILS={"chefe@rede.gov.br"})
    chamadas = []

    class Resp:
        def __init__(self, dados):
            self.dados = dados

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.dados).encode()

    def falso(req, timeout=10):
        corpo = json.loads(req.data.decode()) if req.data else {}
        chamadas.append((req.get_method(), req.full_url, dict(req.header_items()), corpo))
        url = req.full_url
        if "/auth/v1/token" in url:
            if corpo.get("password") != "senha-certa-123":
                raise urllib.error.HTTPError(url, 400, "x", {}, io.BytesIO(b"{}"))
            return Resp({"user": {"email": corpo["email"], "id": "uid-" + corpo["email"]}})
        if url.endswith("/auth/v1/admin/users") and req.get_method() == "POST":
            if corpo["email"] == "existe@x.gov.br":
                raise urllib.error.HTTPError(url, 422, "x", {}, io.BytesIO(
                    b'{"msg":"A user with this email address has already been registered","error_code":"email_exists"}'))
            return Resp({"id": "novo-id"})
        if "/auth/v1/invite" in url:
            return Resp({"id": "convite-id"})
        if "/auth/v1/admin/users/" in url and req.get_method() == "PUT":
            return Resp({"id": url.rsplit("/", 1)[1]})
        if "/auth/v1/recover" in url:
            return Resp({})
        raise AssertionError(url)

    monkeypatch.setattr(admin_auth_service.urllib.request, "urlopen", falso)
    monkeypatch.setattr(supabase_admin.urllib.request, "urlopen", falso)
    return chamadas


def _entrar_supabase(client, email="chefe@rede.gov.br"):
    token = csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"_csrf": token, "login": email, "senha": "senha-certa-123"})
    assert r.status_code == 302
    return csrf(client, "/admin/usuarios")


def test_supabase_convite_senha_e_existente(client, supabase):
    token = _entrar_supabase(client)
    # Convite por e-mail
    r = client.post("/admin/usuarios", data={"_csrf": token, "nome": "Ana", "login": "ana@x.gov.br",
                                             "perfil": "COMUM", "permissoes": ["revogar"], "criacao": "convite"})
    assert r.status_code == 302
    ana = AdminUsuario.query.filter_by(email="ana@x.gov.br").one()
    assert ana.supabase_id == "convite-id" and ana.senha_hash is None
    convite = next(c for c in supabase if "/invite" in c[1])
    assert "redirect_to=" in convite[1] and "definir-senha" in convite[1]
    assert convite[2].get("Apikey") == "sb_secret_x" and "Authorization" not in convite[2]
    # Senha inicial
    client.post("/admin/usuarios", data={"_csrf": token, "nome": "Beto", "login": "beto@x.gov.br",
                                         "perfil": "ADMIN", "criacao": "senha", "senha": "senha-inicial-1"})
    assert AdminUsuario.query.filter_by(email="beto@x.gov.br").one().supabase_id == "novo-id"
    # E-mail já existente no Supabase com "definir senha": erro claro, nada criado
    r = client.post("/admin/usuarios", data={"_csrf": token, "nome": "C", "login": "existe@x.gov.br",
                                             "perfil": "COMUM", "criacao": "senha", "senha": "senha-inicial-1"})
    assert "Já existe um usuário com este e-mail no Supabase" in r.get_data(as_text=True)
    assert AdminUsuario.query.filter_by(email="existe@x.gov.br").first() is None
    # "Já existe no Supabase": só autoriza
    client.post("/admin/usuarios", data={"_csrf": token, "nome": "C", "login": "existe@x.gov.br",
                                         "perfil": "COMUM", "criacao": "existente"})
    assert AdminUsuario.query.filter_by(email="existe@x.gov.br").one().supabase_id is None


def test_supabase_desativar_bloqueia_e_reativar_desbloqueia(client, supabase):
    token = _entrar_supabase(client)
    client.post("/admin/usuarios", data={"_csrf": token, "nome": "Ana", "login": "ana@x.gov.br",
                                         "perfil": "COMUM", "criacao": "convite"})
    ana = AdminUsuario.query.filter_by(email="ana@x.gov.br").one()
    client.post(f"/admin/usuarios/{ana.id}/ativo", data={"_csrf": token})
    ban = [c for c in supabase if c[0] == "PUT" and "convite-id" in c[1]][-1]
    assert ban[3] == {"ban_duration": "876000h"}
    db.session.refresh(ana)
    assert ana.ativo is False
    client.post(f"/admin/usuarios/{ana.id}/ativo", data={"_csrf": token})
    assert [c for c in supabase if c[0] == "PUT" and "convite-id" in c[1]][-1][3] == {"ban_duration": "none"}


def test_supabase_redefinir_senha(client, supabase):
    token = _entrar_supabase(client)
    client.post("/admin/usuarios", data={"_csrf": token, "nome": "Ana", "login": "ana@x.gov.br",
                                         "perfil": "COMUM", "criacao": "convite"})
    ana = AdminUsuario.query.filter_by(email="ana@x.gov.br").one()
    client.post(f"/admin/usuarios/{ana.id}/senha", data={"_csrf": token, "modo": "link"})
    assert any("/auth/v1/recover" in c[1] and c[2].get("Apikey") == "sb_publishable_x" for c in supabase)
    client.post(f"/admin/usuarios/{ana.id}/senha", data={"_csrf": token, "modo": "definir", "senha": "nova-senha-123"})
    assert any(c[0] == "PUT" and c[3] == {"password": "nova-senha-123"} for c in supabase)


def test_pagina_definir_senha(client, app):
    app.config.update(SUPABASE_URL="https://ex.supabase.co", SUPABASE_PUBLISHABLE_KEY="sb_publishable_x")
    r = client.get("/admin/definir-senha")
    assert r.status_code == 200 and "https://ex.supabase.co" in r.headers["Content-Security-Policy"]
    assert "sb_secret" not in r.get_data(as_text=True)

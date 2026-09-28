"""Testes de ponta a ponta das regras principais."""
import hashlib
import re
from datetime import timedelta

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.formatacao import agora_local
from app.models import (Aluno, Autorizacao, AutorizacaoHistorico, Documento, Passeio, Situacao)
from app.security import cpf_valido


class Cfg(TestConfig):
    DOCUMENTOS_DIR = None  # definido no fixture


@pytest.fixture()
def app(tmp_path):
    Cfg.DOCUMENTOS_DIR = str(tmp_path / "docs")
    app = create_app(Cfg)
    with app.app_context():
        db.create_all()
        from seeds.demo import popular
        popular()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf(client, url="/"):
    html = client.get(url, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def login(client, cpf="000.000.000-00"):
    token = csrf(client)
    r = client.post("/api/auth/responsavel", json={"cpf": cpf}, headers={"X-CSRF-Token": token})
    return r, r.get_json().get("csrf", token)


def meus(client, token):
    pid = Passeio.query.first().public_id
    r = client.get(f"/api/passeios/{pid}/meus-alunos")
    return pid, r.get_json()["alunos"]


def test_validacao_cpf():
    assert cpf_valido("52998224725")
    assert not cpf_valido("52998224724")
    assert not cpf_valido("11111111111")


def test_login_cpf_invalido_e_inexistente(client):
    token = csrf(client)
    r = client.post("/api/auth/responsavel", json={"cpf": "123.456.789-00"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 400 and "CPF inválido" in r.get_json()["erro"]
    r = client.post("/api/auth/responsavel", json={"cpf": "111.444.777-35"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 404 and "Não encontramos" in r.get_json()["erro"]


def test_csrf_obrigatorio(client):
    client.get("/")
    r = client.post("/api/auth/responsavel", json={"cpf": "00000000000"})
    assert r.status_code == 400


def test_limite_de_tentativas(client):
    token = csrf(client)
    for _ in range(5):
        client.post("/api/auth/responsavel", json={"cpf": "111.444.777-35"}, headers={"X-CSRF-Token": token})
    r = client.post("/api/auth/responsavel", json={"cpf": "111.444.777-35"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 429


def test_fluxo_completo_autorizacao(client, app):
    r, token = login(client)
    assert r.status_code == 200
    pid, alunos = meus(client, token)
    assert {a["aluno"]["nome"] for a in alunos} == {"Pedro da Silva", "Maria da Silva"}
    assert all(a["situacao"] == "AGUARDANDO" for a in alunos)

    corpo = {"autorizacoes": [{"aluno_id": a["aluno"]["id"], "situacao": "AUTORIZADO"} for a in alunos],
             "declaracao_aceita": True}
    r = client.post(f"/api/passeios/{pid}/autorizacoes", json=corpo, headers={"X-CSRF-Token": token})
    assert r.status_code == 201, r.get_json()
    dados = r.get_json()
    assert re.match(r"AUT-\d{4}-\d{6}", dados["protocolo"])

    doc = Documento.query.filter_by(public_id=dados["documento_id"]).one()
    assert len(doc.itens) == 2                                  # documento único
    assert Autorizacao.query.filter_by(documento_id=doc.id).count() == 2  # registros individuais
    pdf = client.get(dados["pdf_url"])
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert hashlib.sha256(pdf.data).hexdigest() == doc.hash_sha256

    # Sem duplicidade
    r = client.post(f"/api/passeios/{pid}/autorizacoes", json=corpo, headers={"X-CSRF-Token": token})
    assert r.status_code == 409

    # Reabertura mostra "Autorizado"
    _, alunos = meus(client, token)
    assert all(a["situacao"] == "AUTORIZADO" for a in alunos)

    # Validação pública com dados mínimos
    v = client.get(f"/api/validar/{doc.codigo_validacao}").get_json()
    assert v["vigente"] and v["situacao"] == "AUTORIZAÇÃO VÁLIDA"
    assert "cpf" not in str(v).lower()


def test_alteracao_gera_historico_e_substitui_documento(client):
    _, token = login(client)
    pid, alunos = meus(client, token)
    pedro = next(a for a in alunos if a["aluno"]["nome"].startswith("Pedro"))["aluno"]["id"]
    h = {"X-CSRF-Token": token}
    r1 = client.post(f"/api/passeios/{pid}/autorizacoes", headers=h, json={
        "autorizacoes": [{"aluno_id": pedro, "situacao": "AUTORIZADO"}], "declaracao_aceita": True}).get_json()
    r2 = client.post(f"/api/passeios/{pid}/autorizacoes", headers=h, json={
        "autorizacoes": [{"aluno_id": pedro, "situacao": "NAO_AUTORIZADO"}], "declaracao_aceita": True})
    assert r2.status_code == 201
    aut = Autorizacao.query.join(Aluno).filter(Aluno.public_id == pedro).one()
    assert aut.situacao == Situacao.NAO_AUTORIZADO
    assert AutorizacaoHistorico.query.filter_by(autorizacao_id=aut.id).count() == 2
    v = client.get(f"/api/validar/{r1['codigo_validacao']}").get_json()
    assert v["vigente"] is False


def test_prazo_e_bloqueio_de_alteracao(client, app):
    _, token = login(client)
    pid, alunos = meus(client, token)
    p = Passeio.query.first()
    p.data_limite = agora_local() - timedelta(minutes=1)
    db.session.commit()
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": alunos[0]["aluno"]["id"], "situacao": "AUTORIZADO"}],
        "declaracao_aceita": True})
    assert r.status_code == 409


def test_declaracao_obrigatoria(client):
    _, token = login(client)
    pid, alunos = meus(client, token)
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": alunos[0]["aluno"]["id"], "situacao": "AUTORIZADO"}],
        "declaracao_aceita": False})
    assert r.status_code == 400


def test_nao_acessa_aluno_de_outro_responsavel(client):
    _, token = login(client)
    pid, _ = meus(client, token)
    outro = Aluno.query.filter_by(nome="Lucas Souza").one()
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": outro.public_id, "situacao": "AUTORIZADO"}], "declaracao_aceita": True})
    assert r.status_code == 403
    # Documento de outro responsável não é acessível
    _, token2 = login(client, "529.982.247-25")
    pid, alunos = meus(client, token2)
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token2}, json={
        "autorizacoes": [{"aluno_id": alunos[0]["aluno"]["id"], "situacao": "AUTORIZADO"}],
        "declaracao_aceita": True}).get_json()
    login(client)
    assert client.get(r["pdf_url"]).status_code == 404


def test_paginas_renderizam(client):
    assert client.get("/").status_code == 200
    assert client.get("/validar").status_code == 200
    assert client.get("/validar/0000-0000-0000").status_code == 404
    assert client.get("/privacidade").status_code == 200
    assert client.get("/painel").status_code == 302
    login(client)
    r = client.get("/painel", follow_redirects=True)
    assert r.status_code == 200 and "Pedro da Silva" in r.get_data(as_text=True)


def test_admin(client):
    token = csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"login": "admin", "senha": "senha-teste-admin", "_csrf": token})
    assert r.status_code == 302
    html = client.get("/admin/").get_data(as_text=True)
    assert "Total de alunos" in html and "150" in html
    for fmt in ("csv", "xlsx", "pdf"):
        assert client.get(f"/admin/exportar?formato={fmt}&relatorio=autorizados").status_code == 200
    for url in ("/admin/relatorios", "/admin/passeios", "/admin/passeios/novo", "/admin/auditoria",
                "/admin/imprimir?relatorio=aguardando"):
        assert client.get(url).status_code == 200, url
    assert "Pedro" in client.get("/admin/?q=pedro da silva").get_data(as_text=True)


def test_saude_e_url_do_banco(client):
    from app.config import _url_banco
    assert client.get("/saude").get_json() == {"status": "ok"}
    assert _url_banco("postgres://u:s@h:5432/d") == "postgresql+psycopg://u:s@h:5432/d"
    assert _url_banco("postgresql://u:s@h/d") == "postgresql+psycopg://u:s@h/d"
    assert _url_banco("sqlite:///x.db") == "sqlite:///x.db"


def test_imagem_enviada_fica_no_banco(client):
    import io
    from PIL import Image
    from app.models import Midia
    from tests.test_admin_filtros import entrar_admin
    token = entrar_admin(client)
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 0, 0)).save(buf, "JPEG")
    buf.seek(0)
    client.post("/admin/configuracoes", content_type="multipart/form-data", data={
        "_csrf": token, "instituicao_nome": "X", "brasao": (buf, "b.jpg")})
    m = Midia.query.one()
    assert m.dados.startswith(b"\x89PNG")  # regravado em PNG
    r = client.get(f"/midia/{m.nome}")
    assert r.status_code == 200 and r.mimetype == "image/png"

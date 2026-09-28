"""Filtros do painel, configurações, usuários, revogação e prazo de alteração."""
import io
import re
from datetime import timedelta

from PIL import Image

from app.extensions import db
from app.models import (Aluno, Autorizacao, Escola, Passeio, PasseioAluno, Situacao, Turma, utcnow)
from tests.test_fluxo import app, client, csrf, login, meus  # noqa: F401  (fixtures)


def entrar_admin(client, usuario="admin", senha="demo-admin-2026"):
    token = csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"login": usuario, "senha": senha, "_csrf": token})
    assert r.status_code == 302, "login admin falhou"
    return csrf(client, "/admin/")


def total(html):
    return int(re.search(r"(\d+) aluno\(s\) encontrado\(s\)", html).group(1))


def nomes_na_tabela(html):
    return re.findall(r'<a href="/admin/passeios/[^"]+/alunos/[^"]+"><strong>([^<]+)</strong>', html)


def get(client, **params):
    return client.get("/admin/", query_string=params).get_data(as_text=True)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def test_filtro_escola(client):
    entrar_admin(client)
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    esperado = Aluno.query.filter_by(escola_id=e1.id).count()
    html = get(client, escola=e1.id, pagina=1)
    assert total(html) == esperado
    assert "Monteiro Lobato" not in "".join(re.findall(r"Matr\. \d+ · ([^<]+)<", html))


def test_filtro_ano(client):
    entrar_admin(client)
    esperado = Aluno.query.join(Turma).filter(Turma.ano == "9º Ano").count()
    assert total(get(client, ano="9º Ano")) == esperado


def test_filtro_turma(client):
    entrar_admin(client)
    t = Turma.query.join(Escola).filter(Escola.codigo == "EM-001", Turma.ano == "6º Ano",
                                        Turma.nome == "Turma A").one()
    html = get(client, turma=t.id)
    assert total(html) == Aluno.query.filter_by(turma_id=t.id).count()
    assert "Pedro da Silva" in nomes_na_tabela(html)


def test_filtro_turma_incompativel_com_escola_retorna_vazio(client):
    entrar_admin(client)
    e2 = Escola.query.filter_by(codigo="EM-002").one()
    t1 = Turma.query.join(Escola).filter(Escola.codigo == "EM-001").first()
    assert total(get(client, escola=e2.id, turma=t1.id)) == 0


def test_filtro_situacao(client):
    entrar_admin(client)
    p = Passeio.query.first()
    aut = Autorizacao.query.filter_by(passeio_id=p.id, situacao=Situacao.AUTORIZADO).count()
    nao = Autorizacao.query.filter_by(passeio_id=p.id, situacao=Situacao.NAO_AUTORIZADO).count()
    todos = PasseioAluno.query.filter_by(passeio_id=p.id).count()
    assert total(get(client, situacao="AUTORIZADO")) == aut
    assert total(get(client, situacao="NAO_AUTORIZADO")) == nao
    assert total(get(client, situacao="AGUARDANDO")) == todos - aut - nao
    assert total(get(client, situacao="CANCELADO")) == 0


def test_filtros_combinados_e_indicadores(client):
    entrar_admin(client)
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    html = get(client, escola=e1.id, ano="6º Ano", situacao="AGUARDANDO")
    esperado = sum(1 for a in Aluno.query.join(Turma).filter(Aluno.escola_id == e1.id, Turma.ano == "6º Ano")
                   if not Autorizacao.query.filter_by(aluno_id=a.id).first())
    assert total(html) == esperado
    # Indicadores refletem escola+ano (sem o filtro de situação)
    base = Aluno.query.join(Turma).filter(Aluno.escola_id == e1.id, Turma.ano == "6º Ano").count()
    assert re.search(r"Total de alunos</span><strong class=\"stat__value\">(\d+)<", html).group(1) == str(base)


def test_pesquisa_sem_acento_matricula_responsavel_protocolo(client):
    _, token = login(client)
    pid, alunos = meus(client, token)
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": alunos[0]["aluno"]["id"], "situacao": "AUTORIZADO"}],
        "declaracao_aceita": True}).get_json()
    entrar_admin(client)
    assert "Pedro da Silva" in nomes_na_tabela(get(client, q="PEDRO silva"))
    assert "Pedro da Silva" in nomes_na_tabela(get(client, q="jose da silva"))   # responsável sem acento
    pedro = Aluno.query.filter_by(nome="Pedro da Silva").one()
    assert nomes_na_tabela(get(client, q=pedro.matricula)) == ["Pedro da Silva"]
    assert total(get(client, q=r["protocolo"])) == 1
    assert total(get(client, q="nome-que-nao-existe")) == 0


def test_filtros_aplicados_na_exportacao(client):
    entrar_admin(client)
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    csv = client.get("/admin/exportar", query_string={"formato": "csv", "relatorio": "geral", "escola": e1.id})
    linhas = csv.get_data(as_text=True).strip().splitlines()
    assert len(linhas) - 1 == Aluno.query.filter_by(escola_id=e1.id).count()
    assert all("Monteiro Lobato" not in l for l in linhas[1:])


def test_opcoes_de_filtro_limitadas_ao_passeio_e_paginacao(client):
    entrar_admin(client)
    html = get(client)
    assert "js-f-turma" in html and 'data-escola=' in html
    assert "Página 1 de" in html
    html2 = get(client, pagina=2)
    assert set(nomes_na_tabela(html)).isdisjoint(nomes_na_tabela(html2))


def test_escopo_do_usuario_de_escola(client):
    entrar_admin(client, "escola.exemplo", "demo-escola-2026")
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    html = get(client)
    assert total(html) == Aluno.query.filter_by(escola_id=e1.id).count()
    # Tentar filtrar outra escola não vaza dados
    e2 = Escola.query.filter_by(codigo="EM-002").one()
    assert total(get(client, escola=e2.id)) == 0
    assert client.get("/admin/configuracoes").status_code == 403
    assert client.get("/admin/usuarios").status_code == 403


# ---------------------------------------------------------------------------
# Revogação pela escola / cancelamento pelo responsável / prazo
# ---------------------------------------------------------------------------
def _autorizar_pedro(client):
    _, token = login(client)
    pid, alunos = meus(client, token)
    pedro = next(a for a in alunos if a["aluno"]["nome"].startswith("Pedro"))["aluno"]["id"]
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": pedro, "situacao": "AUTORIZADO"}], "declaracao_aceita": True})
    assert r.status_code == 201
    return pid, pedro, token


def test_escola_revoga_autorizacao(client):
    _autorizar_pedro(client)
    token = entrar_admin(client, "escola.exemplo", "demo-escola-2026")
    aut = Autorizacao.query.join(Aluno).filter(Aluno.nome == "Pedro da Silva").one()
    r = client.post(f"/admin/autorizacoes/{aut.public_id}/cancelar",
                    data={"_csrf": token, "motivo": "Pedido presencial do responsável"})
    assert r.status_code == 302
    db.session.refresh(aut)
    assert aut.situacao == Situacao.CANCELADO
    _, token = login(client)
    _, alunos = meus(client, token)
    item = next(a for a in alunos if a["aluno"]["nome"].startswith("Pedro"))
    assert item["pode_responder"] and "revogada pela unidade escolar" in item["aviso"]


def test_responsavel_cancela_dentro_do_prazo(client):
    pid, pedro, token = _autorizar_pedro(client)
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": pedro, "situacao": "CANCELADO"}], "declaracao_aceita": True})
    assert r.status_code == 201
    v = client.get(f"/api/validar/{r.get_json()['codigo_validacao']}").get_json()
    assert v["situacao"] == "CANCELAMENTO REGISTRADO"


def test_prazo_em_horas_para_alterar(client):
    pid, pedro, token = _autorizar_pedro(client)
    p = Passeio.query.first()
    p.prazo_alteracao_horas = 2
    aut = Autorizacao.query.join(Aluno).filter(Aluno.public_id == pedro).one()
    aut.data_hora = utcnow() - timedelta(hours=3)
    db.session.commit()
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": pedro, "situacao": "NAO_AUTORIZADO"}], "declaracao_aceita": True})
    assert r.status_code == 409 and "prazo" in r.get_json()["erro"]
    _, alunos = meus(client, token)
    item = next(a for a in alunos if a["aluno"]["id"] == pedro)
    assert item["pode_alterar"] is False


def test_cancelar_sem_resposta_e_recusado(client):
    _, token = login(client)
    pid, alunos = meus(client, token)
    r = client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": token}, json={
        "autorizacoes": [{"aluno_id": alunos[0]["aluno"]["id"], "situacao": "CANCELADO"}],
        "declaracao_aceita": True})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Configurações, passeio e usuários
# ---------------------------------------------------------------------------
def _png():
    buf = io.BytesIO()
    Image.new("RGBA", (40, 30), (0, 122, 173, 255)).save(buf, "PNG")
    buf.seek(0)
    return buf


def test_configuracoes_e_upload(client):
    token = entrar_admin(client)
    r = client.post("/admin/configuracoes", content_type="multipart/form-data", data={
        "_csrf": token, "instituicao_nome": "Secretaria de Teste", "titulo_sistema": "Passeios",
        "subtitulo": "Subtítulo novo", "passeio_destaque": "", "brasao": (_png(), "b.png")})
    assert r.status_code == 302
    client.post("/admin/sair", data={"_csrf": token})
    html = client.get("/").get_data(as_text=True)
    assert "Secretaria de Teste" in html and "Subtítulo novo" in html
    m = re.search(r'src="(/midia/brasao-[0-9a-f]+\.png)"', html)
    assert m and client.get(m.group(1)).status_code == 200
    # Arquivo que não é imagem é recusado
    token = entrar_admin(client)
    r = client.post("/admin/configuracoes", content_type="multipart/form-data", data={
        "_csrf": token, "instituicao_nome": "X", "brasao": (io.BytesIO(b"<svg onload=alert(1)>"), "x.png")})
    assert r.status_code == 200 and "inválido" in r.get_data(as_text=True)


def test_editar_passeio_nome_textos_imagem_e_destaque(client):
    token = entrar_admin(client)
    p = Passeio.query.first()
    dados = {
        "_csrf": token, "nome": "Passeio ao Museu", "destino": "Museu Nacional", "local_saida": "Escola",
        "data": p.data.isoformat(), "hora_saida": "08:00", "hora_retorno": "12:00",
        "data_limite": p.data_limite.strftime("%Y-%m-%dT%H:%M"), "prazo_alteracao_horas": "24",
        "permite_alteracao": "1", "ativo": "1", "destaque": "1",
        "texto_termo": "Confirmo como responsável legal.", "texto_declaracao": "Nova declaração de teste.",
        "turmas": [str(t.id) for t in p.turmas], "imagem": (_png(), "museu.png"),
    }
    r = client.post(f"/admin/passeios/{p.public_id}/editar", data=dados, content_type="multipart/form-data")
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    db.session.refresh(p)
    assert p.nome == "Passeio ao Museu" and p.prazo_alteracao_horas == 24 and p.versao_texto == 2
    assert p.imagem and p.texto_termo == "Confirmo como responsável legal."
    client.post("/admin/sair", data={"_csrf": token})
    html = client.get("/").get_data(as_text=True)
    assert "Passeio ao Museu" in html and f"/midia/{p.imagem}" in html
    _, tk = login(client)
    html = client.get(f"/passeios/{p.public_id}").get_data(as_text=True)
    assert "Confirmo como responsável legal." in html


def test_gestao_de_usuarios(client):
    token = entrar_admin(client)
    e2 = Escola.query.filter_by(codigo="EM-002").one()
    r = client.post("/admin/usuarios", data={"_csrf": token, "nome": "Diretora ML", "login": "ml.direcao",
                                             "senha": "senha-forte-123", "escola_id": str(e2.id)})
    assert r.status_code == 302
    client.post("/admin/sair", data={"_csrf": token})
    entrar_admin(client, "ml.direcao", "senha-forte-123")
    assert total(get(client)) == Aluno.query.filter_by(escola_id=e2.id).count()


def test_galeria_de_ilustracoes_por_evento(client):
    from app.services.config_service import ILUSTRACOES
    token = entrar_admin(client)
    html = client.get("/admin/passeios/novo").get_data(as_text=True)
    for chave in ILUSTRACOES:
        assert f'value="{chave}"' in html
        assert client.get(f"/static/img/eventos/{chave}.svg").status_code == 200
    p = Passeio.query.first()
    dados = {
        "_csrf": token, "nome": p.nome, "destino": p.destino, "local_saida": p.local_saida,
        "data": p.data.isoformat(), "hora_saida": "13:00", "hora_retorno": "18:00",
        "data_limite": p.data_limite.strftime("%Y-%m-%dT%H:%M"), "permite_alteracao": "1", "ativo": "1",
        "destaque": "1", "ilustracao": "teatro", "texto_termo": p.texto_termo,
        "texto_declaracao": p.texto_declaracao, "turmas": [str(t.id) for t in p.turmas],
    }
    assert client.post(f"/admin/passeios/{p.public_id}/editar", data=dados).status_code == 302
    db.session.refresh(p)
    assert p.ilustracao == "teatro"
    client.post("/admin/sair", data={"_csrf": token})
    assert "/static/img/eventos/teatro.svg" in client.get("/").get_data(as_text=True)
    # Valor fora do catálogo é ignorado
    token = entrar_admin(client)
    dados.update(_csrf=token, ilustracao="../../etc")
    client.post(f"/admin/passeios/{p.public_id}/editar", data=dados)
    db.session.refresh(p)
    assert p.ilustracao == "teatro"


def test_responsavel_com_filhos_em_dois_passeios(client):
    login(client, "529.982.247-25")
    html = client.get("/painel").get_data(as_text=True)
    assert "Passeio ao Cinema" in html and "Visita ao Museu de Ciências" in html
    assert "/static/img/eventos/ciencia.svg" in html


def test_revogacao_em_lote_selecionados_e_todos_do_filtro(client):
    from app.models import AutorizacaoHistorico
    token = entrar_admin(client)
    p = Passeio.query.first()
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    auts = (Autorizacao.query.join(Aluno).filter(Autorizacao.passeio_id == p.id, Aluno.escola_id == e1.id,
                                                 Autorizacao.situacao == Situacao.AUTORIZADO).limit(3).all())
    ids = [a.public_id for a in auts]
    # Sem motivo: nada muda
    client.post("/admin/autorizacoes/revogar", data={"_csrf": token, "passeio": p.public_id, "aut": ids, "motivo": ""})
    assert all(db.session.get(Autorizacao, a.id).situacao == Situacao.AUTORIZADO for a in auts)
    # Selecionados, motivo único
    r = client.post("/admin/autorizacoes/revogar", data={
        "_csrf": token, "passeio": p.public_id, "aut": ids, "motivo": "Chuva forte prevista",
        "voltar": "/admin/?situacao=AUTORIZADO"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/?situacao=AUTORIZADO")
    for a in auts:
        db.session.refresh(a)
        assert a.situacao == Situacao.CANCELADO
        assert AutorizacaoHistorico.query.filter_by(autorizacao_id=a.id).order_by(
            AutorizacaoHistorico.id.desc()).first().motivo == "Chuva forte prevista"
    # Todos do filtro (escola 2, autorizados)
    e2 = Escola.query.filter_by(codigo="EM-002").one()
    antes = (Autorizacao.query.join(Aluno).filter(Autorizacao.passeio_id == p.id, Aluno.escola_id == e2.id,
                                                  Autorizacao.situacao == Situacao.AUTORIZADO).count())
    assert antes > 0
    client.post("/admin/autorizacoes/revogar", data={
        "_csrf": token, "passeio": p.public_id, "todos_filtrados": "1", "f_escola": str(e2.id),
        "f_situacao": "AUTORIZADO", "motivo": "Passeio cancelado para esta unidade"})
    depois = (Autorizacao.query.join(Aluno).filter(Autorizacao.passeio_id == p.id, Aluno.escola_id == e2.id,
                                                   Autorizacao.situacao == Situacao.AUTORIZADO).count())
    assert depois == 0
    # Escola 1 não foi afetada pelo lote da escola 2
    assert Autorizacao.query.join(Aluno).filter(Autorizacao.passeio_id == p.id, Aluno.escola_id == e1.id,
                                                Autorizacao.situacao == Situacao.AUTORIZADO).count() > 0


def test_revogacao_em_lote_respeita_escopo_da_escola(client):
    p = Passeio.query.first()
    e2 = Escola.query.filter_by(codigo="EM-002").one()
    alheia = (Autorizacao.query.join(Aluno).filter(Autorizacao.passeio_id == p.id, Aluno.escola_id == e2.id,
                                                   Autorizacao.situacao == Situacao.AUTORIZADO).first())
    token = entrar_admin(client, "escola.exemplo", "demo-escola-2026")
    client.post("/admin/autorizacoes/revogar", data={
        "_csrf": token, "passeio": p.public_id, "aut": [alheia.public_id], "motivo": "Tentativa indevida"})
    db.session.refresh(alheia)
    assert alheia.situacao == Situacao.AUTORIZADO
    # "Todos do filtro" de um usuário de escola só alcança a própria escola
    client.post("/admin/autorizacoes/revogar", data={
        "_csrf": token, "passeio": p.public_id, "todos_filtrados": "1", "f_situacao": "AUTORIZADO",
        "motivo": "Revogação geral da unidade"})
    db.session.refresh(alheia)
    assert alheia.situacao == Situacao.AUTORIZADO
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    assert Autorizacao.query.join(Aluno).filter(Autorizacao.passeio_id == p.id, Aluno.escola_id == e1.id,
                                                Autorizacao.situacao == Situacao.AUTORIZADO).count() == 0

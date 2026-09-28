"""Cadastro de responsáveis (CPF) e alunos pelo painel."""
import re

from app.extensions import db
from app.models import (Aluno, AdminUsuario, Escola, Passeio, PasseioAluno, Responsavel, ResponsavelAluno,
                        Turma)
from app.security import hash_cpf
from tests.test_admin_filtros import entrar_admin
from tests.test_fluxo import app, client, csrf, login, meus  # noqa: F401  (fixtures)

CPF_NOVO = "111.444.777-35"   # CPF válido fictício


def _novo_resp(client, token, cpf=CPF_NOVO, nome="Carla Mendes Teste"):
    return client.post("/admin/responsaveis/novo", data={"_csrf": token, "nome": nome, "cpf": cpf,
                                                         "data_nascimento": "1985-03-10", "ativo": "1"})


def test_cadastrar_responsavel_com_filho_novo_e_acesso(client):
    token = entrar_admin(client)
    r = _novo_resp(client, token)
    assert r.status_code == 302
    resp = Responsavel.query.filter_by(cpf_hash=hash_cpf("11144477735")).one()
    assert resp.cpf_final == "35" and resp.data_nascimento_hash
    turma = Turma.query.join(Escola).filter(Escola.codigo == "EM-001", Turma.ano == "7º Ano").first()
    r = client.post(f"/admin/responsaveis/{resp.public_id}/filhos", data={
        "_csrf": token, "acao": "novo_aluno", "aluno_nome": "Davi Mendes", "matricula": "9990001",
        "sexo": "M", "turma_id": str(turma.id), "tipo_vinculo": "Mãe", "responsavel_legal": "1"})
    assert r.status_code == 302
    davi = Aluno.query.filter_by(matricula="9990001").one()
    # Entrou automaticamente no passeio da turma
    p = Passeio.query.filter(Passeio.turmas.any(Turma.id == turma.id)).first()
    assert PasseioAluno.query.filter_by(passeio_id=p.id, aluno_id=davi.id).first()
    # E o responsável já consegue acessar e ver o filho
    client.post("/admin/sair", data={"_csrf": token})
    _, tk = login(client, CPF_NOVO)
    pid, alunos = meus(client, tk)
    assert [a["aluno"]["nome"] for a in alunos] == ["Davi Mendes"]


def test_validacoes_de_cpf_e_matricula(client):
    token = entrar_admin(client)
    assert "CPF inválido" in _novo_resp(client, token, cpf="123.456.789-00").get_data(as_text=True)
    assert "já está cadastrado" in _novo_resp(client, token, cpf="529.982.247-25").get_data(as_text=True)
    _novo_resp(client, token)
    resp = Responsavel.query.filter_by(cpf_hash=hash_cpf("11144477735")).one()
    pedro = Aluno.query.filter_by(nome="Pedro da Silva").one()
    turma = Turma.query.first()
    client.post(f"/admin/responsaveis/{resp.public_id}/filhos", data={
        "_csrf": token, "acao": "novo_aluno", "aluno_nome": "Duplicado", "matricula": pedro.matricula,
        "turma_id": str(turma.id)})
    assert Aluno.query.filter_by(nome="Duplicado").first() is None


def test_vincular_existente_editar_vinculo_e_desvincular(client):
    token = entrar_admin(client)
    _novo_resp(client, token)
    resp = Responsavel.query.filter_by(cpf_hash=hash_cpf("11144477735")).one()
    pedro = Aluno.query.filter_by(nome="Pedro da Silva").one()
    client.post(f"/admin/responsaveis/{resp.public_id}/filhos", data={
        "_csrf": token, "acao": "vincular", "aluno_ref": f"{pedro.matricula} — Pedro da Silva",
        "tipo_vinculo": "Avó"})
    v = ResponsavelAluno.query.filter_by(responsavel_id=resp.id, aluno_id=pedro.id).one()
    assert v.tipo_vinculo == "Avó" and v.responsavel_legal is False   # "pode autorizar" desmarcado
    client.post(f"/admin/responsaveis/{resp.public_id}/vinculos/{v.id}", data={
        "_csrf": token, "tipo_vinculo": "Tutor(a)", "responsavel_legal": "1"})
    db.session.refresh(v)
    assert v.tipo_vinculo == "Tutor(a)" and v.responsavel_legal is True
    client.post(f"/admin/responsaveis/{resp.public_id}/filhos", data={
        "_csrf": token, "acao": "desvincular", "vinculo_id": str(v.id)})
    assert ResponsavelAluno.query.filter_by(responsavel_id=resp.id).count() == 0


def test_editar_responsavel_e_alterar_cpf(client):
    token = entrar_admin(client)
    jose = Responsavel.query.filter_by(nome="José da Silva").one()
    r = client.post(f"/admin/responsaveis/{jose.public_id}", data={
        "_csrf": token, "nome": "José da Silva Santos", "cpf": CPF_NOVO, "email": "jose@exemplo.com", "ativo": "1"})
    assert r.status_code == 302
    db.session.refresh(jose)
    assert jose.nome == "José da Silva Santos" and jose.cpf_final == "35" and jose.email == "jose@exemplo.com"
    html = client.get(f"/admin/responsaveis/{jose.public_id}").get_data(as_text=True)
    assert "11144477735" not in html and "111.444.777-35" not in html   # CPF completo nunca exibido


def test_excluir_sem_historico_apaga_e_com_historico_desativa(client):
    token = entrar_admin(client)
    _novo_resp(client, token)
    novo = Responsavel.query.filter_by(cpf_hash=hash_cpf("11144477735")).one()
    client.post(f"/admin/responsaveis/{novo.public_id}/excluir", data={"_csrf": token})
    assert Responsavel.query.filter_by(cpf_hash=hash_cpf("11144477735")).first() is None
    # José autoriza e depois é "excluído": vira inativo, sem vínculos, histórico preservado
    client.post("/admin/sair", data={"_csrf": token})
    _, tk = login(client)
    pid, alunos = meus(client, tk)
    client.post(f"/api/passeios/{pid}/autorizacoes", headers={"X-CSRF-Token": tk}, json={
        "autorizacoes": [{"aluno_id": alunos[0]["aluno"]["id"], "situacao": "AUTORIZADO"}], "declaracao_aceita": True})
    token = entrar_admin(client)
    jose = Responsavel.query.filter_by(nome="José da Silva").one()
    client.post(f"/admin/responsaveis/{jose.public_id}/excluir", data={"_csrf": token})
    db.session.refresh(jose)
    assert jose.ativo is False and ResponsavelAluno.query.filter_by(responsavel_id=jose.id).count() == 0


def test_pesquisa_por_cpf_nome_e_aluno(client):
    token = entrar_admin(client)
    html = client.get("/admin/responsaveis", query_string={"q": "529.982.247-25"}).get_data(as_text=True)
    assert "Ana Paula Souza" in html and "José da Silva" not in html
    html = client.get("/admin/responsaveis", query_string={"q": "maria da silva"}).get_data(as_text=True)
    assert "José da Silva" in html   # busca pelo nome do filho


def test_escopo_escola_e_permissao(client):
    token = entrar_admin(client, "escola.exemplo", "senha-teste-escola")   # Administrador da EM-001
    ana = Responsavel.query.filter_by(nome="Ana Paula Souza").one()      # filhos em EM-001 e EM-002
    assert client.get(f"/admin/responsaveis/{ana.public_id}").status_code == 200
    e2_aluno = Aluno.query.join(Escola).filter(Escola.codigo == "EM-002").first()
    _novo_resp(client, token)
    resp = Responsavel.query.filter_by(cpf_hash=hash_cpf("11144477735")).one()
    client.post(f"/admin/responsaveis/{resp.public_id}/filhos", data={
        "_csrf": token, "acao": "vincular", "aluno_ref": e2_aluno.matricula, "responsavel_legal": "1"})
    assert ResponsavelAluno.query.filter_by(responsavel_id=resp.id).count() == 0   # aluno fora do escopo
    t2 = Turma.query.join(Escola).filter(Escola.codigo == "EM-002").first()
    client.post(f"/admin/responsaveis/{resp.public_id}/filhos", data={
        "_csrf": token, "acao": "novo_aluno", "aluno_nome": "Fora", "matricula": "8880001", "turma_id": str(t2.id)})
    assert Aluno.query.filter_by(matricula="8880001").first() is None
    # Não exclui responsável com filho em outra escola
    client.post(f"/admin/responsaveis/{ana.public_id}/excluir", data={"_csrf": token})
    assert db.session.get(Responsavel, ana.id).ativo is True
    # Usuário comum sem a permissão não acessa
    adm = AdminUsuario.query.filter_by(login="escola.exemplo").one()
    adm.perfil = "COMUM"
    db.session.commit()
    assert client.get("/admin/responsaveis").status_code == 403


def test_editar_aluno_muda_turma(client):
    token = entrar_admin(client)
    pedro = Aluno.query.filter_by(nome="Pedro da Silva").one()
    nova = Turma.query.filter(Turma.escola_id == pedro.escola_id, Turma.id != pedro.turma_id).first()
    r = client.post(f"/admin/alunos/{pedro.public_id}/editar", data={
        "_csrf": token, "aluno_nome": "Pedro da Silva", "matricula": pedro.matricula, "sexo": "M",
        "turma_id": str(nova.id), "aluno_ativo": "1"})
    assert r.status_code == 302
    db.session.refresh(pedro)
    assert pedro.turma_id == nova.id

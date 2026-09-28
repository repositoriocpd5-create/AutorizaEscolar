"""Cadastro de escolas/turmas e importação do JSON da rede."""
import io
import json

from app.extensions import db
from app.models import AdminUsuario, Escola, Turma
from app.services import escola_service as esc
from tests.test_admin_filtros import entrar_admin
from tests.test_fluxo import app, client, csrf  # noqa: F401  (fixtures)

AMOSTRA = [
    {"name": "CEMAEE\n Centro Municipal de Atendimento", "email": "cemaee@edu.itaguai.rj.gov.br", "inep": 33158711,
     "street": "Rua José Bonifácio", "number": "s/n", "complement": "s/n", "area": "Centro", "city": "Itaguaí",
     "state": "RJ", "cep": "23815-650", "room_count": 6, "director": "Ninah", "maps_link": "https://maps.app.goo.gl/x"},
    {"name": "Colégio M. Senador Teotônio Vilella", "email": "cm.x@edu.itaguai.rj.gov.br", "inep": 33044872, "number": 22},
    {"name": "CIEP 497", "email": "ciep497@edu.itaguai.rj.gov.br emamericoamorim@gmail.com", "inep": 33044872},
    {"name": "E. M. Sylvia", "email": "@edu.itaguai.rj.gov.br", "inep": 33162468, "complement": ", Lagoa Nova, Gleba B"},
]


def test_normalizacao_e_importacao_idempotente(app):
    rel = esc.importar(AMOSTRA)
    db.session.commit()
    assert rel.criadas == 4 and len(rel.avisos) == 2
    cemaee = Escola.query.filter_by(inep="33158711").one()
    assert cemaee.nome == "CEMAEE Centro Municipal de Atendimento"   # quebra de linha removida
    assert cemaee.complemento is None and cemaee.numero == "s/n" and cemaee.cep == "23815-650"
    assert cemaee.codigo == "33158711"
    ciep = Escola.query.filter_by(nome="CIEP 497").one()
    assert ciep.inep is None and ciep.email == "ciep497@edu.itaguai.rj.gov.br"   # 1º e-mail válido
    sylvia = Escola.query.filter_by(inep="33162468").one()
    assert sylvia.email is None and sylvia.complemento == "Lagoa Nova, Gleba B"
    # Reimportar não duplica
    rel2 = esc.importar(AMOSTRA)
    db.session.commit()
    assert rel2.criadas == 0 and rel2.atualizadas == 4
    assert Escola.query.filter(Escola.nome.like("CIEP 497%")).count() == 1


def test_sql_supabase(app):
    sql = esc.sql_supabase(AMOSTRA)
    assert "ON CONFLICT (inep) DO UPDATE" in sql and "ON CONFLICT (codigo) DO UPDATE" in sql
    assert sql.count("'33044872'") == 2          # codigo + inep do primeiro; o repetido vai sem INEP


def test_tela_importar_json(client):
    token = entrar_admin(client)
    arquivo = (io.BytesIO(json.dumps(AMOSTRA).encode()), "schools_data.json")
    r = client.post("/admin/escolas/importar", data={"_csrf": token, "arquivo": arquivo},
                    content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Importação concluída" in html and "INEP 33044872 repetido" in html
    r = client.post("/admin/escolas/importar", data={"_csrf": token, "arquivo": (io.BytesIO(b"{x"), "a.json")},
                    content_type="multipart/form-data")
    assert "Arquivo JSON inválido" in r.get_data(as_text=True)


def test_crud_escola_e_turmas(client):
    token = entrar_admin(client)
    r = client.post("/admin/escolas/nova", data={"_csrf": token, "nome": "E. M. Nova Esperança", "inep": "33999999",
                                                 "cep": "23800000", "uf": "rj", "ativo": "1"})
    assert r.status_code == 302
    e = Escola.query.filter_by(inep="33999999").one()
    assert e.cep == "23800-000" and e.uf == "RJ"
    assert "já pertence" in client.post("/admin/escolas/nova", data={
        "_csrf": token, "nome": "Outra", "inep": "33999999"}).get_data(as_text=True)
    client.post(f"/admin/escolas/{e.id}/turmas", data={"_csrf": token, "anos": ["1º Ano", "2º Ano"], "letras": "A, B"})
    assert Turma.query.filter_by(escola_id=e.id).count() == 4
    client.post(f"/admin/escolas/{e.id}/turmas", data={"_csrf": token, "anos": ["1º Ano"], "letras": "A"})
    assert Turma.query.filter_by(escola_id=e.id).count() == 4        # não duplica
    t = Turma.query.filter_by(escola_id=e.id).first()
    client.post(f"/admin/escolas/{e.id}/turmas", data={"_csrf": token, "acao": "excluir", "turma_id": t.id})
    assert Turma.query.filter_by(escola_id=e.id).count() == 3
    client.post(f"/admin/escolas/{e.id}/excluir", data={"_csrf": token})
    assert db.session.get(Escola, e.id) is None                     # sem alunos: excluída


def test_escola_com_alunos_e_desativada(client):
    token = entrar_admin(client)
    e1 = Escola.query.filter_by(codigo="EM-001").one()
    client.post(f"/admin/escolas/{e1.id}/excluir", data={"_csrf": token})
    db.session.refresh(e1)
    assert e1.ativo is False
    t = Turma.query.filter_by(escola_id=e1.id).first()
    r = client.post(f"/admin/escolas/{e1.id}/turmas", data={"_csrf": token, "acao": "excluir", "turma_id": t.id},
                    follow_redirects=True)
    assert db.session.get(Turma, t.id) is not None   # turma com alunos/passeio não é excluída


def test_permissao_escolas(client):
    entrar_admin(client, "escola.exemplo", "senha-teste-escola")      # admin de escola: não gerencia escolas
    assert client.get("/admin/escolas").status_code == 403
    assert "Escolas</a>" not in client.get("/admin/").get_data(as_text=True)

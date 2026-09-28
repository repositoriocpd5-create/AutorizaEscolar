"""Importação de alunos/responsáveis — somente dados FICTÍCIOS."""
import re

from app.extensions import db
from app.models import Aluno, Escola, Responsavel, ResponsavelAluno, Turma
from app.security import hash_cpf
from app.services import importacao_alunos as imp
from tests.test_fluxo import app, client, csrf  # noqa: F401  (fixtures)

# CPFs fictícios com dígitos verificadores válidos
MAE = "98765432100"
PAI = "11144477735"
FICTICIOS = [
    {"aluno_id": 9001, "nome_aluno": "JOÃO DA SILVA TESTE", "data_nascimento": "2018-03-01", "cpf_aluno": "39053344705",
     "turma": "2° Ano (Ensino Fundamental - Anos Iniciais) A", "ano_letivo": 2026, "status_vinculo": "ativo",
     "nome_pai": "PEDRO DOS SANTOS TESTE", "cpf_pai": PAI, "nome_mae": "MARIA DE SOUZA TESTE", "cpf_mae": MAE},
    {"aluno_id": 9002, "nome_aluno": "ANA DA SILVA TESTE", "data_nascimento": "2020-07-10", "cpf_aluno": "NULL",
     "turma": "Pré I (Educação Infantil) B", "ano_letivo": 2026, "status_vinculo": "ativo",
     "nome_pai": "PEDRO DOS SANTOS TESTE", "cpf_pai": "NULL", "nome_mae": "MARIA DE SOUZA TESTE", "cpf_mae": MAE},
    {"aluno_id": 9003, "nome_aluno": "CARLOS ANTIGO", "data_nascimento": "2015-01-01", "cpf_aluno": "123",
     "turma": "5° Ano (Ensino Fundamental - Anos Iniciais) C", "ano_letivo": 2025, "status_vinculo": "desligado",
     "nome_pai": "JOSÉ SEM CPF", "cpf_pai": "NULL", "nome_mae": "LUCIA SEM CPF", "cpf_mae": "123456789"},
]


def test_leitura_normaliza_e_valida():
    lt = imp.ler(FICTICIOS)
    a, b, c = lt.linhas
    assert a.nome == "João da Silva Teste" and a.mae == "Maria de Souza Teste" and a.pai == "Pedro dos Santos Teste"
    assert (a.ano, a.turma, a.segmento) == ("2º Ano", "Turma A", "Ensino Fundamental - Anos Iniciais")
    assert (b.ano, b.turma, b.segmento) == ("Pré I", "Turma B", "Educação Infantil")
    assert a.ativo and b.ativo and not c.ativo                      # 2025/desligado → inativo
    assert c.cpf_aluno is None and c.cpf_mae is None                # CPFs inválidos descartados
    assert sum("inválido" in x for x in lt.avisos) == 2


def test_sql_gerado_nao_contem_pepper_e_tem_protecoes():
    sql = imp.gerar_sql(imp.ler(FICTICIOS))
    linhas = sql.splitlines()
    assert "'00000000'" in linhas[3] and "COLE-AQUI-O-CPF_PEPPER" in linhas[4]
    assert sql.count("DO $importacao$") == 1 and "CREATE TEMP TABLE _cfg" not in sql   # um único bloco
    assert "extensions.hmac(" in sql and "ON CONFLICT (matricula)" in sql
    assert "parece um CNPJ/CPF" in sql and sql.count("INSERT INTO responsavel ") == 2
    pronto = imp.gerar_sql(imp.ler(FICTICIOS), inep="33000009", pepper="chave-secreta-de-teste-123")
    assert "'33000009'" in pronto.splitlines()[3] and "ARQUIVO PRONTO" in pronto.splitlines()[0]


def test_importacao_local_e_idempotente(client, app):
    esc = Escola(nome="Escola Importação", codigo="33000009", inep="33000009", ativo=True)
    db.session.add(esc)
    db.session.commit()
    with app.test_request_context():
        imp.importar_local(imp.ler(FICTICIOS), "33000009")
        db.session.commit()
        imp.importar_local(imp.ler(FICTICIOS), "33000009")   # segunda vez: não duplica
        db.session.commit()
    assert Aluno.query.filter(Aluno.id_externo.in_(["9001", "9002", "9003"])).count() == 3
    assert Turma.query.filter_by(escola_id=esc.id).count() == 3
    mae = Responsavel.query.filter_by(cpf_hash=hash_cpf(MAE)).one()
    assert len(mae.vinculos) == 2                                   # irmãos no mesmo cadastro
    assert Responsavel.query.filter_by(id_externo="9002-PAI").one().cpf_hash is None
    assert Responsavel.query.filter_by(id_externo="9003-MAE").one().cpf_mascarado == "CPF não informado"
    assert ResponsavelAluno.query.join(Aluno).filter(Aluno.id_externo == "9001").count() == 2
    # A mãe importada entra e vê só os filhos ATIVOS
    tok = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/").get_data(as_text=True)).group(1)
    assert client.post("/api/auth/responsavel", json={"cpf": MAE}, headers={"X-CSRF-Token": tok}).status_code == 200
    nomes = {a["nome"] for a in client.get("/api/responsavel/me/alunos").get_json()["alunos"]}
    assert nomes == {"João da Silva Teste", "Ana da Silva Teste"}

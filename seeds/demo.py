"""Dados FICTÍCIOS de demonstração.

Executado apenas via ``flask seed-demo`` com DEMO_MODE=true. Para usar dados
reais, importe escolas, turmas, alunos, responsáveis e vínculos a partir do
sistema de gestão escolar e NÃO execute este seed.
"""
import os
import random
from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.formatacao import agora_local
from app.models import (AdminUsuario, Aluno, Autorizacao, AutorizacaoHistorico, Escola, Passeio,
                        Responsavel, ResponsavelAluno, Situacao, Turma, utcnow)
from app.security import hash_cpf, hash_segredo
from app.services.passeio_service import sincronizar_participantes

NOMES_M = ["Pedro", "Lucas", "Gabriel", "Rafael", "Miguel", "Arthur", "Davi", "Bernardo", "Heitor", "Enzo",
           "Samuel", "Joaquim", "Theo", "Lorenzo", "Benjamin", "Matheus", "Isaac", "Nicolas", "Caio", "Vitor"]
NOMES_F = ["Maria", "Alice", "Laura", "Helena", "Valentina", "Sophia", "Isabela", "Manuela", "Júlia", "Luiza",
           "Heloísa", "Lorena", "Lívia", "Beatriz", "Cecília", "Clara", "Giovanna", "Mariana", "Yasmin", "Lara"]
SOBRENOMES = ["Oliveira", "Santos", "Souza", "Lima", "Pereira", "Ferreira", "Costa", "Rodrigues", "Almeida",
              "Nascimento", "Carvalho", "Araújo", "Ribeiro", "Gomes", "Martins", "Rocha", "Barbosa", "Mendes"]
ADULTOS_M = ["Carlos", "Paulo", "Marcos", "André", "Ricardo", "Fernando", "Roberto", "Eduardo", "Luiz", "Sérgio"]
ADULTOS_F = ["Ana", "Patrícia", "Fernanda", "Juliana", "Adriana", "Camila", "Luciana", "Renata", "Cláudia", "Sandra"]


def _cpf_ficticio(rng: random.Random) -> str:
    """Gera CPF com dígitos verificadores válidos (fictício)."""
    base = [rng.randint(0, 9) for _ in range(9)]
    for tamanho in (9, 10):
        soma = sum(base[i] * (tamanho + 1 - i) for i in range(tamanho))
        base.append((soma * 10 % 11) % 10)
    return "".join(map(str, base))


def popular(seed: int = 2026) -> None:
    if Responsavel.query.first():
        print("Banco já possui dados; use --reset para recriar.")
        return
    rng = random.Random(seed)

    # Escolas e turmas
    e1 = Escola(nome="Escola Municipal Exemplo", codigo="EM-001")
    e2 = Escola(nome="Escola Municipal Monteiro Lobato", codigo="EM-002")
    db.session.add_all([e1, e2])
    db.session.flush()
    turmas = {}
    for esc in (e1, e2):
        for ano in ("6º Ano", "7º Ano", "8º Ano", "9º Ano"):
            for nome in ("Turma A", "Turma B"):
                t = Turma(nome=nome, ano=ano, escola_id=esc.id)
                db.session.add(t)
                turmas[(esc.codigo, ano, nome)] = t
    db.session.flush()

    matricula = [2026000]

    def novo_aluno(nome, sexo, turma):
        matricula[0] += 1
        a = Aluno(matricula=str(matricula[0]), nome=nome, sexo=sexo, escola_id=turma.escola_id,
                  turma_id=turma.id, data_nascimento=date(2010 + rng.randint(0, 4), rng.randint(1, 12), rng.randint(1, 28)))
        db.session.add(a)
        return a

    def novo_resp(nome, cpf, nascimento=None):
        r = Responsavel(nome=nome, cpf_hash=hash_cpf(cpf), cpf_final=cpf[-2:],
                        data_nascimento_hash=hash_segredo(nascimento) if nascimento else None)
        db.session.add(r)
        return r

    # --- Família principal da demonstração (conforme especificação) ---------
    jose = novo_resp("José da Silva", "00000000000", "1980-05-20")
    pedro = novo_aluno("Pedro da Silva", "M", turmas[("EM-001", "6º Ano", "Turma A")])
    maria = novo_aluno("Maria da Silva", "F", turmas[("EM-001", "9º Ano", "Turma B")])
    db.session.flush()
    for a in (pedro, maria):
        db.session.add(ResponsavelAluno(responsavel_id=jose.id, aluno_id=a.id, tipo_vinculo="Pai"))

    # Segunda família (CPF válido) com três filhos — demonstra 3+ cards.
    ana = novo_resp("Ana Paula Souza", "52998224725", "1985-09-12")
    filhos_ana = [novo_aluno("Lucas Souza", "M", turmas[("EM-001", "7º Ano", "Turma A")]),
                  novo_aluno("Beatriz Souza", "F", turmas[("EM-002", "8º Ano", "Turma B")]),
                  novo_aluno("Clara Souza", "F", turmas[("EM-002", "6º Ano", "Turma A")])]
    db.session.flush()
    for a in filhos_ana:
        db.session.add(ResponsavelAluno(responsavel_id=ana.id, aluno_id=a.id, tipo_vinculo="Mãe"))

    # Demais alunos fictícios para o painel administrativo (~150 no total).
    lista_turmas = list(turmas.values())
    extras = []
    while len(extras) < 145:
        sexo = rng.choice("MF")
        sobrenome = rng.choice(SOBRENOMES)
        nome = f"{rng.choice(NOMES_M if sexo == 'M' else NOMES_F)} {rng.choice(SOBRENOMES)} {sobrenome}"
        aluno = novo_aluno(nome, sexo, rng.choice(lista_turmas))
        resp_sexo = rng.choice("MF")
        resp = novo_resp(f"{rng.choice(ADULTOS_M if resp_sexo == 'M' else ADULTOS_F)} {sobrenome}",
                         _cpf_ficticio(rng))
        db.session.flush()
        db.session.add(ResponsavelAluno(responsavel_id=resp.id, aluno_id=aluno.id,
                                        tipo_vinculo="Pai" if resp_sexo == "M" else "Mãe"))
        extras.append((aluno, resp))

    # --- Passeio -----------------------------------------------------------
    # A especificação cita 15/04/2026; para a demonstração funcionar a data
    # precisa estar no futuro. Defina DEMO_PASSEIO_DATA=AAAA-MM-DD para fixar.
    data_env = os.environ.get("DEMO_PASSEIO_DATA")
    data_passeio = (datetime.strptime(data_env, "%Y-%m-%d").date() if data_env
                    else agora_local().date() + timedelta(days=21))
    passeio = Passeio(
        nome="Passeio ao Cinema",
        descricao="Sessão de cinema com filme de classificação livre, como atividade cultural do bimestre.",
        destino="Cinema Shopping Cidade", data=data_passeio, hora_saida=time(13, 0), hora_retorno=time(18, 0),
        local_saida="Unidade Escolar", transporte="Transporte escolar disponibilizado pela rede",
        orientacoes="Enviar lanche leve e garrafa de água. Usar uniforme escolar. "
                    "Chegar à unidade escolar até 12h40.",
        data_limite=datetime.combine(data_passeio - timedelta(days=3), time(23, 59)),
        permite_alteracao=True, ativo=True, prazo_alteracao_horas=48, ilustracao="cinema",
    )
    passeio.turmas = lista_turmas
    db.session.add(passeio)
    db.session.flush()
    sincronizar_participantes(passeio)
    db.session.flush()

    # Segundo evento (somente Escola Monteiro Lobato) para demonstrar vários passeios/ilustrações.
    museu = Passeio(
        nome="Visita ao Museu de Ciências",
        descricao="Exposição interativa sobre o sistema solar e sessão no planetário.",
        destino="Museu de Ciências da Cidade", data=data_passeio - timedelta(days=7),
        hora_saida=time(8, 0), hora_retorno=time(12, 30), local_saida="Unidade Escolar",
        transporte="Transporte escolar disponibilizado pela rede",
        orientacoes="Levar caderno e lápis. Usar uniforme e tênis.",
        data_limite=datetime.combine(data_passeio - timedelta(days=9), time(23, 59)),
        permite_alteracao=True, ativo=True, prazo_alteracao_horas=24, ilustracao="ciencia",
    )
    museu.turmas = [t for t in lista_turmas if t.escola_id == e2.id]
    db.session.add(museu)
    db.session.flush()
    sincronizar_participantes(museu)
    db.session.flush()

    # Respostas fictícias (sem PDF) para compor o painel: ~75% autorizados.
    agora = utcnow()
    for aluno, resp in extras:
        sorte = rng.random()
        if sorte < 0.78:
            situacao = Situacao.AUTORIZADO
        elif sorte < 0.84:
            situacao = Situacao.NAO_AUTORIZADO
        else:
            continue
        quando = agora - timedelta(hours=rng.randint(1, 240), minutes=rng.randint(0, 59))
        aut = Autorizacao(passeio_id=passeio.id, aluno_id=aluno.id, responsavel_id=resp.id, situacao=situacao,
                          data_hora=quando, versao_texto=1, origem="SEED_DEMO")
        db.session.add(aut)
        db.session.flush()
        db.session.add(AutorizacaoHistorico(autorizacao_id=aut.id, situacao_nova=situacao, data_hora=quando,
                                            responsavel_id=resp.id, motivo="Dado fictício de demonstração"))

    # --- Administradores de demonstração -------------------------------
    # Criados SOMENTE se DEMO_ADMIN_SENHA / DEMO_ESCOLA_SENHA estiverem definidas
    # (ambiente local/testes). Com o Supabase, o acesso é pelo Authentication.
    from flask import current_app
    if current_app.config.get("DEMO_ADMIN_SENHA"):
        adm = AdminUsuario(nome="Administrador (demo)", login=os.environ.get("DEMO_ADMIN_LOGIN", "admin"))
        adm.definir_senha(current_app.config["DEMO_ADMIN_SENHA"])
        db.session.add(adm)
    if current_app.config.get("DEMO_ESCOLA_SENHA"):
        adm_escola = AdminUsuario(nome="Secretaria da EM Exemplo (demo)", escola_id=e1.id,
                                  login=os.environ.get("DEMO_ESCOLA_LOGIN", "escola.exemplo"))
        adm_escola.definir_senha(current_app.config["DEMO_ESCOLA_SENHA"])
        db.session.add(adm_escola)
    db.session.commit()

"""Importação de alunos e responsáveis (pai/mãe) do sistema de gestão escolar.

Formato de entrada (JSON exportado do banco da rede), um registro por aluno:
  aluno_id, nome_aluno, data_nascimento, cpf_aluno, turma, ano_letivo,
  status_vinculo, nome_pai, cpf_pai, nome_mae, cpf_mae

Regras:
- CPFs são validados (dígito verificador); inválidos são descartados com aviso.
- CPF nunca é gravado em claro: somente HMAC-SHA256(CPF_PEPPER) + 2 dígitos finais.
- Responsáveis COM CPF são únicos pelo CPF (irmãos compartilham o mesmo cadastro).
- Responsáveis SEM CPF são cadastrados por aluno (id_externo "<aluno>-MAE"/"-PAI"),
  sem acesso ao sistema até alguém informar o CPF no painel.
- Aluno ativo = status "ativo" no ano letivo mais recente do arquivo.
- Tudo é idempotente: reimportar atualiza, não duplica.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date

from ..security import cpf_valido, normalizar_cpf

PARTICULAS = {"da", "de", "do", "das", "dos", "e", "d'"}
RE_TURMA = re.compile(r"^(?P<ano>.+?)\s*(?:\((?P<seg>[^)]*)\))?\s*(?P<letra>\b[A-Z]\b)?\s*$")


def nome_proprio(nome: str | None) -> str | None:
    """'MARIA DA SILVA' → 'Maria da Silva'."""
    if not nome or not str(nome).strip() or str(nome).strip().upper() == "NULL":
        return None
    partes = re.sub(r"\s+", " ", str(nome).strip()).lower().split(" ")
    return " ".join(p if (i and p in PARTICULAS) else p[:1].upper() + p[1:] for i, p in enumerate(partes))[:160]


def cpf_ou_none(v) -> str | None:
    d = normalizar_cpf(str(v or ""))
    return d if len(d) == 11 and cpf_valido(d) else None


def turma_de(texto: str) -> tuple[str, str, str | None]:
    """'5° Ano (Ensino Fundamental - Anos Iniciais) A' → ('5º Ano', 'Turma A', 'Ensino Fundamental - Anos Iniciais')."""
    t = re.sub(r"\s+", " ", (texto or "").replace("°", "º")).strip()
    m = RE_TURMA.match(t)
    if not m or not m.group("ano"):
        return (t or "Sem turma")[:40], "Turma Única", None
    ano = m.group("ano").strip()[:40]
    letra = m.group("letra")
    return ano, (f"Turma {letra}" if letra else "Turma Única"), (m.group("seg") or None)


@dataclass
class Linha:
    aluno_id: str
    nome: str
    nascimento: date | None
    cpf_aluno: str | None
    ano: str
    turma: str
    segmento: str | None
    ano_letivo: int | None
    status: str
    ativo: bool
    pai: str | None
    cpf_pai: str | None
    mae: str | None
    cpf_mae: str | None


@dataclass
class Leitura:
    linhas: list = field(default_factory=list)
    avisos: list = field(default_factory=list)


def ler(dados: list) -> Leitura:
    if not isinstance(dados, list):
        raise ValueError("O arquivo deve conter uma lista de alunos.")
    out = Leitura()
    anos = [int(r["ano_letivo"]) for r in dados if str(r.get("ano_letivo") or "").isdigit()]
    ano_atual = max(anos) if anos else None
    vistos = set()
    for i, r in enumerate(dados, start=1):
        aid = str(r.get("aluno_id") or "").strip()
        nome = nome_proprio(r.get("nome_aluno"))
        if not aid or not nome:
            out.avisos.append(f"Registro {i}: sem aluno_id ou nome — ignorado.")
            continue
        if aid in vistos:
            out.avisos.append(f"Registro {i}: aluno_id {aid} repetido — ignorado.")
            continue
        vistos.add(aid)
        try:
            nasc = date.fromisoformat(str(r.get("data_nascimento"))[:10])
        except ValueError:
            nasc = None
        ano, turma, seg = turma_de(r.get("turma"))
        ano_letivo = int(r["ano_letivo"]) if str(r.get("ano_letivo") or "").isdigit() else None
        status = (str(r.get("status_vinculo") or "").strip().lower() or "desconhecido")[:20]
        cpfs = {}
        for campo in ("cpf_aluno", "cpf_pai", "cpf_mae"):
            bruto = normalizar_cpf(str(r.get(campo) or ""))
            cpfs[campo] = cpf_ou_none(bruto)
            if bruto and not cpfs[campo]:
                out.avisos.append(f"Aluno {aid}: {campo} inválido — descartado.")
        pai, mae = nome_proprio(r.get("nome_pai")), nome_proprio(r.get("nome_mae"))
        if cpfs["cpf_pai"] and cpfs["cpf_pai"] == cpfs["cpf_mae"]:
            out.avisos.append(f"Aluno {aid}: pai e mãe com o mesmo CPF — mantido só na mãe.")
            cpfs["cpf_pai"] = None
        out.linhas.append(Linha(
            aluno_id=aid[:40], nome=nome, nascimento=nasc, cpf_aluno=cpfs["cpf_aluno"], ano=ano, turma=turma,
            segmento=seg, ano_letivo=ano_letivo, status=status,
            ativo=(status == "ativo" and (ano_letivo == ano_atual or ano_atual is None)),
            pai=pai, cpf_pai=cpfs["cpf_pai"], mae=mae, cpf_mae=cpfs["cpf_mae"]))
    return out


def ler_arquivo(caminho: str) -> Leitura:
    with open(caminho, encoding="utf-8-sig") as f:
        return ler(json.load(f))


# ---------------------------------------------------------------------------
# SQL para o Supabase (hash do CPF calculado NO BANCO com o pepper informado)
# ---------------------------------------------------------------------------
def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


def gerar_sql(leitura: Leitura) -> str:
    colunas = ["aluno_id", "nome", "nascimento", "cpf_aluno", "ano", "turma", "segmento", "ano_letivo",
               "status", "ativo", "pai", "cpf_pai", "mae", "cpf_mae"]
    valores = ",\n  ".join(
        "(" + ", ".join(_lit(getattr(l, c)) for c in colunas) + ")" for l in leitura.linhas)
    avisos = "\n".join(f"--   {a}" for a in leitura.avisos) or "--   (nenhum)"
    n_ativos = sum(1 for l in leitura.linhas if l.ativo)
    return f"""-- >>>>>>>>>> PREENCHA AS LINHAS 4 E 5 E DEPOIS CLIQUE EM "RUN" <<<<<<<<<<
BEGIN;
CREATE TEMP TABLE _cfg ON COMMIT DROP AS SELECT
  '00000000'::text               AS inep,    -- >>> 1) troque 00000000 pelo INEP da escola (8 dígitos)
  'COLE-AQUI-O-CPF_PEPPER'::text AS pepper;  -- >>> 2) troque pelo CPF_PEPPER do servidor (Render)

-- =====================================================================
-- Autoriza Escolar — importação de ALUNOS e RESPONSÁVEIS (dados reais — LGPD)
-- {len(leitura.linhas)} alunos ({n_ativos} ativos). NÃO versione nem compartilhe este arquivo.
--
-- 1) INEP: a escola já deve existir (escolas.sql). Para consultar:
--      SELECT nome, inep FROM escola ORDER BY nome;
-- 2) CPF_PEPPER: EXATAMENTE o mesmo do servidor (Render → Environment),
--    senão os responsáveis não conseguem entrar. Ele não fica salvo em lugar nenhum.
--
-- Pré-requisitos: schema.sql (versão atual) e escolas.sql já executados.
-- Pode ser executado mais de uma vez: atualiza sem duplicar.
--
-- Avisos da leitura do arquivo:
{avisos}
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

DO $chk$
DECLARE c record;
BEGIN
  SELECT * INTO c FROM _cfg;
  IF NOT EXISTS (SELECT 1 FROM escola WHERE inep = c.inep) THEN
    RAISE EXCEPTION 'Escola com INEP % não encontrada. Preencha o INEP na LINHA 4 do arquivo (topo).', c.inep;
  END IF;
  IF c.pepper = 'COLE-AQUI-O-CPF_PEPPER' OR length(c.pepper) < 16 THEN
    RAISE EXCEPTION 'Preencha o CPF_PEPPER do servidor na LINHA 5 do arquivo (topo).';
  END IF;
END
$chk$;

CREATE TEMP TABLE _imp (
  aluno_id text, nome text, nascimento date, cpf_aluno text, ano text, turma text, segmento text,
  ano_letivo int, status text, ativo boolean, pai text, cpf_pai text, mae text, cpf_mae text
) ON COMMIT DROP;

INSERT INTO _imp ({", ".join(colunas)}) VALUES
  {valores};

-- Hash do CPF igual ao do sistema: HMAC-SHA256(cpf, CPF_PEPPER) em hexadecimal
CREATE TEMP TABLE _h ON COMMIT DROP AS
SELECT i.*,
       e.id AS escola_id,
       CASE WHEN i.cpf_aluno IS NOT NULL THEN encode(extensions.hmac(i.cpf_aluno, c.pepper, 'sha256'), 'hex') END AS h_aluno,
       CASE WHEN i.cpf_pai   IS NOT NULL THEN encode(extensions.hmac(i.cpf_pai,   c.pepper, 'sha256'), 'hex') END AS h_pai,
       CASE WHEN i.cpf_mae   IS NOT NULL THEN encode(extensions.hmac(i.cpf_mae,   c.pepper, 'sha256'), 'hex') END AS h_mae
FROM _imp i CROSS JOIN _cfg c JOIN escola e ON e.inep = c.inep;

-- 1) Turmas
INSERT INTO turma (nome, ano, escola_id, segmento)
SELECT DISTINCT h.turma, h.ano, h.escola_id, h.segmento FROM _h h
WHERE NOT EXISTS (SELECT 1 FROM turma t WHERE t.escola_id = h.escola_id AND t.ano = h.ano AND t.nome = h.turma);
UPDATE turma t SET segmento = h.segmento
FROM (SELECT DISTINCT escola_id, ano, turma, segmento FROM _h) h
WHERE t.escola_id = h.escola_id AND t.ano = h.ano AND t.nome = h.turma AND t.segmento IS NULL;

-- 2) Alunos (matrícula = aluno_id da origem)
INSERT INTO aluno (public_id, matricula, id_externo, nome, data_nascimento, escola_id, turma_id, ativo,
                   cpf_hash, cpf_final, ano_letivo, situacao_matricula)
SELECT gen_random_uuid()::text, h.aluno_id, h.aluno_id, h.nome, h.nascimento, h.escola_id, t.id, h.ativo,
       h.h_aluno, right(h.cpf_aluno, 2), h.ano_letivo, h.status
FROM _h h JOIN turma t ON t.escola_id = h.escola_id AND t.ano = h.ano AND t.nome = h.turma
ON CONFLICT (matricula) DO UPDATE SET
  id_externo = EXCLUDED.id_externo, nome = EXCLUDED.nome, data_nascimento = EXCLUDED.data_nascimento,
  escola_id = EXCLUDED.escola_id, turma_id = EXCLUDED.turma_id, ativo = EXCLUDED.ativo,
  cpf_hash = EXCLUDED.cpf_hash, cpf_final = EXCLUDED.cpf_final, ano_letivo = EXCLUDED.ano_letivo,
  situacao_matricula = EXCLUDED.situacao_matricula;

-- 3) Responsáveis COM CPF (únicos pelo CPF; irmãos compartilham o cadastro)
INSERT INTO responsavel (public_id, nome, cpf_hash, cpf_final, ativo, criado_em)
SELECT DISTINCT ON (x.h) gen_random_uuid()::text, x.nome, x.h, x.fim, true, now() AT TIME ZONE 'utc'
FROM (SELECT mae AS nome, h_mae AS h, right(cpf_mae, 2) AS fim FROM _h WHERE h_mae IS NOT NULL
      UNION ALL
      SELECT pai, h_pai, right(cpf_pai, 2) FROM _h WHERE h_pai IS NOT NULL) x
ORDER BY x.h, x.nome
ON CONFLICT (cpf_hash) DO NOTHING;

-- 4) Responsáveis SEM CPF (um cadastro por aluno/papel; sem acesso até informar o CPF)
INSERT INTO responsavel (public_id, nome, id_externo, ativo, criado_em)
SELECT gen_random_uuid()::text, x.nome, x.ext, true, now() AT TIME ZONE 'utc'
FROM (SELECT mae AS nome, aluno_id || '-MAE' AS ext FROM _h WHERE h_mae IS NULL AND mae IS NOT NULL
      UNION ALL
      SELECT pai, aluno_id || '-PAI' FROM _h WHERE h_pai IS NULL AND pai IS NOT NULL) x
ON CONFLICT (id_externo) DO UPDATE SET nome = EXCLUDED.nome;

-- 5) Vínculos responsável ↔ aluno (Mãe / Pai), todos podem autorizar
INSERT INTO responsavel_aluno (responsavel_id, aluno_id, tipo_vinculo, responsavel_legal, ativo)
SELECT r.id, a.id, v.tipo, true, true
FROM (SELECT aluno_id, 'Mãe' AS tipo, h_mae AS h, aluno_id || '-MAE' AS ext FROM _h WHERE mae IS NOT NULL
      UNION ALL
      SELECT aluno_id, 'Pai', h_pai, aluno_id || '-PAI' FROM _h WHERE pai IS NOT NULL) v
JOIN aluno a ON a.matricula = v.aluno_id
JOIN responsavel r ON (v.h IS NOT NULL AND r.cpf_hash = v.h) OR (v.h IS NULL AND r.id_externo = v.ext)
ON CONFLICT (responsavel_id, aluno_id) DO UPDATE SET tipo_vinculo = EXCLUDED.tipo_vinculo, ativo = true;

-- 6) Alunos ativos entram nos passeios que já incluem a turma deles
INSERT INTO passeio_aluno (passeio_id, aluno_id)
SELECT pt.passeio_id, a.id FROM passeio_turma pt
JOIN aluno a ON a.turma_id = pt.turma_id AND a.ativo
JOIN _h h ON h.aluno_id = a.matricula
ON CONFLICT (passeio_id, aluno_id) DO NOTHING;

COMMIT;

-- Conferência
SELECT (SELECT count(*) FROM aluno WHERE id_externo IS NOT NULL)                AS alunos_importados,
       (SELECT count(*) FROM aluno WHERE id_externo IS NOT NULL AND ativo)      AS alunos_ativos,
       (SELECT count(*) FROM responsavel WHERE cpf_hash IS NOT NULL)            AS responsaveis_com_cpf,
       (SELECT count(*) FROM responsavel WHERE cpf_hash IS NULL)                AS responsaveis_sem_cpf,
       (SELECT count(*) FROM responsavel_aluno)                                 AS vinculos;
"""


# ---------------------------------------------------------------------------
# Importação direta pelo sistema (banco local ou DATABASE_URL), mesmas regras
# ---------------------------------------------------------------------------
def importar_local(leitura: Leitura, inep: str) -> dict:
    from ..extensions import db
    from ..models import Aluno, Escola, Responsavel, ResponsavelAluno, Turma
    from ..security import hash_cpf
    escola = Escola.query.filter_by(inep=inep).first()
    if escola is None:
        raise ValueError(f"Escola com INEP {inep} não encontrada.")
    turmas = {(t.ano, t.nome): t for t in escola.turmas}
    por_hash = {}
    for l in leitura.linhas:
        t = turmas.get((l.ano, l.turma))
        if t is None:
            t = Turma(escola_id=escola.id, ano=l.ano, nome=l.turma, segmento=l.segmento)
            db.session.add(t)
            db.session.flush()
            turmas[(l.ano, l.turma)] = t
        elif not t.segmento:
            t.segmento = l.segmento
        a = Aluno.query.filter_by(matricula=l.aluno_id).first() or Aluno(matricula=l.aluno_id)
        a.id_externo, a.nome, a.data_nascimento = l.aluno_id, l.nome, l.nascimento
        a.escola_id, a.turma_id, a.ativo = escola.id, t.id, l.ativo
        a.cpf_hash = hash_cpf(l.cpf_aluno) if l.cpf_aluno else None
        a.cpf_final = l.cpf_aluno[-2:] if l.cpf_aluno else None
        a.ano_letivo, a.situacao_matricula = l.ano_letivo, l.status
        db.session.add(a)
        db.session.flush()
        for tipo, nome, cpf, sufixo in (("Mãe", l.mae, l.cpf_mae, "MAE"), ("Pai", l.pai, l.cpf_pai, "PAI")):
            if not nome:
                continue
            if cpf:
                h = hash_cpf(cpf)
                r = por_hash.get(h) or Responsavel.query.filter_by(cpf_hash=h).first()
                if r is None:
                    r = Responsavel(nome=nome, cpf_hash=h, cpf_final=cpf[-2:])
                    db.session.add(r)
                por_hash[h] = r
            else:
                ext = f"{l.aluno_id}-{sufixo}"
                r = Responsavel.query.filter_by(id_externo=ext).first() or Responsavel(id_externo=ext, nome=nome)
                r.nome = nome
                db.session.add(r)
            db.session.flush()
            v = ResponsavelAluno.query.filter_by(responsavel_id=r.id, aluno_id=a.id).first()
            if v is None:
                db.session.add(ResponsavelAluno(responsavel_id=r.id, aluno_id=a.id, tipo_vinculo=tipo,
                                                responsavel_legal=True, ativo=True))
            else:
                v.tipo_vinculo, v.ativo = tipo, True
    db.session.flush()
    from ..models import Passeio
    from .passeio_service import sincronizar_participantes
    for p in Passeio.query.filter(Passeio.turmas.any(Turma.escola_id == escola.id)).all():
        sincronizar_participantes(p)
    return {"alunos": len(leitura.linhas), "ativos": sum(1 for l in leitura.linhas if l.ativo)}

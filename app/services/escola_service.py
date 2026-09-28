"""Cadastro de escolas e turmas, e importação do JSON da rede (schools_data.json).

A importação é idempotente: escolas são localizadas pelo INEP (ou pelo nome, se o
INEP faltar) e atualizadas; nada é duplicado ao importar o mesmo arquivo de novo.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field

from .. import audit
from ..extensions import db
from ..models import AdminUsuario, Aluno, Escola, Passeio, Turma

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Anos/séries oferecidos no cadastro de turmas em lote (ordem de exibição).
ANOS_PADRAO = ["Berçário", "Nível I", "Nível II", "Maternal I", "Maternal II", "Pré I", "Pré II",
               "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano", "6º Ano", "7º Ano", "8º Ano", "9º Ano",
               "EJA"]


def anos_da_modalidade(modalidade: str | None) -> list[str]:
    """Deduz os anos/séries a partir do texto de modalidade da rede. Exemplos:
    'Pré ao 9º Ano' → Pré I, Pré II, 1º…9º Ano · 'Pré II ao 7º ano' → Pré II, 1º…7º Ano
    '6º ao 9º Ano' → 6º…9º Ano · 'Pré I e PréII' → Pré I, Pré II
    'Berçário NI e NII' → Berçário, Nível I, Nível II · '... EJA' → acrescenta EJA."""
    t = (modalidade or "").replace("°", "º").strip()
    if not t:
        return []
    baixo = t.lower()
    anos: list[str] = []
    faixa = re.search(r"(pr[ée]\s*(ii|i)?|(\d)\s*º)\s*(?:ano\s*)?ao\s*(\d)\s*º", baixo)
    if faixa:
        fim = int(faixa.group(4))
        if faixa.group(1).startswith("pr"):
            anos += ["Pré II"] if faixa.group(2) == "ii" else ["Pré I", "Pré II"]
            inicio = 1
        else:
            inicio = int(faixa.group(3))
        anos += [f"{n}º Ano" for n in range(inicio, fim + 1)]
    elif re.search(r"pr[ée]\s*i\b", baixo) or re.search(r"pr[ée]\s*ii\b", baixo):
        if re.search(r"pr[ée]\s*i\b", baixo):
            anos.append("Pré I")
        if re.search(r"pr[ée]\s*ii\b", baixo):
            anos.append("Pré II")
    if "berç" in baixo or "berc" in baixo:
        anos.append("Berçário")
        if re.search(r"\bni\b", baixo):
            anos.append("Nível I")
        if re.search(r"\bnii\b", baixo):
            anos.append("Nível II")
    if re.search(r"\beja\b", baixo):
        anos.append("EJA")
    return anos


class ErroEscola(ValueError):
    pass


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------
def _txt(v, maximo=200) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip().strip(",").strip()
    return s[:maximo] or None


def _primeiro_email(v) -> str | None:
    m = RE_EMAIL.search(str(v or ""))
    return m.group(0).lower() if m else None


def _complemento(v) -> str | None:
    s = _txt(v, 120)
    if not s:
        return None
    s = s.lstrip(", ").strip()
    return None if s.lower() in {"s/n", "sn", "-"} else s


def _inep(v) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d if len(d) == 8 else None


def _cep(v) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else None


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalizar_registro(r: dict) -> dict:
    """Converte um item do JSON (chaves em inglês) para os campos de Escola."""
    return {
        "nome": _txt(r.get("name"), 160),
        "inep": _inep(r.get("inep")),
        "cnpj": _txt(r.get("cnpj"), 18),
        "email": _primeiro_email(r.get("email")),
        "telefone": _txt(r.get("phone"), 30),
        "ramal": _txt(r.get("ramal"), 10),
        "diretor": _txt(r.get("director"), 160),
        "vice_diretor": _txt(r.get("deputy_director"), 160),
        "modalidade": _txt(r.get("modality"), 120),
        "turno": _txt(r.get("shift"), 40),
        "qtd_salas": _int(r.get("room_count")),
        "logradouro": _txt(r.get("street"), 200),
        "numero": _txt(r.get("number"), 20),
        "complemento": _complemento(r.get("complement")),
        "bairro": _txt(r.get("area") or r.get("neighborhood"), 120),
        "cidade": _txt(r.get("city"), 80),
        "uf": (_txt(r.get("state"), 2) or "").upper() or None,
        "cep": _cep(r.get("cep")),
        "maps_link": _txt(r.get("maps_link"), 300) if str(r.get("maps_link") or "").startswith("https://") else None,
    }


def _chave_nome(nome: str) -> str:
    n = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", n)


# ---------------------------------------------------------------------------
# Importação
# ---------------------------------------------------------------------------
@dataclass
class Relatorio:
    criadas: int = 0
    atualizadas: int = 0
    avisos: list = field(default_factory=list)


def importar(dados: list, adm: AdminUsuario | None = None) -> Relatorio:
    if not isinstance(dados, list):
        raise ErroEscola("O arquivo deve conter uma lista de escolas.")
    rel = Relatorio()
    inep_no_arquivo: dict[str, str] = {}
    existentes = Escola.query.all()
    por_inep = {e.inep: e for e in existentes if e.inep}
    por_nome = {_chave_nome(e.nome): e for e in existentes}
    for i, bruto in enumerate(dados, start=1):
        if not isinstance(bruto, dict):
            rel.avisos.append(f"Item {i}: formato inválido, ignorado.")
            continue
        d = normalizar_registro(bruto)
        if not d["nome"]:
            rel.avisos.append(f"Item {i}: sem nome, ignorado.")
            continue
        if bruto.get("inep") and not d["inep"]:
            rel.avisos.append(f"{d['nome']}: INEP inválido ({bruto.get('inep')}); importada sem INEP.")
        if d["inep"] and d["inep"] in inep_no_arquivo:
            rel.avisos.append(f"{d['nome']}: INEP {d['inep']} repetido (já usado por {inep_no_arquivo[d['inep']]}); "
                              "importada sem INEP — corrija no cadastro.")
            d["inep"] = None
        if d["inep"]:
            inep_no_arquivo[d["inep"]] = d["nome"]
        if bruto.get("email") and d["email"] != str(bruto.get("email")).strip().lower():
            if not d["email"]:
                rel.avisos.append(f"{d['nome']}: e-mail inválido ({bruto.get('email')}); deixado em branco.")
        escola = (por_inep.get(d["inep"]) if d["inep"] else None) or por_nome.get(_chave_nome(d["nome"]))
        if escola is None:
            escola = Escola(codigo=d["inep"] or _codigo_livre(d["nome"]), ativo=True)
            db.session.add(escola)
            rel.criadas += 1
        else:
            rel.atualizadas += 1
        for campo, valor in d.items():
            setattr(escola, campo, valor)
        if d["inep"] and escola.codigo != d["inep"] and not Escola.query.filter(
                Escola.codigo == d["inep"], Escola.id != (escola.id or 0)).first():
            escola.codigo = d["inep"]
        db.session.flush()
        if escola.inep:
            por_inep[escola.inep] = escola
        por_nome[_chave_nome(escola.nome)] = escola
    if adm is not None:
        audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo="escolas",
                        detalhes={"acao": "importar_escolas", "criadas": rel.criadas,
                                  "atualizadas": rel.atualizadas, "avisos": len(rel.avisos)}, commit=False)
    return rel


def importar_arquivo(conteudo: bytes, adm=None) -> Relatorio:
    try:
        dados = json.loads(conteudo.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ErroEscola("Arquivo JSON inválido.")
    return importar(dados, adm)


def _codigo_livre(nome: str) -> str:
    base = "ESC-" + (_chave_nome(nome)[:20].upper() or "SEMNOME")
    codigo, n = base, 2
    while Escola.query.filter_by(codigo=codigo).first():
        codigo, n = f"{base}-{n}", n + 1
    return codigo[:30]


def sql_supabase(dados: list) -> str:
    """Gera SQL idempotente (INSERT ... ON CONFLICT) para rodar no SQL Editor do Supabase."""
    colunas = ["nome", "codigo", "inep", "cnpj", "email", "telefone", "ramal", "diretor", "vice_diretor",
               "modalidade", "turno", "qtd_salas", "logradouro", "numero", "complemento", "bairro", "cidade",
               "uf", "cep", "maps_link", "ativo"]

    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"

    vistos, linhas_com, linhas_sem = set(), [], []
    for bruto in dados:
        d = normalizar_registro(bruto)
        if not d["nome"]:
            continue
        if d["inep"] in vistos:
            d["inep"] = None
        if d["inep"]:
            vistos.add(d["inep"])
        d["codigo"] = d["inep"] or ("ESC-" + _chave_nome(d["nome"])[:20].upper())
        d["ativo"] = True
        valores = "(" + ", ".join(lit(d[c]) for c in colunas) + ")"
        (linhas_com if d["inep"] else linhas_sem).append(valores)
    atualiza = ",\n  ".join(f"{c} = EXCLUDED.{c}" for c in colunas if c not in ("codigo", "inep", "ativo"))
    partes = ["-- Escolas da rede — gerado a partir de schools_data.json",
              "-- Idempotente: pode ser executado mais de uma vez (atualiza pelo INEP/código).",
              "BEGIN;"]
    if linhas_com:
        partes.append(f"INSERT INTO escola ({', '.join(colunas)}) VALUES\n  " + ",\n  ".join(linhas_com) +
                      f"\nON CONFLICT (inep) DO UPDATE SET\n  {atualiza};")
    if linhas_sem:
        partes.append("-- Escolas sem INEP válido/único (revise o INEP no painel):")
        partes.append(f"INSERT INTO escola ({', '.join(colunas)}) VALUES\n  " + ",\n  ".join(linhas_sem) +
                      f"\nON CONFLICT (codigo) DO UPDATE SET\n  {atualiza};")
    # Turmas deduzidas da modalidade ("Turma A" por ano/série), sem duplicar.
    partes.append("-- Turmas geradas a partir da modalidade de cada escola (ajuste no painel se necessário):")
    vistos2 = set()
    for bruto in dados:
        d = normalizar_registro(bruto)
        if not d["nome"]:
            continue
        if d["inep"] in vistos2:
            d["inep"] = None
        if d["inep"]:
            vistos2.add(d["inep"])
        codigo = d["inep"] or ("ESC-" + _chave_nome(d["nome"])[:20].upper())
        anos = anos_da_modalidade(d["modalidade"])
        if not anos:
            partes.append(f"-- {d['nome']}: modalidade não informada; cadastre as turmas no painel.")
            continue
        valores = ", ".join(f"({lit(a)})" for a in anos)
        partes.append(
            "INSERT INTO turma (nome, ano, escola_id)\n"
            f"SELECT 'Turma A', v.ano, e.id FROM escola e CROSS JOIN (VALUES {valores}) AS v(ano)\n"
            f"WHERE e.codigo = {lit(codigo)} AND NOT EXISTS (SELECT 1 FROM turma t "
            "WHERE t.escola_id = e.id AND t.ano = v.ano AND t.nome = 'Turma A');")
    partes.append("COMMIT;")
    return "\n".join(partes) + "\n"


# ---------------------------------------------------------------------------
# Cadastro manual
# ---------------------------------------------------------------------------
CAMPOS_FORM = ["nome", "inep", "cnpj", "email", "telefone", "ramal", "diretor", "vice_diretor", "modalidade",
               "turno", "qtd_salas", "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "cep",
               "maps_link"]


def salvar(adm, escola: Escola | None, form) -> Escola:
    novo = escola is None
    nome = _txt(form.get("nome"), 160)
    if not nome or len(nome) < 3:
        raise ErroEscola("Informe o nome da escola.")
    inep = _inep(form.get("inep")) if form.get("inep") else None
    if form.get("inep") and not inep:
        raise ErroEscola("O INEP deve ter 8 dígitos.")
    if inep and Escola.query.filter(Escola.inep == inep, Escola.id != (escola.id if escola else 0)).first():
        raise ErroEscola(f"O INEP {inep} já pertence a outra escola.")
    email = (form.get("email") or "").strip()
    if email and not RE_EMAIL.fullmatch(email):
        raise ErroEscola("E-mail inválido.")
    maps = (form.get("maps_link") or "").strip()
    if maps and not maps.startswith("https://"):
        raise ErroEscola("O link do mapa deve começar com https://")
    if novo:
        escola = Escola(codigo=inep or _codigo_livre(nome), ativo=True)
        db.session.add(escola)
    escola.nome, escola.inep = nome, inep
    escola.email = email.lower() or None
    for campo in ("cnpj", "telefone", "ramal", "diretor", "vice_diretor", "modalidade", "turno", "logradouro",
                  "numero", "bairro", "cidade"):
        setattr(escola, campo, _txt(form.get(campo), 200))
    escola.complemento = _complemento(form.get("complemento"))
    escola.qtd_salas = _int(form.get("qtd_salas"))
    escola.uf = (_txt(form.get("uf"), 2) or "").upper() or None
    escola.cep = _cep(form.get("cep"))
    escola.maps_link = maps or None
    escola.ativo = form.get("ativo", "1") == "1"
    db.session.flush()
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"escola:{escola.id}",
                    detalhes={"acao": "criar_escola" if novo else "editar_escola", "nome": nome}, commit=False)
    return escola


def excluir(adm, escola: Escola) -> str:
    """Apaga se não houver alunos, usuários ou turmas em passeios; senão desativa."""
    tem_alunos = Aluno.query.filter_by(escola_id=escola.id).first() is not None
    tem_usuarios = AdminUsuario.query.filter_by(escola_id=escola.id).first() is not None
    em_passeio = Passeio.query.filter(Passeio.turmas.any(Turma.escola_id == escola.id)).first() is not None
    if tem_alunos or tem_usuarios or em_passeio:
        escola.ativo = False
        resultado = "desativada"
    else:
        Turma.query.filter_by(escola_id=escola.id).delete()
        db.session.delete(escola)
        resultado = "excluida"
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"escola:{escola.id}",
                    detalhes={"acao": f"escola_{resultado}", "nome": escola.nome}, commit=False)
    return resultado


# ---------------------------------------------------------------------------
# Turmas
# ---------------------------------------------------------------------------
def criar_turmas(adm, escola: Escola, anos: list[str], letras: str) -> int:
    """Cria turmas em lote: cada ano × cada letra (ex.: A,B → 'Turma A', 'Turma B')."""
    anos = [_txt(a, 40) for a in anos if _txt(a, 40)]
    nomes = [f"Turma {l.strip().upper()}" for l in re.split(r"[,;\s]+", letras or "") if l.strip()]
    if not anos:
        raise ErroEscola("Selecione ao menos um ano/série.")
    if not nomes:
        raise ErroEscola("Informe as turmas (ex.: A, B, C).")
    existentes = {(t.ano, t.nome) for t in escola.turmas}
    criadas = 0
    for ano in anos:
        for nome in nomes:
            if (ano, nome[:40]) not in existentes:
                db.session.add(Turma(escola_id=escola.id, ano=ano, nome=nome[:40]))
                criadas += 1
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"escola:{escola.id}",
                    detalhes={"acao": "criar_turmas", "quantidade": criadas}, commit=False)
    return criadas


def gerar_turmas_pela_modalidade(adm, escola: Escola, letras: str = "A") -> int:
    anos = anos_da_modalidade(escola.modalidade)
    if not anos:
        raise ErroEscola(f"Não foi possível deduzir os anos a partir da modalidade de {escola.nome}.")
    return criar_turmas(adm, escola, anos, letras)


def excluir_turma(adm, escola: Escola, turma_id: int) -> None:
    t = Turma.query.filter_by(id=turma_id, escola_id=escola.id).first()
    if t is None:
        raise ErroEscola("Turma não encontrada.")
    if Aluno.query.filter_by(turma_id=t.id).first():
        raise ErroEscola(f"{t.ano} — {t.nome} tem alunos; transfira-os antes de excluir a turma.")
    if Passeio.query.filter(Passeio.turmas.any(Turma.id == t.id)).first():
        raise ErroEscola(f"{t.ano} — {t.nome} participa de um passeio; remova-a do passeio antes.")
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"escola:{escola.id}",
                    detalhes={"acao": "excluir_turma", "turma": f"{t.ano} {t.nome}"}, commit=False)
    db.session.delete(t)

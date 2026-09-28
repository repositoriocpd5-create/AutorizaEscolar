"""Configurações gerais editáveis pelo painel administrativo.

Os valores ficam na tabela ``configuracao``; na ausência, valem os padrões
abaixo (e, para o nome da instituição, a variável INSTITUICAO_NOME do .env).
"""
from flask import current_app, g, url_for

from ..extensions import db
from ..models import Configuracao, Passeio

CHAVES = {
    "instituicao_nome": "Nome da instituição",
    "titulo_sistema": "Título do sistema",
    "subtitulo": "Subtítulo da tela inicial",
    "passeio_destaque": "Passeio em destaque na tela inicial",
    "brasao": "Brasão / logotipo",
    "imagem_inicial": "Imagem padrão da tela inicial",
    "ilustracao_inicial": "Ilustração padrão da tela inicial",
}

# Galeria de ilustrações prontas (app/static/img/eventos/<chave>.svg).
ILUSTRACOES = {
    "cinema": "Cinema",
    "museu": "Museu / exposição",
    "teatro": "Teatro / espetáculo",
    "parque": "Parque / lazer",
    "viagem": "Viagem / excursão",
    "esporte": "Competição esportiva",
    "musica": "Evento cultural / música",
    "visita-tecnica": "Visita técnica",
    "ciencia": "Ciência / planetário",
}


def url_ilustracao(chave: str | None) -> str:
    chave = chave if chave in ILUSTRACOES else "cinema"
    return url_for("static", filename=f"img/eventos/{chave}.svg")


def _padroes() -> dict:
    return {
        "instituicao_nome": current_app.config["INSTITUICAO_NOME"],
        "titulo_sistema": "Passeios Escolares",
        "subtitulo": "Sistema de Autorização de Alunos",
        "passeio_destaque": "",
        "brasao": "",
        "imagem_inicial": "",
        "ilustracao_inicial": "cinema",
    }


def todas() -> dict:
    if "_config" not in g:
        valores = _padroes()
        for c in Configuracao.query.all():
            if c.chave in valores and c.valor not in (None, ""):
                valores[c.chave] = c.valor
        g._config = valores
    return g._config


def obter(chave: str) -> str:
    return todas().get(chave, "")


def definir(chave: str, valor: str | None) -> None:
    if chave not in CHAVES:
        raise KeyError(chave)
    item = db.session.get(Configuracao, chave) or Configuracao(chave=chave)
    item.valor = (valor or "").strip() or None
    db.session.add(item)
    g.pop("_config", None)


def imagem_passeio(p: Passeio | None) -> tuple[str, bool]:
    """(url, é_foto_enviada) da imagem de um passeio: upload > ilustração escolhida."""
    from .midia_service import caminho
    if p is not None and caminho(p.imagem):
        return url_for("public.midia", nome=p.imagem), True
    return url_ilustracao(p.ilustracao if p is not None else None), False


def imagem_inicial() -> tuple[str, bool]:
    """Imagem da tela inicial: passeio em destaque > imagem enviada nas configurações > ilustração padrão."""
    from .midia_service import caminho
    destaque = passeio_destaque()
    if destaque is not None and (caminho(destaque.imagem) or destaque.ilustracao):
        return imagem_passeio(destaque)
    if caminho(obter("imagem_inicial")):
        return url_for("public.midia", nome=obter("imagem_inicial")), True
    return url_ilustracao(obter("ilustracao_inicial")), False


def url_midia(nome: str | None, padrao: str) -> str:
    from .midia_service import caminho
    if caminho(nome):
        return url_for("public.midia", nome=nome)
    return url_for("static", filename=padrao)


def brasao_url() -> str:
    return url_midia(obter("brasao"), "img/brasao-256.png")


def passeio_destaque() -> Passeio | None:
    """Passeio escolhido no painel; senão, o ativo com data mais próxima."""
    pid = obter("passeio_destaque")
    if pid:
        p = Passeio.query.filter_by(public_id=pid, ativo=True).first()
        if p:
            return p
    return Passeio.query.filter_by(ativo=True).order_by(Passeio.data.desc()).first()

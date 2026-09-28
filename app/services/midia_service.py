"""Upload seguro de imagens (brasão, imagem do passeio).

A imagem enviada é aberta com Pillow, validada e REGRAVADA em PNG com nome
aleatório — nunca servimos o arquivo original (evita SVG/HTML disfarçado,
metadados EXIF com localização, etc.).

As imagens ficam no BANCO (tabela ``midia``), e não no disco: hospedagens como
o Render apagam o disco a cada nova versão. Arquivos antigos em
``instance/uploads`` continuam sendo lidos como alternativa.
"""
import io
import re
import secrets
from pathlib import Path

from flask import current_app, g
from PIL import Image, UnidentifiedImageError

from ..extensions import db
from ..models import Midia

TAMANHO_MAXIMO = 5 * 1024 * 1024
FORMATOS = {"PNG", "JPEG", "WEBP", "GIF"}
RE_NOME = re.compile(r"^[a-z]+-[0-9a-f]{24}\.png$")


class ErroImagem(ValueError):
    pass


def salvar(arquivo, prefixo: str, max_lado: int = 1200) -> str:
    """Valida e grava o upload (a gravação é confirmada no commit de quem chamou).
    Retorna o nome gerado."""
    if arquivo is None or not arquivo.filename:
        raise ErroImagem("Nenhum arquivo enviado.")
    bruto = arquivo.read(TAMANHO_MAXIMO + 1)
    if len(bruto) > TAMANHO_MAXIMO:
        raise ErroImagem("A imagem deve ter no máximo 5 MB.")
    try:
        img = Image.open(io.BytesIO(bruto))
        if img.format not in FORMATOS:
            raise ErroImagem("Formato não suportado. Envie PNG, JPG, WEBP ou GIF.")
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ErroImagem("Arquivo de imagem inválido.")
    img = img.convert("RGBA")
    bbox = img.getbbox()  # remove bordas transparentes
    if bbox:
        img = img.crop(bbox)
    img.thumbnail((max_lado, max_lado))
    saida = io.BytesIO()
    img.save(saida, "PNG", optimize=True)
    nome = f"{prefixo}-{secrets.token_hex(12)}.png"
    db.session.add(Midia(nome=nome, dados=saida.getvalue()))
    _cache().pop(nome, None)
    return nome


def _cache() -> dict:
    if "_midia" not in g:
        g._midia = {}
    return g._midia


def _arquivo_legado(nome: str) -> Path:
    return Path(current_app.instance_path) / "uploads" / nome


def dados(nome: str | None) -> bytes | None:
    """Bytes PNG da imagem ou None se o nome for inválido/inexistente."""
    if not nome or not RE_NOME.match(nome):
        return None
    cache = _cache()
    if nome not in cache:
        m = db.session.get(Midia, nome)
        if m is not None:
            cache[nome] = m.dados
        else:
            legado = _arquivo_legado(nome)
            cache[nome] = legado.read_bytes() if legado.exists() else None
    return cache[nome]


def existe(nome: str | None) -> bool:
    return dados(nome) is not None

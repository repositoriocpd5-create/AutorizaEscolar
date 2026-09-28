"""Upload seguro de imagens (brasão, imagem do passeio).

A imagem enviada é aberta com Pillow, validada e REGRAVADA em PNG com nome
aleatório — nunca servimos o arquivo original (evita SVG/HTML disfarçado,
metadados EXIF com localização, etc.).
"""
import re
import secrets
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError

TAMANHO_MAXIMO = 5 * 1024 * 1024
FORMATOS = {"PNG", "JPEG", "WEBP", "GIF"}
RE_NOME = re.compile(r"^[a-z]+-[0-9a-f]{24}\.png$")


class ErroImagem(ValueError):
    pass


def pasta() -> Path:
    p = Path(current_app.instance_path) / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def salvar(arquivo, prefixo: str, max_lado: int = 1200) -> str:
    """Valida e salva o upload. Retorna o nome do arquivo gerado."""
    if arquivo is None or not arquivo.filename:
        raise ErroImagem("Nenhum arquivo enviado.")
    dados = arquivo.read(TAMANHO_MAXIMO + 1)
    if len(dados) > TAMANHO_MAXIMO:
        raise ErroImagem("A imagem deve ter no máximo 5 MB.")
    try:
        import io
        img = Image.open(io.BytesIO(dados))
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
    nome = f"{prefixo}-{secrets.token_hex(12)}.png"
    img.save(pasta() / nome, "PNG", optimize=True)
    return nome


def caminho(nome: str | None) -> Path | None:
    if not nome or not RE_NOME.match(nome):
        return None
    p = pasta() / nome
    return p if p.exists() else None

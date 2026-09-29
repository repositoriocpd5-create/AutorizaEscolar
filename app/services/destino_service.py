"""Catálogo de destinos reaproveitáveis no cadastro de passeios."""
import re

from ..extensions import db
from ..models import DestinoSalvo


def normalizar(nome: str | None) -> str:
    """Gera uma chave estável, sem diferenças de caixa ou espaços extras."""
    return re.sub(r"\s+", " ", (nome or "").strip().lower())


def registrar(nome: str | None) -> DestinoSalvo | None:
    """Inclui o destino no catálogo ou registra mais um uso dele."""
    nome_limpo = re.sub(r"\s+", " ", (nome or "").strip())[:200]
    chave = normalizar(nome_limpo)
    if not chave:
        return None

    destino = DestinoSalvo.query.filter_by(nome_normalizado=chave).first()
    if destino is None:
        destino = DestinoSalvo(nome=nome_limpo, nome_normalizado=chave)
        db.session.add(destino)
    else:
        destino.usos += 1
    return destino


def listar(limite: int = 100) -> list[DestinoSalvo]:
    """Retorna os destinos mais utilizados e recentes para sugestão."""
    return (DestinoSalvo.query.order_by(
        DestinoSalvo.usos.desc(), DestinoSalvo.atualizado_em.desc(), DestinoSalvo.nome
    ).limit(limite).all())

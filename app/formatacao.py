"""Formatação de datas/horas no fuso local e rótulos de exibição."""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from flask import current_app

from .models import Situacao


def tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["TIMEZONE"])


def agora_local() -> datetime:
    """Horário local sem tzinfo (compatível com Passeio.data_limite)."""
    return datetime.now(tz()).replace(tzinfo=None)


def utc_para_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(tz()).replace(tzinfo=None)


def data_br(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        valor = valor.date()
    return valor.strftime("%d/%m/%Y")


def hora_br(valor: time | None) -> str:
    if valor is None:
        return ""
    return f"{valor.hour:02d}h{valor.minute:02d}"


def data_hora_utc_br(dt: datetime | None, segundos: bool = False) -> str:
    """Converte um datetime UTC gravado no banco para 'dd/mm/aaaa às hh:mm'."""
    local = utc_para_local(dt)
    if local is None:
        return ""
    return local.strftime("%d/%m/%Y às %H:%M" + (":%S" if segundos else ""))


def data_hora_local_br(dt: datetime | None) -> str:
    return dt.strftime("%d/%m/%Y às %H:%M") if dt else ""


def rotulo_situacao(situacao: str) -> str:
    return Situacao.ROTULOS.get(situacao, situacao)


def registrar_filtros(app) -> None:
    app.jinja_env.filters.update(
        data_br=data_br, hora_br=hora_br, data_hora_br=data_hora_utc_br,
        data_hora_local_br=data_hora_local_br, situacao=rotulo_situacao,
    )


def dia_semana(d: date) -> str:
    return ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"][d.weekday()]

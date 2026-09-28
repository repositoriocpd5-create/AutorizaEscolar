"""Geração do PDF comprobatório (A4) com QR Code de validação.

O PDF é gerado a partir de ``Documento.conteudo`` (fotografia imutável) em
modo determinístico (``invariant``): regenerá-lo produz exatamente os mesmos
bytes e, portanto, o mesmo hash SHA-256 registrado no banco.
"""
import hashlib
import io
from pathlib import Path
from xml.sax.saxutils import escape

from flask import current_app, request
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .. import audit
from ..extensions import db
from ..models import Documento, Situacao, utcnow

AZUL = colors.HexColor("#007AAD")
NAVY = colors.HexColor("#0C1D32")
CINZA = colors.HexColor("#5B6576")
CINZA_CLARO = colors.HexColor("#D9E2E9")
VERDE = colors.HexColor("#17823B")
VERMELHO = colors.HexColor("#B42318")

ROTULOS_PDF = {
    Situacao.AUTORIZADO: ("AUTORIZADO", "#17823B"),
    Situacao.NAO_AUTORIZADO: ("NÃO AUTORIZADO", "#B42318"),
    Situacao.CANCELADO: ("CANCELADO", "#B45309"),
}


def url_validacao(codigo: str) -> str:
    base = current_app.config["PUBLIC_BASE_URL"]
    if not base:
        try:
            base = request.host_url.rstrip("/")
        except RuntimeError:
            base = "http://localhost:5000"
    return f"{base}/validar/{codigo}"


def _logo(tamanho=16 * mm) -> Drawing:
    """Ícone institucional (livro aberto + telhado) desenhado em vetor."""
    d = Drawing(tamanho, tamanho)
    s = tamanho / 48.0
    d.add(Polygon([24 * s, 46 * s, 8 * s, 34 * s, 40 * s, 34 * s], fillColor=AZUL, strokeColor=None))
    d.add(Rect(4 * s, 4 * s, 19 * s, 26 * s, fillColor=AZUL, strokeColor=None))
    d.add(Rect(25 * s, 4 * s, 19 * s, 26 * s, fillColor=AZUL, strokeColor=None))
    for y in (22, 16, 10):
        d.add(Line(8 * s, y * s, 19 * s, y * s, strokeColor=colors.white, strokeWidth=1.4 * s))
        d.add(Line(29 * s, y * s, 40 * s, y * s, strokeColor=colors.white, strokeWidth=1.4 * s))
    return d


def _qr(conteudo: str, tamanho=32 * mm) -> Drawing:
    w = QrCodeWidget(conteudo, barLevel="M")
    x1, y1, x2, y2 = w.getBounds()
    d = Drawing(tamanho, tamanho, transform=[tamanho / (x2 - x1), 0, 0, tamanho / (y2 - y1), 0, 0])
    d.add(w)
    return d


def _estilos():
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13, textColor=colors.black)
    return {
        "inst": ParagraphStyle("inst", **{**base, "fontName": "Helvetica-Bold", "fontSize": 11, "textColor": AZUL}),
        "titulo": ParagraphStyle("titulo", **{**base, "fontName": "Helvetica-Bold", "fontSize": 13.5, "leading": 17}),
        "sub": ParagraphStyle("sub", **{**base, "fontName": "Helvetica-Bold", "fontSize": 11, "textColor": CINZA}),
        "secao": ParagraphStyle("secao", **{**base, "fontName": "Helvetica-Bold", "fontSize": 10,
                                            "textColor": AZUL, "spaceBefore": 10, "spaceAfter": 4}),
        "normal": ParagraphStyle("normal", **base),
        "pequeno": ParagraphStyle("pequeno", **{**base, "fontSize": 8.5, "leading": 11, "textColor": CINZA}),
        "celula": ParagraphStyle("celula", **{**base, "fontSize": 9, "leading": 11}),
        "codigo": ParagraphStyle("codigo", **{**base, "fontName": "Courier-Bold", "fontSize": 13, "leading": 16}),
        "centro": ParagraphStyle("centro", **{**base, "alignment": TA_CENTER, "fontSize": 8.5, "textColor": CINZA}),
    }


def _pares(rotulos_valores, st):
    linhas = [[Paragraph(f"<b>{r}</b>", st["normal"]), Paragraph(escape(v or "—"), st["normal"])]
              for r, v in rotulos_valores]
    t = Table(linhas, colWidths=[48 * mm, None])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


def renderizar_pdf(doc: Documento) -> bytes:
    c = doc.conteudo
    st = _estilos()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Autorização {doc.protocolo}", author=c["instituicao"], subject=c["passeio"]["nome"],
        creator="Sistema de Autorização de Alunos", invariant=1,
    )
    todos_aut = all(a["situacao"] == Situacao.AUTORIZADO for a in c["alunos"])
    el = []

    # Cabeçalho
    cab = Table([[_brasao(c.get("brasao")), [Paragraph(escape(c["instituicao"].upper()), st["inst"]),
                            Paragraph("AUTORIZAÇÃO PARA PASSEIO ESCOLAR" if todos_aut
                                      else "REGISTRO DE RESPOSTA — PASSEIO ESCOLAR", st["titulo"]),
                            Paragraph(escape(c["passeio"]["nome"].upper()), st["sub"])]]],
                colWidths=[24 * mm, None])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("LINEBELOW", (0, 0), (-1, 0), 1.2, AZUL),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    el += [cab, Spacer(1, 4)]

    el += [Paragraph("DADOS DO RESPONSÁVEL", st["secao"]),
           _pares([("Nome:", c["responsavel"]["nome"]), ("CPF:", c["responsavel"]["cpf_mascarado"])], st)]

    p = c["passeio"]
    info = [("Evento:", p["nome"]), ("Destino:", p["destino"]), ("Data:", p["data"]),
            ("Horário de saída:", p["hora_saida"]), ("Horário previsto de retorno:", p["hora_retorno"]),
            ("Local de saída:", p["local_saida"])]
    if p.get("transporte"):
        info.append(("Transporte:", p["transporte"]))
    el += [Paragraph("INFORMAÇÕES DO PASSEIO", st["secao"]), _pares(info, st)]

    # Tabela de alunos
    el.append(Paragraph("ALUNOS AUTORIZADOS" if todos_aut else "ALUNOS E RESPOSTAS", st["secao"]))
    linhas = [[Paragraph(f"<b>{h}</b>", st["celula"]) for h in ("Aluno", "Ano/Turma", "Escola", "Situação")]]
    estilo_tab = [("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#9AA4B2")),
                  ("BACKGROUND", (0, 0), (-1, 0), CINZA_CLARO), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for i, a in enumerate(c["alunos"], start=1):
        rot, cor = ROTULOS_PDF.get(a["situacao"], (a["situacao"], "#0C1D32"))
        linhas.append([Paragraph(escape(a["nome"]), st["celula"]), Paragraph(escape(a["turma"]), st["celula"]),
                       Paragraph(escape(a["escola"]), st["celula"]),
                       Paragraph(f'<font color="{cor}"><b>{rot}</b></font>',
                                 st["celula"])])
    tab = Table(linhas, colWidths=[52 * mm, 34 * mm, 52 * mm, 36 * mm], repeatRows=1)
    tab.setStyle(TableStyle(estilo_tab))
    el += [tab, Spacer(1, 8)]

    declaracao = c["declaracao"]
    if not todos_aut:
        declaracao = ("Declaro, na condição de responsável legal, que registro as respostas acima para o(s) "
                      "aluno(s) identificado(s) neste documento em relação ao passeio escolar descrito, "
                      "estando ciente das informações, horários e condições apresentadas pela unidade escolar.")
    el += [Paragraph(escape(declaracao), st["normal"]),
           Paragraph(f"Versão do texto de autorização: v{c['versao_texto']}", st["pequeno"])]

    # Registro eletrônico + QR Code
    reg = c["registro"]
    bloco = [
        Paragraph("REGISTRO ELETRÔNICO", st["secao"]),
        Paragraph("Manifestação de consentimento registrada eletronicamente pelo responsável.", st["normal"]),
        Spacer(1, 3),
        _pares([("Responsável:", c["responsavel"]["nome"]), ("Data:", reg["data"]),
                ("Hora:", reg["hora"]), ("Protocolo:", doc.protocolo)], st),
        Spacer(1, 4),
        Paragraph("Código de validação:", st["normal"]),
        Paragraph(doc.codigo_validacao, st["codigo"]),
    ]
    url = c.get("url_validacao") or url_validacao(doc.codigo_validacao)
    reg_tab = Table([[bloco, _qr(url)]], colWidths=[None, 36 * mm])
    reg_tab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                                 ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#C9D2DE")),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    el += [Spacer(1, 8), KeepTogether([reg_tab, Spacer(1, 6), Paragraph(
        "A autenticidade deste documento poderá ser verificada por meio do QR Code ou do código de "
        f"validação em {url.rsplit('/', 1)[0]}.", st["centro"])])]

    pdf.build(el)
    return buf.getvalue()


def _caminho(doc: Documento) -> Path:
    pasta = Path(current_app.config["DOCUMENTOS_DIR"])
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / f"{doc.public_id}.pdf"


def gerar_e_salvar(doc: Documento) -> bytes:
    dados = renderizar_pdf(doc)
    caminho = _caminho(doc)
    caminho.write_bytes(dados)
    doc.arquivo = caminho.name
    doc.hash_sha256 = hashlib.sha256(dados).hexdigest()
    doc.data_geracao = utcnow()
    audit.registrar(audit.Acao.PDF_GERADO, "SISTEMA", alvo=f"documento:{doc.public_id}",
                    detalhes={"protocolo": doc.protocolo, "sha256": doc.hash_sha256}, commit=False)
    db.session.commit()
    return dados


def obter_pdf(doc: Documento) -> bytes:
    """Lê o arquivo; se ausente ou divergente do hash, regenera a partir da fotografia."""
    caminho = _caminho(doc)
    if doc.hash_sha256 and caminho.exists():
        dados = caminho.read_bytes()
        if hashlib.sha256(dados).hexdigest() == doc.hash_sha256:
            return dados
        current_app.logger.warning("Hash divergente para %s; regenerando.", doc.protocolo)
    if doc.hash_sha256:
        dados = renderizar_pdf(doc)
        if hashlib.sha256(dados).hexdigest() != doc.hash_sha256:
            current_app.logger.error("PDF regenerado difere do hash original: %s", doc.protocolo)
        caminho.write_bytes(dados)
        return dados
    return gerar_e_salvar(doc)


def _brasao(nome_upload=None, largura=19 * mm):
    """Brasão configurado no painel (fotografado no documento) ou o padrão do sistema."""
    from reportlab.lib.utils import ImageReader
    from .midia_service import caminho as caminho_upload
    caminho = caminho_upload(nome_upload) or Path(current_app.static_folder) / "img" / "brasao-512.png"
    if not caminho.exists():
        return _logo()
    w, h = ImageReader(str(caminho)).getSize()
    altura = largura * h / w
    if altura > 24 * mm:  # imagens muito altas
        largura, altura = largura * 24 * mm / altura, 24 * mm
    return Image(str(caminho), width=largura, height=altura)

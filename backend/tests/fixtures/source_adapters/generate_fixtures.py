"""生成 TXT/DOCX 解析器的纯合成 fixtures；全部为手写虚构内容，不含真实用户材料。

运行：
    & backend/.venv/Scripts/python.exe -X utf8 backend/tests/fixtures/source_adapters/generate_fixtures.py

生成物与 backend/tests/test_txt_adapter.py、test_docx_adapter.py 的期望值一一对应；
重跑可复现（ZIP 时间戳固定为 2026-01-01）。同目录 .gitattributes 禁用行尾归一化，
保证 CRLF/BOM 等字节精确进入版本库。
"""
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml"'
    ' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1"'
    ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
    ' Target="word/document.xml"/>'
    "</Relationships>"
)


def _document(*body_children: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" xmlns:wp="{WP_NS}" xmlns:a="{A_NS}" xmlns:wps="{WPS_NS}">'
        "<w:body>" + "".join(body_children) + "<w:sectPr/></w:body></w:document>"
    )


def _p(*runs: str, style: str | None = None) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}{''.join(runs)}</w:p>"


def _r(*items: str) -> str:
    return "<w:r>" + "".join(items) + "</w:r>"


def _t(text: str) -> str:
    return f'<w:t xml:space="preserve">{text}</w:t>'


def _tr(*cells: str) -> str:
    return "<w:tr>" + "".join(cells) + "</w:tr>"


def _tc(*blocks: str, properties: str = "") -> str:
    return f"<w:tc>{properties}" + "".join(blocks) + "</w:tc>"


def _tbl(*rows: str) -> str:
    return "<w:tbl>" + "".join(rows) + "</w:tbl>"


def _write_package(filename: str, document_xml: str, extra_parts: dict[str, str] | None = None) -> None:
    parts = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/document.xml": document_xml,
        **(extra_parts or {}),
    }
    with zipfile.ZipFile(HERE / filename, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)


def main() -> None:
    # TXT：BOM + CRLF + 空行 + 纯空格行 + Tab + 中文。
    (HERE / "txt_lines_bom_crlf_cn.txt").write_bytes(
        b"\xef\xbb\xbf" + "标题行\r\n\r\n   \r\n第三行\t带tab\r\n".encode("utf-8")
    )
    # TXT：LF + 尾随空格 + 末尾换行。
    (HERE / "txt_lines_lf_plain.txt").write_bytes("alpha\n\nbeta \n".encode("utf-8"))

    # DOCX：正文—表格—正文，run 合并，中文。
    body_table_body = _document(
        _p(_r(_t("正文")), _r(_t("第一段"))),
        _tbl(
            _tr(_tc(_p(_r(_t("甲组数据")))), _tc(_p(_r(_t("重复")), _r(_t("项"))))),
            _tr(_tc(_p(_r(_t("乙组数据")))), _tc(_p())),
        ),
        _p(_r(_t("结语段落"))),
    )
    _write_package("docx_body_table_body.docx", body_table_body)

    # DOCX：标题段落与正文段落。
    _write_package(
        "docx_headings_chinese.docx",
        _document(
            _p(_r(_t("第一章 项目概况")), style="Heading1"),
            _p(_r(_t("普通正文。"))),
            _p(_r(_t("1.1 目标")), style="Heading2"),
        ),
    )

    # DOCX：单元格多段落、空段落、空单元格、同格重复文本。
    _write_package(
        "docx_cell_multi_paragraph.docx",
        _document(
            _tbl(
                _tr(
                    _tc(_p(_r(_t("单元格第一段"))), _p(), _p(_r(_t("单元格第三段")))),
                    _tc(_p()),
                    _tc(_p(_r(_t("重复项"))), _p(_r(_t("重复项")))),
                )
            )
        ),
    )

    # DOCX：正文、表格、表格内出现相同文本，结构位置不同。
    _write_package(
        "docx_repeated_text.docx",
        _document(
            _p(_r(_t("同一句文本"))),
            _p(_r(_t("同一句文本"))),
            _tbl(_tr(_tc(_p(_r(_t("同一句文本")))))),
        ),
    )

    # DOCX：真实 tab/换行，纯空格段落保留。
    _write_package(
        "docx_tab_break_runs.docx",
        _document(
            _p(_r(_t("制表")), _r("<w:tab/>", _t("后")), _r("<w:br/>", _t("换行后中文"))),
            _p(_r(_t(" "))),
        ),
    )

    # DOCX：空 body（空段落占号但不产节点）。
    _write_package("docx_empty_body.docx", _document(_p(), _p(style="Heading1")))

    # DOCX：页眉有文字但不应进入正文节点。
    _write_package(
        "docx_header_ignored.docx",
        _document(_p(_r(_t("正文唯一段落")))),
        extra_parts={
            "word/header1.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:hdr xmlns:w="{W_NS}">{_p(_r(_t("页眉文字")))}</w:hdr>'
            )
        },
    )

    # 拒绝用例：合并单元格（gridSpan）。
    _write_package(
        "reject_merged_cells.docx",
        _document(
            _tbl(
                _tr(
                    _tc(_p(_r(_t("合并"))), properties='<w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'),
                    _tc(_p(_r(_t("尾列")))),
                )
            )
        ),
    )

    # 拒绝用例：嵌套表格。
    nested = _tbl(_tr(_tc(_p(_r(_t("内层单元格"))))))
    _write_package(
        "reject_nested_table.docx",
        _document(_tbl(_tr(_tc(_p(_r(_t("外层段落"))), nested)))),
    )

    # 拒绝用例：body 级内容控件（w:sdt）。
    _write_package(
        "reject_content_control.docx",
        _document(
            _p(_r(_t("前"))),
            "<w:sdt><w:sdtPr/><w:sdtContent>" + _p(_r(_t("控件内文字"))) + "</w:sdtContent></w:sdt>",
            _p(_r(_t("后"))),
        ),
    )

    # 拒绝用例：文本框文字。
    text_box = (
        "<w:p><w:r><w:drawing><wp:inline><a:graphic><a:graphicData>"
        "<wps:wsp><wps:txbx><w:txbxContent>"
        + _p(_r(_t("框内文字")))
        + "</w:txbxContent></wps:txbx></wps:wsp>"
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )
    _write_package("reject_text_box.docx", _document(text_box))

    # 拒绝用例：不是 ZIP 的文件。
    (HERE / "reject_broken_zip.docx").write_bytes(b"this is not a zip archive")

    # 拒绝用例：ZIP 合法但 XML 损坏。
    _write_package("reject_bad_xml.docx", f'<w:document xmlns:w="{W_NS}"><w:body><w:p>')

    # 拒绝用例：缺少 word/document.xml。
    with zipfile.ZipFile(HERE / "reject_missing_document.docx", "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("[Content_Types].xml", date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(info, CONTENT_TYPES)


if __name__ == "__main__":
    main()
    print(f"fixtures written to {HERE}")

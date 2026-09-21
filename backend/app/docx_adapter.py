"""纯 DOCX 解析：标准库 ZIP + XML，按 document body 顺序产出文本节点。

冻结规则：
- 只读 word/document.xml；不访问关系、页眉页脚、图片、文本框或任何外部资源。
- body 子元素按文档顺序遍历：w:p 计入 paragraph_index，w:tbl 计入 table_index；
  表内 row/cell 一基，cell 内 w:p 计入 cell_paragraph_index（含空段落占号）。
- 一个段落合并全部 run 为一段文本；w:tab→"\\t"，w:br/w:cr→"\\n"；
  修订删除（w:del/w:moveFrom）的文本不并入正文。
- 合并单元格、嵌套表格、内容控件、文本框、altChunk 等不能准确定位的结构明确拒绝，
  不静默展开为普通结构，也不把图片文字/页眉页脚冒充已解析正文。
- 损坏 ZIP/XML、解压超限、缺少 document.xml 明确失败；错误码见 source_adapters。
"""
import io
import zipfile
import zlib
import xml.etree.ElementTree as ET

from .source_adapters import (
    DOCX_PARSER_VERSION,
    MAX_DOCX_ENTRY_BYTES,
    MAX_DOCX_TOTAL_BYTES,
    ParsedSource,
    SourceNode,
    SourceParseError,
)

DOCUMENT_PATH = "word/document.xml"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_IGNORED_MARKERS = frozenset(
    {
        "bookmarkStart",
        "bookmarkEnd",
        "commentRangeStart",
        "commentRangeEnd",
        "permStart",
        "permEnd",
        "proofErr",
    }
)
_IGNORED_BODY_CHILDREN = _IGNORED_MARKERS | {"sectPr"}
_IGNORED_TABLE_CHILDREN = _IGNORED_MARKERS | {"tblPr", "tblGrid", "tblPrEx"}
_IGNORED_ROW_CHILDREN = _IGNORED_MARKERS | {"trPr"}
_IGNORED_CELL_CHILDREN = _IGNORED_MARKERS | {"tcPr"}


def _tag(name: str) -> str:
    return f"{{{WORD_NS}}}{name}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_docx(data: bytes) -> ParsedSource:
    """把 DOCX 字节转成正文顺序文本节点；失败抛 SourceParseError。"""
    root = _parse_document_xml(_read_document_xml(data))
    if root.tag != _tag("document"):
        raise SourceParseError(
            "invalid_docx",
            "word/document.xml 不是 WordprocessingML 文档",
            [f"根元素：{_local(root.tag)}"],
        )
    body = root.find(_tag("body"))
    if body is None:
        raise SourceParseError("invalid_docx", "DOCX 缺少 w:body", [])

    nodes: list[SourceNode] = []
    paragraph_index = 0
    table_index = 0
    for child in body:
        name = _local(child.tag)
        if name == "p":
            paragraph_index += 1
            text = _paragraph_text(child, f"正文段落 {paragraph_index}")
            if text:
                nodes.append(
                    SourceNode(
                        kind="paragraph",
                        text=text,
                        body_ordinal=len(nodes),
                        paragraph_index=paragraph_index,
                    )
                )
        elif name == "tbl":
            table_index += 1
            _collect_table(child, table_index, nodes)
        elif name in _IGNORED_BODY_CHILDREN:
            continue
        else:
            raise SourceParseError(
                "unsupported_structure",
                f"正文含不支持的 w:{name}",
                [f"位置：正文第 {len(nodes)} 个输出节点之后", "不支持的正文结构不会被静默跳过"],
            )

    return ParsedSource(
        format="docx",
        parser_version=DOCX_PARSER_VERSION,
        nodes=tuple(nodes),
        line_count=None,
    )


def _read_document_xml(data: bytes) -> bytes:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SourceParseError("invalid_zip", "不是有效的 DOCX（ZIP）文件", [str(exc)]) from exc

    with archive:
        infos = archive.infolist()
        encrypted = [info.filename for info in infos if info.flag_bits & 0x1]
        if encrypted:
            raise SourceParseError("invalid_zip", "不支持加密的 DOCX", encrypted)
        names = [info.filename for info in infos]
        if names.count(DOCUMENT_PATH) > 1:
            raise SourceParseError("invalid_zip", "DOCX 含重复的 word/document.xml", [])
        total_bytes = sum(info.file_size for info in infos)
        if total_bytes > MAX_DOCX_TOTAL_BYTES:
            raise SourceParseError(
                "archive_too_large",
                "DOCX 解压后总体积超过解析上限",
                [
                    f"解压总量 {total_bytes} 字节，上限 {MAX_DOCX_TOTAL_BYTES} 字节",
                    "上限为解析器临时安全值，待与 API 输入门对齐后调整",
                ],
            )
        try:
            document_info = archive.getinfo(DOCUMENT_PATH)
        except KeyError as exc:
            raise SourceParseError(
                "invalid_docx",
                "DOCX 缺少 word/document.xml；只接受 WordprocessingML 文档（旧 .doc 等格式不支持）",
                [],
            ) from exc
        if document_info.file_size > MAX_DOCX_ENTRY_BYTES:
            raise SourceParseError(
                "archive_too_large",
                "word/document.xml 解压后超过解析上限",
                [
                    f"解压体积 {document_info.file_size} 字节，上限 {MAX_DOCX_ENTRY_BYTES} 字节",
                    "上限为解析器临时安全值，待与 API 输入门对齐后调整",
                ],
            )
        try:
            return archive.read(document_info)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as exc:
            raise SourceParseError("invalid_zip", "DOCX 解压失败", [str(exc)]) from exc


def _parse_document_xml(document_xml: bytes) -> ET.Element:
    try:
        return ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise SourceParseError("invalid_xml", "word/document.xml 不是有效 XML", [str(exc)]) from exc


def _collect_table(table: ET.Element, table_index: int, nodes: list[SourceNode]) -> None:
    row_index = 0
    for child in table:
        name = _local(child.tag)
        if name == "tr":
            row_index += 1
            _collect_row(child, table_index, row_index, nodes)
        elif name in _IGNORED_TABLE_CHILDREN:
            continue
        else:
            raise SourceParseError(
                "unsupported_structure",
                f"表格 {table_index} 含不支持的 w:{name}",
                ["表格只支持 w:tr 行结构"],
            )


def _collect_row(row: ET.Element, table_index: int, row_index: int, nodes: list[SourceNode]) -> None:
    cell_index = 0
    for child in row:
        name = _local(child.tag)
        if name == "tc":
            cell_index += 1
            _collect_cell(child, table_index, row_index, cell_index, nodes)
        elif name in _IGNORED_ROW_CHILDREN:
            continue
        else:
            raise SourceParseError(
                "unsupported_structure",
                f"表格 {table_index} 第 {row_index} 行含不支持的 w:{name}",
                ["行只支持 w:tc 单元格结构"],
            )


def _collect_cell(
    cell: ET.Element,
    table_index: int,
    row_index: int,
    cell_index: int,
    nodes: list[SourceNode],
) -> None:
    _reject_merged_cell(cell, table_index, row_index, cell_index)
    cell_paragraph_index = 0
    for child in cell:
        name = _local(child.tag)
        if name == "p":
            cell_paragraph_index += 1
            text = _paragraph_text(
                child,
                f"表格 {table_index} 第 {row_index} 行第 {cell_index} 列段落 {cell_paragraph_index}",
            )
            if text:
                nodes.append(
                    SourceNode(
                        kind="table_cell",
                        text=text,
                        body_ordinal=len(nodes),
                        table_index=table_index,
                        row_index=row_index,
                        cell_index=cell_index,
                        cell_paragraph_index=cell_paragraph_index,
                    )
                )
        elif name == "tbl":
            raise SourceParseError(
                "unsupported_structure",
                f"表格 {table_index} 第 {row_index} 行第 {cell_index} 列含嵌套表格，不能准确表达",
                ["嵌套表格不会被静默展开为普通单元格"],
            )
        elif name in _IGNORED_CELL_CHILDREN:
            continue
        else:
            raise SourceParseError(
                "unsupported_structure",
                f"表格 {table_index} 第 {row_index} 行第 {cell_index} 列含不支持的 w:{name}",
                ["单元格只支持 w:p 段落与 w:tcPr 属性"],
            )


def _reject_merged_cell(cell: ET.Element, table_index: int, row_index: int, cell_index: int) -> None:
    properties = cell.find(_tag("tcPr"))
    if properties is None:
        return
    marks: list[str] = []
    for child in properties:
        name = _local(child.tag)
        if name == "gridSpan":
            marks.append(f"gridSpan={child.get(_tag('val'), '?')}")
        elif name in ("vMerge", "hMerge"):
            marks.append(f"{name}={child.get(_tag('val')) or 'continue'}")
    if marks:
        raise SourceParseError(
            "unsupported_structure",
            f"表格 {table_index} 第 {row_index} 行第 {cell_index} 列是合并单元格（{', '.join(marks)}），不能准确定位",
            ["合并单元格不会被静默展开为普通单元格"],
        )


def _paragraph_text(paragraph: ET.Element, position: str) -> str:
    parts: list[str] = []

    def walk(element: ET.Element) -> None:
        for child in element:
            name = _local(child.tag)
            if name in ("del", "moveFrom"):
                continue  # 修订删除/移走的文本不属于最终正文
            if name == "t":
                parts.append(child.text or "")
            elif name == "tab":
                parts.append("\t")
            elif name in ("br", "cr"):
                parts.append("\n")
            elif name == "txbxContent":
                raise SourceParseError(
                    "unsupported_structure",
                    f"{position} 含文本框文字，无法给出稳定的段落位置",
                    ["文本框内容不会被静默并入正文"],
                )
            else:
                walk(child)

    walk(paragraph)
    return "".join(parts)

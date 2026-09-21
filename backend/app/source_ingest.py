"""通用来源解析边界：消费 B2 纯 parser，转换成公共 Block/Locator。

B2 接口（不依赖公共 contracts，本模块不修改其实现）：
- app.txt_adapter.parse_txt(data) -> ParsedSource
- app.docx_adapter.parse_docx(data) -> ParsedSource
- app.source_adapters：ParsedSource(format/parser_version/nodes/line_count)、
  SourceNode(kind/text/body_ordinal + 结构坐标)、SourceParseError(code/message/details)。

本模块职责：
- 按扩展名选择 parser：md 走冻结的行解析（与旧 Markdown 语义一致），txt/docx 走 B2；
- SourceNode → 公共 Block：body_ordinal 零基连续直接作为 Block.ordinal（保持 parser 结构语义，
  不重新编号、不按 line_number 排序），结构位置原样映射到 Locator：
  line_index→index，paragraph_index→index，
  table_index/row_index/cell_index/cell_paragraph_index→index/row_index/cell_index/paragraph_index；
- 非行来源 line_count 保持 null（TXT 给真实行数，DOCX 为 None）；
- parser 的 SourceParseError 统一转成 400 PreviewRejected（错误码原样透出，不静默降级）。

解析拒绝（合并单元格/嵌套表格/内容控件/文本框/损坏 ZIP/XML 等）完全由 B2 parser 决定，
本层不扩大也不收窄 DOCX 支持范围。
"""
import hashlib
from collections.abc import Sequence

from .contracts import Block, Locator, SourcePreview
from .docx_adapter import parse_docx
from .markdown_preview import (
    MAX_BYTES,
    TEMPORARY_DOCUMENT_ID,
    PreviewRejected,
    decode_markdown,
    split_lines,
)
from .source_adapters import ParsedSource, SourceNode, SourceParseError
from .txt_adapter import parse_txt

PARSER_VERSION_LINE = "line-v1"


def detect_format(filename: str) -> str:
    lower = filename.lower()
    for extension, fmt in ((".md", "md"), (".txt", "txt"), (".docx", "docx")):
        if lower.endswith(extension):
            return fmt
    raise PreviewRejected(
        "invalid_extension", "只支持 .md/.txt/.docx 文件", [f"收到：{filename or '空文件名'}"]
    )


def _invalid_node(message: str, details: list[str] | None = None) -> PreviewRejected:
    return PreviewRejected("invalid_source_node", message, details or [])


def locator_from_node(node: SourceNode) -> Locator:
    """SourceNode 结构位置 → 公共 Locator；坐标缺失/越界即拒绝整份解析。"""
    if node.kind == "line":
        if node.line_index is None or node.line_index < 1:
            raise _invalid_node("line 节点缺少一基 line_index", [f"body_ordinal={node.body_ordinal}"])
        return Locator(kind="line", index=node.line_index, end_index=None, block_index=1)
    if node.kind == "paragraph":
        if node.paragraph_index is None or node.paragraph_index < 1:
            raise _invalid_node(
                "paragraph 节点缺少一基 paragraph_index", [f"body_ordinal={node.body_ordinal}"]
            )
        return Locator(kind="paragraph", index=node.paragraph_index, end_index=None, block_index=1)
    if node.kind == "table_cell":
        coordinates = (node.table_index, node.row_index, node.cell_index, node.cell_paragraph_index)
        if any(value is None or value < 1 for value in coordinates):
            raise _invalid_node(
                "table_cell 节点缺少完整的一基 table/row/cell/cell_paragraph 坐标",
                [f"body_ordinal={node.body_ordinal}"],
            )
        return Locator(
            kind="table_cell",
            index=node.table_index,
            end_index=None,
            block_index=1,
            row_index=node.row_index,
            cell_index=node.cell_index,
            paragraph_index=node.cell_paragraph_index,
        )
    raise _invalid_node(f"未知 SourceNode.kind：{node.kind}", [f"body_ordinal={node.body_ordinal}"])


def blocks_from_nodes(nodes: Sequence[SourceNode]) -> list[Block]:
    """保持 parser 的正文顺序与结构语义：body_ordinal 零基连续 → Block.ordinal。"""
    blocks: list[Block] = []
    for index, node in enumerate(nodes):
        if node.body_ordinal != index:
            raise _invalid_node(
                "parser 输出的 body_ordinal 必须零基连续",
                [f"位置 {index} 收到 body_ordinal={node.body_ordinal}"],
            )
        if node.text == "":
            raise _invalid_node("parser 不应输出空文本节点", [f"body_ordinal={node.body_ordinal}"])
        blocks.append(
            Block(
                id=f"{TEMPORARY_DOCUMENT_ID}-block-{index}",
                document_id=TEMPORARY_DOCUMENT_ID,
                ordinal=index,
                text=node.text,
                locator=locator_from_node(node),
            )
        )
    return blocks


def _run_b2_parser(fmt: str, data: bytes) -> ParsedSource:
    """把 B2 的 SourceParseError 原码转成 400 PreviewRejected；不吞错、不降级。"""
    try:
        return parse_txt(data) if fmt == "txt" else parse_docx(data)
    except SourceParseError as exc:
        raise PreviewRejected(exc.code, exc.message, exc.details) from exc


def _markdown_nodes(text: str) -> list[SourceNode]:
    """md 行节点：冻结的 Markdown 行规则，空行不产节点但计入 line_count。"""
    nodes: list[SourceNode] = []
    for line_index, line in enumerate(split_lines(text), start=1):
        if line == "":
            continue
        nodes.append(
            SourceNode(kind="line", text=line, body_ordinal=len(nodes), line_index=line_index)
        )
    return nodes


def build_source_preview(filename: str, data: bytes) -> SourcePreview:
    """通用预览：md 走冻结行解析，txt/docx 走 B2 parser；不保存、不渲染。"""
    fmt = detect_format(filename)
    if len(data) > MAX_BYTES:
        raise PreviewRejected("file_too_large", "文件超过 1 MiB 上限", [f"收到 {len(data)} 字节"])

    if fmt == "md":
        decoded = decode_markdown(data)
        nodes = _markdown_nodes(decoded)
        line_count: int | None = len(split_lines(decoded))
        parser_version = PARSER_VERSION_LINE
    else:
        parsed = _run_b2_parser(fmt, data)
        nodes = list(parsed.nodes)
        line_count = parsed.line_count
        parser_version = parsed.parser_version

    return SourcePreview(
        document_id=TEMPORARY_DOCUMENT_ID,
        filename=filename,
        format=fmt,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        line_count=line_count,
        parser_version=parser_version,
        blocks=blocks_from_nodes(nodes),
    )

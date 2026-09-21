"""通用来源解析边界：md/txt 行解析 + B2 SourceNode → 公共 Block/Locator 转换。

B2 交付纯 SourceNode（不依赖公共 contracts）：text、body_ordinal；位置三选一——
line；paragraph；或 table/row/cell/cell_paragraph。本模块负责：
- 把节点按 body_ordinal 顺序转成公共 Block，并分配 Block.ordinal（0 起连续）与临时身份；
- line → Locator(kind="line")，paragraph → Locator(kind="paragraph")，
  table → Locator(kind="table_cell", index=table, row_index, cell_index, paragraph_index)；
- 非行格式的 line_count 为 null，绝不用 index 冒充行号。

DOCX 解析属于 B2 adapter；adapter 未落地时抛 ParserUnavailable（400 parser_unavailable），
不伪造 Block、不静默截断。旧的 `.md` 预览入口仍走 markdown_preview.build_preview，语义不变。
"""
import hashlib
from dataclasses import dataclass

from .contracts import Block, Locator, SourcePreview
from .markdown_preview import (
    MAX_BYTES,
    TEMPORARY_DOCUMENT_ID,
    PreviewRejected,
    decode_markdown,
    split_lines,
    validate_filename,
)

PARSER_VERSION_LINE = "line-v1"
PARSER_VERSION_B2 = "b2-source-nodes-v1"

SUPPORTED_FORMATS = ("md", "txt", "docx")


class ParserUnavailable(PreviewRejected):
    """格式已识别但对应 parser 不可用（当前只有 DOCX 等待 B2 adapter）。"""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__("parser_unavailable", message, details)


@dataclass(frozen=True)
class SourceNode:
    """B2 纯节点形状的本地镜像；也可由内置行解析生成，测试可注入。"""

    text: str
    body_ordinal: int
    line: int | None = None
    paragraph: int | None = None
    table: int | None = None
    row: int | None = None
    cell: int | None = None
    cell_paragraph: int | None = None


def detect_format(filename: str) -> str:
    lower = filename.lower()
    for extension, fmt in ((".md", "md"), (".txt", "txt"), (".docx", "docx")):
        if lower.endswith(extension):
            return fmt
    raise PreviewRejected(
        "invalid_extension", "只支持 .md/.txt/.docx 文件", [f"收到：{filename or '空文件名'}"]
    )


def line_nodes(text: str) -> list[SourceNode]:
    """真实逐行节点：空行不生成节点但计入 line_count；只含空格/Tab 的行不是空行。"""
    nodes: list[SourceNode] = []
    for line_number, line in enumerate(split_lines(text), start=1):
        if line == "":
            continue
        nodes.append(SourceNode(text=line, body_ordinal=len(nodes), line=line_number))
    return nodes


def locator_from_node(node: SourceNode) -> Locator:
    """节点位置 → 公共 Locator；位置形式必须唯一，否则拒绝整份解析。"""
    has_line = node.line is not None
    has_paragraph = node.paragraph is not None
    has_table = node.table is not None
    if sum((has_line, has_paragraph, has_table)) != 1:
        raise PreviewRejected(
            "invalid_source_node",
            "SourceNode 必须且只能提供 line / paragraph / table 中的一种位置",
            [f"body_ordinal={node.body_ordinal}"],
        )
    if has_line:
        if node.line < 1:
            raise PreviewRejected("invalid_source_node", "line 必须从 1 开始", [f"line={node.line}"])
        return Locator(kind="line", index=node.line, end_index=None, block_index=1)
    if has_paragraph:
        if node.paragraph < 1:
            raise PreviewRejected(
                "invalid_source_node", "paragraph 必须从 1 开始", [f"paragraph={node.paragraph}"]
            )
        return Locator(kind="paragraph", index=node.paragraph, end_index=None, block_index=1)
    if node.row is None or node.cell is None or node.cell_paragraph is None:
        raise PreviewRejected(
            "invalid_source_node",
            "table_cell 节点必须同时提供 row/cell/cell_paragraph",
            [f"body_ordinal={node.body_ordinal}"],
        )
    if min(node.table, node.row, node.cell, node.cell_paragraph) < 1:
        raise PreviewRejected(
            "invalid_source_node", "表格结构序号必须从 1 开始", [f"table={node.table}"]
        )
    return Locator(
        kind="table_cell",
        index=node.table,
        end_index=None,
        block_index=1,
        row_index=node.row,
        cell_index=node.cell,
        paragraph_index=node.cell_paragraph,
    )


def blocks_from_nodes(nodes: list[SourceNode]) -> list[Block]:
    """按 body_ordinal 排定正文顺序，重新分配 0 起连续的 Block.ordinal；空文本节点跳过。"""
    ordered = sorted(nodes, key=lambda node: node.body_ordinal)
    ordinals = [node.body_ordinal for node in ordered]
    if len(set(ordinals)) != len(ordinals):
        raise PreviewRejected("invalid_source_node", "body_ordinal 必须唯一", [])
    blocks: list[Block] = []
    for node in ordered:
        if node.text == "":
            continue
        ordinal = len(blocks)
        blocks.append(
            Block(
                id=f"{TEMPORARY_DOCUMENT_ID}-block-{ordinal}",
                document_id=TEMPORARY_DOCUMENT_ID,
                ordinal=ordinal,
                text=node.text,
                locator=locator_from_node(node),
            )
        )
    return blocks


def _b2_source_adapter():
    """延迟导入 B2 模块；不存在时返回 None（不抛 ImportError 到调用方）。"""
    try:
        from . import source_adapters  # type: ignore[attr-defined]
    except ImportError:
        return None
    return source_adapters


def _parse_with_b2(filename: str, data: bytes) -> tuple[list[SourceNode], str]:
    adapter = _b2_source_adapter()
    if adapter is None:
        raise ParserUnavailable(
            "DOCX parser 尚未集成（等待 B2 source adapter）", [f"filename={filename}"]
        )
    parse = getattr(adapter, "read_source_nodes", None)
    if parse is None:
        raise ParserUnavailable(
            "B2 source adapter 未提供 read_source_nodes(filename, data) 接口",
            [f"filename={filename}"],
        )
    nodes = parse(filename, data)
    return list(nodes), getattr(adapter, "PARSER_VERSION", PARSER_VERSION_B2)


def build_source_preview(filename: str, data: bytes) -> SourcePreview:
    """通用预览：按扩展名解析；不保存、不渲染。失败抛 PreviewRejected。"""
    fmt = detect_format(filename)
    if len(data) > MAX_BYTES:
        raise PreviewRejected("file_too_large", "文件超过 1 MiB 上限", [f"收到 {len(data)} 字节"])

    line_count: int | None = None
    if fmt == "docx":
        nodes, parser_version = _parse_with_b2(filename, data)
    else:
        decoded = decode_markdown(data)
        nodes = line_nodes(decoded)
        line_count = len(split_lines(decoded))
        parser_version = PARSER_VERSION_LINE

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


def build_markdown_preview(filename: str, data: bytes):
    """旧 `.md` 入口：仍走冻结的行解析实现，保证历史 wire 值不变。"""
    from .markdown_preview import build_preview

    validate_filename(filename)
    return build_preview(filename, data)

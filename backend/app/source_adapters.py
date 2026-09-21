"""TXT/DOCX 纯解析的内部节点协议；不导入 contracts/storage/main，不做任何 IO。

定位语义（与 B 的接口约定；结构位置全部一基）：
- line：line_index 是原始行号；空行不产节点但照常占行号。
- paragraph：paragraph_index 只数 body 直接段落；标题段落同样是段落。
- table_cell：table_index 数 body 直接表格，row_index/cell_index 表内一基，
  cell_paragraph_index 数该单元格内的段落（含空段落）。
- body_ordinal 零基连续，只按输出文本节点递增，与结构位置解耦；
  空段落/空单元格不产节点，但结构位置计数不被挤掉。
- 解析结果没有数据库 ID、没有公开 Block；由调用方映射为 API/契约对象。
"""
from dataclasses import dataclass
from typing import Literal

SourceFormat = Literal["txt", "docx"]
SourceKind = Literal["line", "paragraph", "table_cell"]

TXT_PARSER_VERSION = "txt/1"
DOCX_PARSER_VERSION = "docx/1"

# DOCX 解压安全上限：解析器自身防线，不是产品上传限制；待与 API 输入门对齐后调整。
MAX_DOCX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_DOCX_ENTRY_BYTES = 32 * 1024 * 1024

# SourceParseError.code 取值（由 B 映射为 API 错误）：
#   invalid_encoding / invalid_zip / invalid_xml / invalid_docx /
#   unsupported_structure / archive_too_large
ERROR_CODES = (
    "invalid_encoding",
    "invalid_zip",
    "invalid_xml",
    "invalid_docx",
    "unsupported_structure",
    "archive_too_large",
)


class SourceParseError(Exception):
    """解析拒绝；code 由调用方映射为 API 错误。"""

    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = list(details or [])
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class SourceNode:
    """一个可转成 Block 的文本节点；位置字段按 kind 使用，其余为 None。"""

    kind: SourceKind
    text: str
    body_ordinal: int
    line_index: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    cell_paragraph_index: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """一次纯解析的结果；TXT 给出真实行数，DOCX 的行数为 None。"""

    format: SourceFormat
    parser_version: str
    nodes: tuple[SourceNode, ...]
    line_count: int | None

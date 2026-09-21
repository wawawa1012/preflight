"""纯 TXT 解析：UTF-8（允许 BOM），行规则与 markdown_preview 冻结规则一致。

- 空行（去掉 LF/CRLF 后长度为 0）不产节点但计入行号；纯空格/Tab 行产节点。
- 行内容原样保留（含行首、行尾空格与 Tab），只去掉行终止符；LF 与 CRLF 都支持。
- UTF-8 BOM 合法且不属于第一行文本。
- 不读写材料文件、数据库，不调用模型，不返回数据库 ID。
"""
from .source_adapters import (
    TXT_PARSER_VERSION,
    ParsedSource,
    SourceNode,
    SourceParseError,
)


def decode_txt(data: bytes) -> str:
    """UTF-8 解码，允许 UTF-8 BOM；失败则拒绝。"""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceParseError("invalid_encoding", "文件不是有效 UTF-8", [str(exc)]) from exc


def split_lines(text: str) -> list[str]:
    """按 LF/CRLF 切分并去掉行终止符；末尾换行不产生额外空行。"""
    if text == "":
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def parse_txt(data: bytes) -> ParsedSource:
    """把 TXT 字节转成带真实行号的文本节点；空行不产节点但占行号。"""
    lines = split_lines(decode_txt(data))
    nodes: list[SourceNode] = []
    for line_index, line in enumerate(lines, start=1):
        if line == "":
            continue
        nodes.append(
            SourceNode(
                kind="line",
                text=line,
                body_ordinal=len(nodes),
                line_index=line_index,
            )
        )
    return ParsedSource(
        format="txt",
        parser_version=TXT_PARSER_VERSION,
        nodes=tuple(nodes),
        line_count=len(lines),
    )

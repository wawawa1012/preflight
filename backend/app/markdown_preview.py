"""把 UTF-8 Markdown 字节转成临时 Block 预览；不保存、不抽取、不渲染。

冻结规则：
- 空行严格定义为：去掉 LF/CRLF 后长度为 0 的行。
- 长度为 0 的空行不生成 Block，但计入行号；只含空格或 Tab 的行不是空行，必须生成 Block。
- 行内容保留原文（含行首、行尾空格与 Tab），只去掉行终止符；LF 与 CRLF 都支持。
- UTF-8 BOM 文件合法；BOM 不属于第一行的 Block text。
- Block.ordinal 从 0 连续递增；Locator.kind="line"，index 是从 1 开始的原文件行号。
- 每行一个 Block：end_index 固定为 null，block_index 固定为 1。
"""
import hashlib

from .contracts import Block, Locator, MarkdownPreview

MAX_BYTES = 1024 * 1024
TEMPORARY_DOCUMENT_ID = "preview"


class PreviewRejected(Exception):
    """输入被拒绝；由 API 层转换成 ApiError。"""

    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


def validate_filename(filename: str) -> None:
    if not filename.lower().endswith(".md"):
        raise PreviewRejected("invalid_extension", "只支持 .md 文件", [f"收到：{filename or '空文件名'}"])


def decode_markdown(data: bytes) -> str:
    """UTF-8 解码，允许 UTF-8 BOM；失败则拒绝。"""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreviewRejected("invalid_encoding", "文件不是有效 UTF-8", [str(exc)]) from exc


def split_lines(text: str) -> list[str]:
    """按 LF/CRLF 切分并去掉行终止符；末尾换行不产生额外空行。"""
    if text == "":
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def build_preview(filename: str, data: bytes) -> MarkdownPreview:
    validate_filename(filename)
    if len(data) > MAX_BYTES:
        raise PreviewRejected("file_too_large", "文件超过 1 MiB 上限", [f"收到 {len(data)} 字节"])

    lines = split_lines(decode_markdown(data))
    blocks: list[Block] = []
    for line_number, line in enumerate(lines, start=1):
        # 只有长度为 0 的行才是空行；空格/Tab 行照常生成 Block。
        if line == "":
            continue
        blocks.append(
            Block(
                id=f"{TEMPORARY_DOCUMENT_ID}-block-{len(blocks)}",
                document_id=TEMPORARY_DOCUMENT_ID,
                ordinal=len(blocks),
                text=line,
                locator=Locator(kind="line", index=line_number, end_index=None, block_index=1),
            )
        )

    return MarkdownPreview(
        document_id=TEMPORARY_DOCUMENT_ID,
        filename=filename,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        line_count=len(lines),
        blocks=blocks,
    )

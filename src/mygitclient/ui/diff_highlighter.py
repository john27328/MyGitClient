from __future__ import annotations

import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit

from mygitclient.git.models import DiffLineKind, UnifiedDiff

SyntaxRule = tuple[re.Pattern[str], str]

_PYTHON_KEYWORDS = (
    "and|as|assert|async|await|break|case|class|continue|def|del|elif|else|except|"
    "False|finally|for|from|global|if|import|in|is|lambda|match|None|nonlocal|not|or|"
    "pass|raise|return|True|try|while|with|yield"
)
_C_KEYWORDS = (
    "alignas|alignof|auto|bool|break|case|catch|char|class|const|constexpr|continue|"
    "default|delete|do|double|else|enum|explicit|extern|false|float|for|friend|if|"
    "inline|int|long|namespace|new|nullptr|operator|override|private|protected|public|"
    "return|short|signed|sizeof|static|struct|switch|template|this|throw|true|try|"
    "typedef|typename|union|unsigned|using|virtual|void|volatile|while"
)
_CS_JAVA_KEYWORDS = (
    "abstract|as|async|await|base|boolean|break|byte|case|catch|char|class|const|"
    "continue|decimal|default|delegate|do|double|else|enum|extends|false|final|finally|"
    "float|for|foreach|if|implements|import|in|instanceof|int|interface|internal|is|"
    "long|namespace|new|null|nullptr|object|out|override|package|private|protected|public|"
    "record|return|sealed|short|static|string|struct|super|switch|this|throw|throws|"
    "true|try|using|var|virtual|void|volatile|while"
)
_JS_KEYWORDS = (
    "async|await|break|case|catch|class|const|continue|debugger|default|delete|do|else|"
    "export|extends|false|finally|for|from|function|get|if|import|in|instanceof|let|new|"
    "null|of|return|set|static|super|switch|this|throw|true|try|typeof|undefined|var|"
    "void|while|with|yield"
)


def _rules(keywords: str, comment: str) -> tuple[SyntaxRule, ...]:
    return (
        (re.compile(rf"\b(?:{keywords})\b"), "keyword"),
        (re.compile(r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?)\b"), "number"),
        (re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''), "string"),
        (re.compile(comment), "comment"),
    )


_LANGUAGE_RULES: dict[str, tuple[SyntaxRule, ...]] = {
    "python": _rules(_PYTHON_KEYWORDS, r"#.*$"),
    "c": _rules(_C_KEYWORDS, r"//.*$|/\*.*?\*/"),
    "csharp": _rules(_CS_JAVA_KEYWORDS, r"//.*$|/\*.*?\*/"),
    "java": _rules(_CS_JAVA_KEYWORDS, r"//.*$|/\*.*?\*/"),
    "javascript": _rules(_JS_KEYWORDS, r"//.*$|/\*.*?\*/"),
    "json": (
        (re.compile(r'"(?:\\.|[^"\\])*"(?=\s*:)'), "keyword"),
        (re.compile(r'"(?:\\.|[^"\\])*"'), "string"),
        (re.compile(r"\b(?:true|false|null)\b"), "keyword"),
        (re.compile(r"\b(?:-?\d+(?:\.\d+)?)\b"), "number"),
    ),
    "yaml": (
        (re.compile(r"^[+\- ]?\s*[\w.-]+(?=\s*:)", re.UNICODE), "keyword"),
        (re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''), "string"),
        (re.compile(r"\b(?:true|false|null|yes|no)\b", re.IGNORECASE), "keyword"),
        (re.compile(r"#.*$"), "comment"),
    ),
    "shell": _rules(
        "case|do|done|elif|else|esac|export|fi|for|function|if|in|local|readonly|then|while",
        r"#.*$",
    ),
    "markdown": (
        (re.compile(r"^[+\- ]?#{1,6}\s+.*$"), "keyword"),
        (re.compile(r"`[^`]+`"), "string"),
        (re.compile(r"\*\*[^*]+\*\*|__[^_]+__"), "keyword"),
    ),
}


def _language_for_path(path: str) -> str | None:
    suffix = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if suffix in {"py", "pyi", "pyw"}:
        return "python"
    if suffix in {"c", "cc", "cpp", "cxx", "h", "hh", "hpp", "hxx"}:
        return "c"
    if suffix == "cs":
        return "csharp"
    if suffix in {"java", "kt", "kts"}:
        return "java"
    if suffix in {"js", "jsx", "mjs", "cjs", "ts", "tsx"}:
        return "javascript"
    if suffix == "json":
        return "json"
    if suffix in {"yaml", "yml"}:
        return "yaml"
    if suffix in {"sh", "bash", "zsh", "ps1"}:
        return "shell"
    if suffix in {"md", "markdown"}:
        return "markdown"
    return None


class DiffHighlighter(QSyntaxHighlighter):
    """Apply theme-aware semantic colors to a rendered unified diff."""

    def __init__(self, editor: QPlainTextEdit) -> None:
        super().__init__(editor.document())
        self._editor = editor
        self._line_kinds: tuple[DiffLineKind, ...] = ()
        self._inline_ranges: dict[int, tuple[tuple[int, int], ...]] = {}
        self._language: str | None = None

    def set_diff(self, diff: UnifiedDiff | None) -> None:
        self._language = None if diff is None else _language_for_path(diff.path)
        self.set_line_kinds(() if diff is None else tuple(line.kind for line in diff.lines))

    def set_line_kinds(self, line_kinds: tuple[DiffLineKind, ...]) -> None:
        self._line_kinds = line_kinds
        self.rehighlight()

    def set_language(self, path: str) -> None:
        self._language = _language_for_path(path)
        self.rehighlight()

    def set_inline_ranges(self, ranges: dict[int, tuple[tuple[int, int], ...]]) -> None:
        self._inline_ranges = ranges
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        block_number = self.currentBlock().blockNumber()
        if block_number < 0 or block_number >= len(self._line_kinds):
            return
        kind = self._line_kinds[block_number]
        colors = self._colors()
        background = colors.get(kind)
        if background is None:
            text_format = QTextCharFormat()
        else:
            text_format = QTextCharFormat()
            text_format.setBackground(background)
            if kind in {"header", "hunk"}:
                text_format.setForeground(colors["header_text"])
            self.setFormat(0, len(text), text_format)
        if self._language is not None and kind in {"addition", "deletion", "context"}:
            for pattern, color_role in _LANGUAGE_RULES[self._language]:
                syntax_format = QTextCharFormat()
                syntax_format.setForeground(colors[color_role])
                if background is not None:
                    syntax_format.setBackground(background)
                for match in pattern.finditer(text):
                    self.setFormat(
                        match.start(), match.end() - match.start(), syntax_format
                    )
        inline_format = QTextCharFormat()
        inline_format.setBackground(
            colors["inline_addition"]
            if kind == "addition"
            else colors["inline_deletion"]
        )
        for start, length in self._inline_ranges.get(block_number, ()):
            self.setFormat(start, length, inline_format)

    def _colors(self) -> dict[str, QColor]:
        dark = self._editor.palette().base().color().lightness() < 128
        if dark:
            return {
                "addition": QColor("#142f20"),
                "deletion": QColor("#3b1d22"),
                "hunk": QColor("#243955"),
                "header": QColor("#252a31"),
                "header_text": QColor("#9aa7b5"),
                "keyword": QColor("#c792ea"),
                "string": QColor("#c3e88d"),
                "comment": QColor("#7f8c98"),
                "number": QColor("#f78c6c"),
                "inline_addition": QColor("#285d3a"),
                "inline_deletion": QColor("#71313a"),
            }
        return {
            "addition": QColor("#edf8f0"),
            "deletion": QColor("#fbecec"),
            "hunk": QColor("#e8f0fa"),
            "header": QColor("#f3f5f7"),
            "header_text": QColor("#64758a"),
            "keyword": QColor("#7b3fc6"),
            "string": QColor("#2e7d32"),
            "comment": QColor("#718096"),
            "number": QColor("#b45309"),
            "inline_addition": QColor("#b9e7c5"),
            "inline_deletion": QColor("#f1b9b9"),
        }

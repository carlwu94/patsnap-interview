from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": WORD_NS, "m": MATH_NS}


def qn(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


W_VAL = qn(WORD_NS, "val")
W_P = qn(WORD_NS, "p")
W_TBL = qn(WORD_NS, "tbl")
W_TR = qn(WORD_NS, "tr")
W_TC = qn(WORD_NS, "tc")


@dataclass(frozen=True)
class LevelDefinition:
    start: int
    num_fmt: str
    lvl_text: str


class NumberingDefinitions:
    def __init__(self) -> None:
        self.abstract_levels: dict[int, dict[int, LevelDefinition]] = {}
        self.num_to_abstract: dict[int, int] = {}
        self.level_overrides: dict[int, dict[int, LevelDefinition]] = {}

    @classmethod
    def from_xml_bytes(cls, xml_bytes: bytes | None) -> "NumberingDefinitions":
        definitions = cls()
        if not xml_bytes:
            return definitions

        root = ET.fromstring(xml_bytes)
        for abstract_num in root.findall("w:abstractNum", NS):
            abstract_num_id = int(abstract_num.attrib[qn(WORD_NS, "abstractNumId")])
            levels: dict[int, LevelDefinition] = {}
            for level in abstract_num.findall("w:lvl", NS):
                ilvl = int(level.attrib[qn(WORD_NS, "ilvl")])
                levels[ilvl] = parse_level_definition(level)
            definitions.abstract_levels[abstract_num_id] = levels

        for numbering in root.findall("w:num", NS):
            num_id = int(numbering.attrib[qn(WORD_NS, "numId")])
            abstract_num_id = int(numbering.find("w:abstractNumId", NS).attrib[W_VAL])
            definitions.num_to_abstract[num_id] = abstract_num_id

            overrides: dict[int, LevelDefinition] = {}
            for override in numbering.findall("w:lvlOverride", NS):
                ilvl = int(override.attrib[qn(WORD_NS, "ilvl")])
                override_level = override.find("w:lvl", NS)
                start_override = override.find("w:startOverride", NS)

                if override_level is not None:
                    overrides[ilvl] = parse_level_definition(override_level)
                    continue

                base_definition = definitions.abstract_levels.get(abstract_num_id, {}).get(ilvl)
                if base_definition is None:
                    continue
                if start_override is None:
                    continue
                overrides[ilvl] = LevelDefinition(
                    start=int(start_override.attrib[W_VAL]),
                    num_fmt=base_definition.num_fmt,
                    lvl_text=base_definition.lvl_text,
                )

            definitions.level_overrides[num_id] = overrides

        return definitions

    def level_definition(self, num_id: int, ilvl: int) -> LevelDefinition | None:
        override = self.level_overrides.get(num_id, {}).get(ilvl)
        if override is not None:
            return override

        abstract_num_id = self.num_to_abstract.get(num_id)
        if abstract_num_id is None:
            return None
        return self.abstract_levels.get(abstract_num_id, {}).get(ilvl)


def parse_level_definition(level: ET.Element) -> LevelDefinition:
    start_node = level.find("w:start", NS)
    num_fmt_node = level.find("w:numFmt", NS)
    lvl_text_node = level.find("w:lvlText", NS)

    return LevelDefinition(
        start=int(start_node.attrib[W_VAL]) if start_node is not None else 1,
        num_fmt=num_fmt_node.attrib[W_VAL] if num_fmt_node is not None else "decimal",
        lvl_text=lvl_text_node.attrib[W_VAL] if lvl_text_node is not None else "",
    )


class NumberingState:
    def __init__(self, definitions: NumberingDefinitions) -> None:
        self.definitions = definitions
        self.counters: dict[int, dict[int, int]] = {}

    def render_prefix(self, num_id: int, ilvl: int) -> str:
        level_definition = self.definitions.level_definition(num_id, ilvl)
        if level_definition is None:
            return ""

        state = self.counters.setdefault(num_id, {})
        for level in list(state):
            if level > ilvl:
                del state[level]

        current_value = state.get(ilvl, level_definition.start - 1) + 1
        state[ilvl] = current_value

        if level_definition.num_fmt == "bullet" and "%" not in level_definition.lvl_text:
            return level_definition.lvl_text

        template = level_definition.lvl_text or f"%{ilvl + 1}"

        def replace_match(match: re.Match[str]) -> str:
            referenced_level = int(match.group(1)) - 1
            value = state.get(referenced_level)
            if value is None:
                referenced_definition = self.definitions.level_definition(num_id, referenced_level)
                value = referenced_definition.start if referenced_definition is not None else 1
            referenced_definition = self.definitions.level_definition(num_id, referenced_level)
            referenced_fmt = referenced_definition.num_fmt if referenced_definition is not None else "decimal"
            return format_counter(value, referenced_fmt)

        return re.sub(r"%(\d+)", replace_match, template)


def format_counter(value: int, num_fmt: str) -> str:
    if num_fmt in {"decimal", "cardinalText", "ordinal"}:
        return str(value)
    if num_fmt == "decimalZero":
        return f"{value:02d}"
    if num_fmt == "lowerLetter":
        return to_alpha(value).lower()
    if num_fmt == "upperLetter":
        return to_alpha(value).upper()
    if num_fmt == "lowerRoman":
        return to_roman(value).lower()
    if num_fmt == "upperRoman":
        return to_roman(value).upper()
    return str(value)


def to_alpha(value: int) -> str:
    result: list[str] = []
    current = value
    while current > 0:
        current -= 1
        current, remainder = divmod(current, 26)
        result.append(chr(ord("A") + remainder))
    return "".join(reversed(result)) or "A"


def to_roman(value: int) -> str:
    numerals = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    result: list[str] = []
    current = value
    for numeral_value, numeral_text in numerals:
        while current >= numeral_value:
            result.append(numeral_text)
            current -= numeral_value
    return "".join(result) or "I"


class DocxConverter:
    def __init__(self, docx_path: Path) -> None:
        self.docx_path = docx_path
        with ZipFile(docx_path) as archive:
            self.document_root = ET.fromstring(archive.read("word/document.xml"))
            numbering_bytes = archive.read("word/numbering.xml") if "word/numbering.xml" in archive.namelist() else None
        self.numbering = NumberingDefinitions.from_xml_bytes(numbering_bytes)
        self.numbering_state = NumberingState(self.numbering)

    def convert(self) -> str:
        body = self.document_root.find("w:body", NS)
        blocks: list[str] = []
        for child in body:
            if child.tag == W_P:
                blocks.append(self.render_paragraph(child))
            elif child.tag == W_TBL:
                blocks.append(self.render_table(child))
        return "\n\n".join(blocks).rstrip() + "\n"

    def render_paragraph(self, paragraph: ET.Element) -> str:
        text = extract_text(paragraph)
        prefix = self.paragraph_prefix(paragraph)
        if prefix and text:
            return f"{prefix} {text}"
        if prefix:
            return prefix
        return text

    def paragraph_prefix(self, paragraph: ET.Element) -> str:
        num_pr = paragraph.find("w:pPr/w:numPr", NS)
        if num_pr is None:
            return ""

        ilvl_node = num_pr.find("w:ilvl", NS)
        num_id_node = num_pr.find("w:numId", NS)
        if ilvl_node is None or num_id_node is None:
            return ""

        ilvl = int(ilvl_node.attrib[W_VAL])
        num_id = int(num_id_node.attrib[W_VAL])
        return self.numbering_state.render_prefix(num_id, ilvl)

    def render_table(self, table: ET.Element) -> str:
        rows: list[str] = []
        for row in table.findall("w:tr", NS):
            cells: list[str] = []
            for cell in row.findall("w:tc", NS):
                cell_blocks: list[str] = []
                for child in cell:
                    if child.tag == W_P:
                        cell_blocks.append(self.render_paragraph(child))
                    elif child.tag == W_TBL:
                        cell_blocks.append(self.render_table(child))
                cell_text = " ".join(part for part in cell_blocks if part.strip())
                cells.append(cell_text)
            rows.append("\t".join(cells).rstrip())
        return "\n".join(rows)


def extract_text(element: ET.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        tag_name = local_name(node.tag)
        if tag_name == "t":
            parts.append(node.text or "")
        elif tag_name == "tab":
            parts.append("\t")
        elif tag_name in {"br", "cr"}:
            parts.append("\n")
        elif tag_name == "noBreakHyphen":
            parts.append("-")
        elif tag_name == "sym":
            char_value = node.attrib.get(qn(WORD_NS, "char"))
            if char_value:
                try:
                    parts.append(chr(int(char_value, 16)))
                except ValueError:
                    continue
    return "".join(parts)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def default_output_path(docx_path: Path) -> Path:
    return docx_path.with_suffix(".md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a DOCX file to Markdown without rewriting the visible text.")
    parser.add_argument("docx_path", type=Path, help="Path to the source DOCX file")
    parser.add_argument("output_path", nargs="?", type=Path, help="Optional output Markdown path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    docx_path = args.docx_path.resolve()
    output_path = args.output_path.resolve() if args.output_path else default_output_path(docx_path)

    converter = DocxConverter(docx_path)
    markdown = converter.convert()

    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
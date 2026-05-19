"""Small OOXML helpers used by the trust minute pipeline.

The project deliberately avoids Word automation.  These helpers treat Word
documents as ZIP packages and edit the WordprocessingML directly.
"""

from __future__ import annotations

import copy
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "templates" / "source"
WORKING_DIR = ROOT / "templates" / "working"
FIELDMAP_DIR = ROOT / "templates" / "fieldmaps"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_NS = "http://www.w3.org/XML/1998/namespace"

NS = {
    "w": W_NS,
    "r": R_NS,
    "rel": PKG_REL_NS,
    "ct": CT_NS,
}

ET.register_namespace("w", W_NS)
ET.register_namespace("r", R_NS)
ET.register_namespace("xml", XML_NS)


def qn(name: str) -> str:
    prefix, local = name.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


def _is_xml_part(name: str) -> bool:
    return name.startswith("word/") and name.endswith(".xml")


def _iter_word_xml_parts(names: Iterable[str]) -> list[str]:
    return [
        name
        for name in names
        if _is_xml_part(name)
        and (
            name == "word/document.xml"
            or name.startswith("word/header")
            or name.startswith("word/footer")
            or name in {"word/footnotes.xml", "word/endnotes.xml"}
        )
    ]


def read_package_part(package: Path | bytes, part_name: str) -> bytes | None:
    with _open_zip(package) as zf:
        try:
            return zf.read(part_name)
        except KeyError:
            return None


def read_xml(package: Path | bytes, part_name: str) -> ET.Element:
    raw = read_package_part(package, part_name)
    if raw is None:
        raise FileNotFoundError(f"{part_name} not found in package")
    return ET.fromstring(raw)


def write_docx_bytes(package: Path | bytes, replacements: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with _open_zip(package) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = replacements.get(item.filename)
            if data is None:
                data = src.read(item.filename)
            dst.writestr(item, data)
    return out.getvalue()


def _open_zip(package: Path | bytes) -> zipfile.ZipFile:
    if isinstance(package, bytes):
        return zipfile.ZipFile(io.BytesIO(package), "r")
    return zipfile.ZipFile(package, "r")


def package_text(package: Path | bytes) -> str:
    texts: list[str] = []
    with _open_zip(package) as zf:
        for name in _iter_word_xml_parts(zf.namelist()):
            root = ET.fromstring(zf.read(name))
            texts.append(element_text(root))
    return "\n".join(texts)


def extract_tables(package: Path | bytes) -> list[list[list[str]]]:
    root = read_xml(package, "word/document.xml")
    tables: list[list[list[str]]] = []
    for tbl in root.findall(".//w:tbl", NS):
        rows: list[list[str]] = []
        for tr in tbl.findall("./w:tr", NS):
            rows.append([normalise_space(element_text(tc)) for tc in tr.findall("./w:tc", NS)])
        tables.append(rows)
    return tables


def element_text(element: ET.Element) -> str:
    return "".join(t.text or "" for t in element.findall(".//w:t", NS))


def normalise_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clamp_quote(value: str, max_words: int = 50) -> str:
    words = normalise_space(value).split()
    return " ".join(words[:max_words])


def set_element_text(element: ET.Element, value: Any) -> None:
    text = "" if value is None else str(value)
    text_nodes = element.findall(".//w:t", NS)
    if text_nodes:
        text_nodes[0].text = text
        text_nodes[0].set(f"{{{XML_NS}}}space", "preserve")
        for node in text_nodes[1:]:
            node.text = ""
        return

    paragraph = element.find(".//w:p", NS)
    if paragraph is None:
        paragraph = ET.SubElement(element, qn("w:p"))
    run = ET.SubElement(paragraph, qn("w:r"))
    node = ET.SubElement(run, qn("w:t"))
    node.set(f"{{{XML_NS}}}space", "preserve")
    node.text = text


def replace_text_nodes(root: ET.Element, replacements: dict[str, Any]) -> int:
    """Replace visible strings even when the target spans several runs.

    For each paragraph we flatten all text nodes, apply replacements, then put
    the changed string back into the first run.  This sacrifices local run
    formatting only in paragraphs that actually changed.
    """

    changed = 0
    string_replacements = {
        str(key): "" if value is None else str(value)
        for key, value in replacements.items()
        if key
    }
    for paragraph in root.findall(".//w:p", NS):
        nodes = paragraph.findall(".//w:t", NS)
        if not nodes:
            continue
        current = "".join(node.text or "" for node in nodes)
        updated = current
        for needle, value in string_replacements.items():
            updated = updated.replace(needle, value)
        if updated != current:
            nodes[0].text = updated
            nodes[0].set(f"{{{XML_NS}}}space", "preserve")
            for node in nodes[1:]:
                node.text = ""
            changed += 1
    return changed


def replace_placeholders(package: Path | bytes, replacements: dict[str, Any]) -> bytes:
    with _open_zip(package) as zf:
        part_names = _iter_word_xml_parts(zf.namelist())
        updates: dict[str, bytes] = {}
        for name in part_names:
            root = ET.fromstring(zf.read(name))
            replace_text_nodes(root, replacements)
            updates[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return write_docx_bytes(package, updates)


def replace_docx_field_values(package: Path | bytes, data: dict[str, Any], field_map: list[dict[str, Any]]) -> bytes:
    replacements: dict[str, str] = {}
    for item in field_map:
        path = item.get("field_path")
        if not path:
            continue
        value = get_field_value(data, path, default="")
        for placeholder in item.get("placeholders", []):
            replacements[placeholder] = stringify_value(value)
        replacements[f"{{{{{path}}}}}"] = stringify_value(value)
    return replace_placeholders(package, replacements)


def get_field_value(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    if isinstance(current, dict) and "value" in current:
        return current.get("value", default)
    return current


def get_evidenced(data: dict[str, Any], path: str) -> dict[str, Any] | None:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current if isinstance(current, dict) else None


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if "name" in item:
                    parts.append(str(item["name"]))
                elif "value" in item:
                    parts.append(str(item["value"]))
                else:
                    parts.append(", ".join(f"{k}: {v}" for k, v in item.items()))
            else:
                parts.append(str(item))
        return "; ".join(parts)
    if isinstance(value, dict):
        if "value" in value:
            return stringify_value(value.get("value"))
        return "; ".join(f"{k}: {stringify_value(v)}" for k, v in value.items())
    return str(value)


def load_fieldmap(name: str) -> dict[str, Any]:
    path = FIELDMAP_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def package_has_macros(path: Path) -> bool:
    with zipfile.ZipFile(path, "r") as zf:
        return any("vbaProject" in name or name.endswith(".bin") and "activeX" in name for name in zf.namelist())


def package_has_activex(path: Path) -> bool:
    with zipfile.ZipFile(path, "r") as zf:
        return any("activeX" in name for name in zf.namelist())


def macro_free_copy(source: Path, destination: Path) -> Path:
    """Create a macro-free DOCX/DOTX-style package from DOCM/DOTM source."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    skip_patterns = (
        "vbaProject",
        "vbaData.xml",
        "activeX/",
        "embeddings/",
        "customUI/",
    )
    with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            name = item.filename
            if any(pattern in name for pattern in skip_patterns):
                continue
            if name.endswith(".rels"):
                data = _remove_macro_relationships(src.read(name))
            elif name == "[Content_Types].xml":
                data = _rewrite_content_types(src.read(name), destination.suffix.lower())
            else:
                data = src.read(name)
            dst.writestr(item, data)
    return destination


def _remove_macro_relationships(raw: bytes) -> bytes:
    root = ET.fromstring(raw)
    for rel in list(root):
        rel_type = rel.attrib.get("Type", "")
        target = rel.attrib.get("Target", "")
        if any(token in rel_type or token in target for token in ("vbaProject", "activeX", "vbaData")):
            root.remove(rel)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rewrite_content_types(raw: bytes, suffix: str) -> bytes:
    root = ET.fromstring(raw)
    for override in list(root):
        part = override.attrib.get("PartName", "")
        content_type = override.attrib.get("ContentType", "")
        if any(token in part for token in ("/vbaProject", "/activeX/", "/vbaData.xml")):
            root.remove(override)
            continue
        if "macroEnabled" in content_type:
            if suffix == ".dotx":
                content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
            else:
                content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            override.set("ContentType", content_type)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def ensure_working_template(kind: str) -> Path:
    source_names = {
        "discretionary": "Discretionary Trust Minute Template - User Form.docm",
        "unit": "Unit Trust Minute Template - User Form.docm",
    }
    dest_names = {
        "discretionary": "discretionary_trust_minute.docx",
        "unit": "unit_trust_minute.docx",
    }
    if kind not in source_names:
        raise ValueError(f"Unknown template kind: {kind}")
    destination = WORKING_DIR / dest_names[kind]
    source = template_source_path(kind, source_names[kind])
    if not source.exists():
        raise FileNotFoundError(f"Missing source template: {source}")
    if destination.exists() and destination.stat().st_mtime >= source.stat().st_mtime:
        return destination
    return macro_free_copy(source, destination)


def template_source_path(kind: str, source_name: str) -> Path:
    return SOURCE_DIR / source_name


@dataclass(frozen=True)
class Branch:
    index: int
    start_child_index: int
    end_child_index: int
    label: str


def detect_manual_page_break_branches(package: Path | bytes) -> list[Branch]:
    root = read_xml(package, "word/document.xml")
    body = root.find("w:body", NS)
    if body is None:
        return []
    starts: list[int] = []
    for index, child in enumerate(list(body)):
        text = normalise_space(element_text(child)).lower()
        if text.startswith("minutes of trustee resolution"):
            starts.append(index)
    branches: list[Branch] = []
    labels = [
        "corporate_multi_director",
        "corporate_sole_director",
        "individual_sole_trustee",
        "individual_multi_trustee",
    ]
    body_children = list(body)
    sect_index = len(body_children)
    if body_children and body_children[-1].tag == qn("w:sectPr"):
        sect_index -= 1
    for branch_index, start in enumerate(starts):
        end = starts[branch_index + 1] if branch_index + 1 < len(starts) else sect_index
        label = labels[branch_index] if branch_index < len(labels) else f"branch_{branch_index + 1}"
        branches.append(Branch(branch_index, start, end, label))
    return branches


def select_branch(package: Path | bytes, branch_label: str) -> bytes:
    root = read_xml(package, "word/document.xml")
    branches = detect_manual_page_break_branches(package)
    target = next((branch for branch in branches if branch.label == branch_label), None)
    if target is None:
        return package.read_bytes() if isinstance(package, Path) else package

    body = root.find("w:body", NS)
    if body is None:
        return package.read_bytes() if isinstance(package, Path) else package

    children = list(body)
    keep: set[int] = set(range(target.start_child_index, target.end_child_index))
    if children and children[-1].tag == qn("w:sectPr"):
        keep.add(len(children) - 1)
    for index, child in enumerate(children):
        if index not in keep:
            body.remove(child)

    first = next(iter(body), None)
    if first is not None:
        for br in list(first.findall(".//w:br", NS)):
            if br.attrib.get(qn("w:type")) == "page":
                parent = _find_parent(first, br)
                if parent is not None:
                    parent.remove(br)

    updates = {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)}
    return write_docx_bytes(package, updates)


def _find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for candidate in root.iter():
        if child in list(candidate):
            return candidate
    return None


def fill_table_rows_by_label(
    package: Path | bytes,
    values_by_label: dict[str, Any],
    *,
    value_column: int = 1,
    match_contains: bool = False,
) -> bytes:
    root = read_xml(package, "word/document.xml")
    labels = {normalise_space(key).lower(): value for key, value in values_by_label.items()}
    for tbl in root.findall(".//w:tbl", NS):
        for tr in tbl.findall("./w:tr", NS):
            cells = tr.findall("./w:tc", NS)
            if len(cells) <= value_column:
                continue
            label = normalise_space(element_text(cells[0])).lower()
            match_key = None
            if label in labels:
                match_key = label
            elif match_contains:
                match_key = next((key for key in labels if key and key in label), None)
            if match_key:
                set_element_text(cells[value_column], stringify_value(labels[match_key]))
    updates = {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)}
    return write_docx_bytes(package, updates)


def fill_checklist_rows(package: Path | bytes, rows: list[dict[str, Any]]) -> bytes:
    root = read_xml(package, "word/document.xml")
    for tbl in root.findall(".//w:tbl", NS):
        for tr in tbl.findall("./w:tr", NS):
            cells = tr.findall("./w:tc", NS)
            if len(cells) < 3:
                continue
            item_text = normalise_space(element_text(cells[0])).lower()
            if not item_text:
                continue
            match = next(
                (
                    row
                    for row in rows
                    if row.get("question_fragment")
                    and row["question_fragment"].lower() in item_text
                ),
                None,
            )
            if not match:
                continue
            set_element_text(cells[1], match.get("relevant_clauses", ""))
            set_element_text(cells[2], match.get("notes", ""))
            if len(cells) > 3 and "answer" in match:
                set_element_text(cells[1], match.get("answer", ""))
                set_element_text(cells[2], match.get("relevant_clauses", ""))
                set_element_text(cells[3], match.get("notes", ""))
    updates = {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)}
    return write_docx_bytes(package, updates)


def fill_tables_by_header(package: Path | bytes, headers: list[str], rows: list[list[Any]]) -> bytes:
    root = read_xml(package, "word/document.xml")
    target_headers = [normalise_space(header).lower() for header in headers]
    for tbl in root.findall(".//w:tbl", NS):
        table_rows = tbl.findall("./w:tr", NS)
        if not table_rows:
            continue
        header_cells = table_rows[0].findall("./w:tc", NS)
        actual_headers = [normalise_space(element_text(cell)).lower() for cell in header_cells]
        if actual_headers[: len(target_headers)] != target_headers:
            continue
        data_rows = table_rows[1:]
        if rows and not data_rows:
            data_rows.append(copy.deepcopy(table_rows[0]))
            tbl.append(data_rows[-1])
        while rows and len(data_rows) < len(rows):
            data_rows.append(copy.deepcopy(data_rows[-1]))
            tbl.append(data_rows[-1])
        for index, tr in enumerate(data_rows):
            cells = tr.findall("./w:tc", NS)
            values = rows[index] if index < len(rows) else [""] * len(headers)
            for cell_index, cell in enumerate(cells[: len(headers)]):
                set_element_text(cell, values[cell_index] if cell_index < len(values) else "")
    updates = {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)}
    return write_docx_bytes(package, updates)


def remove_paragraphs_matching(package: Path | bytes, patterns: list[str]) -> bytes:
    regexes = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    root = read_xml(package, "word/document.xml")
    body = root.find("w:body", NS)
    if body is None:
        return package.read_bytes() if isinstance(package, Path) else package
    children = list(body)
    to_remove: set[int] = set()
    for index, child in enumerate(children):
        text = normalise_space(element_text(child))
        if any(regex.search(text) for regex in regexes):
            to_remove.add(index)
            if index > 0 and re.fullmatch(r"[_\s]+", element_text(children[index - 1]) or ""):
                to_remove.add(index - 1)
    for index in sorted(to_remove, reverse=True):
        if children[index].tag != qn("w:sectPr"):
            body.remove(children[index])
    updates = {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)}
    return write_docx_bytes(package, updates)


def append_paragraph(package: Path | bytes, text: str, *, style: str | None = None) -> bytes:
    root = read_xml(package, "word/document.xml")
    body = root.find("w:body", NS)
    if body is None:
        return package.read_bytes() if isinstance(package, Path) else package
    paragraph = make_paragraph(text, style=style)
    _insert_before_section_properties(body, paragraph)
    updates = {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)}
    return write_docx_bytes(package, updates)


def append_table(package: Path | bytes, title: str, headers: list[str], rows: list[list[Any]]) -> bytes:
    root = read_xml(package, "word/document.xml")
    body = root.find("w:body", NS)
    if body is None:
        return package.read_bytes() if isinstance(package, Path) else package
    _insert_before_section_properties(body, make_paragraph(title, style="Heading2"))
    table = make_table(headers, rows)
    _insert_before_section_properties(body, table)
    updates = {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)}
    return write_docx_bytes(package, updates)


def _insert_before_section_properties(body: ET.Element, child: ET.Element) -> None:
    children = list(body)
    if children and children[-1].tag == qn("w:sectPr"):
        body.insert(len(children) - 1, child)
    else:
        body.append(child)


def make_paragraph(text: str, *, style: str | None = None) -> ET.Element:
    p = ET.Element(qn("w:p"))
    if style:
        p_pr = ET.SubElement(p, qn("w:pPr"))
        p_style = ET.SubElement(p_pr, qn("w:pStyle"))
        p_style.set(qn("w:val"), style)
    r = ET.SubElement(p, qn("w:r"))
    t = ET.SubElement(r, qn("w:t"))
    t.set(f"{{{XML_NS}}}space", "preserve")
    t.text = text
    return p


def make_table(headers: list[str], rows: list[list[Any]]) -> ET.Element:
    tbl = ET.Element(qn("w:tbl"))
    tbl_pr = ET.SubElement(tbl, qn("w:tblPr"))
    borders = ET.SubElement(tbl_pr, qn("w:tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = ET.SubElement(borders, qn(f"w:{edge}"))
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), "auto")
    _append_table_row(tbl, headers, bold=True)
    for row in rows:
        _append_table_row(tbl, [stringify_value(value) for value in row])
    return tbl


def build_landscape_table_docx(
    headers: list[str],
    rows: list[list[Any]],
    *,
    title: str | None = None,
    font_family: str = "Arial",
    font_size_points: int = 8,
) -> bytes:
    """Build a simple landscape DOCX containing one fixed-width table."""

    half_points = str(font_size_points * 2)
    document = _document_xml(headers, rows, title=title, font_family=font_family, half_points=half_points)
    styles = _styles_xml(font_family=font_family, half_points=half_points)
    content_types = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    package_rels = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document_rels = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", package_rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", styles)
        zf.writestr("word/_rels/document.xml.rels", document_rels)
    return out.getvalue()


def _styles_xml(*, font_family: str, half_points: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:rPr>
      <w:rFonts w:ascii="{xml_escape_text(font_family)}" w:hAnsi="{xml_escape_text(font_family)}"/>
      <w:sz w:val="{half_points}"/>
    </w:rPr>
  </w:style>
</w:styles>""".encode("utf-8")


def _document_xml(headers: list[str], rows: list[list[Any]], *, title: str | None, font_family: str, half_points: str) -> bytes:
    table_rows = [_table_row_xml(headers, bold=True, font_family=font_family, half_points=half_points)]
    table_rows.extend(_table_row_xml([stringify_value(value) for value in row], bold=False, font_family=font_family, half_points=half_points) for row in rows)
    title_xml = _paragraph_xml(title, bold=True, font_family=font_family, half_points=half_points) if title else ""
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}">
  <w:body>
    {title_xml}
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="15400" w:type="dxa"/>
        <w:tblLayout w:type="fixed"/>
        <w:tblBorders>
          <w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>
          <w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>
          <w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>
          <w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>
          <w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>
          <w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>
        </w:tblBorders>
      </w:tblPr>
      <w:tblGrid>
        <w:gridCol w:w="3600"/><w:gridCol w:w="3200"/><w:gridCol w:w="7000"/><w:gridCol w:w="1600"/>
      </w:tblGrid>
      {''.join(table_rows)}
    </w:tbl>
    <w:sectPr>
      <w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>
      <w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="360" w:footer="360" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>""".encode("utf-8")


def _paragraph_xml(text: Any, *, bold: bool, font_family: str, half_points: str) -> str:
    bold_xml = "<w:b/>" if bold else ""
    return f"""<w:p><w:r><w:rPr>{bold_xml}<w:rFonts w:ascii="{xml_escape_text(font_family)}" w:hAnsi="{xml_escape_text(font_family)}"/><w:sz w:val="{half_points}"/></w:rPr><w:t xml:space="preserve">{xml_escape_text(text)}</w:t></w:r></w:p>"""


def _table_row_xml(values: list[Any], *, bold: bool, font_family: str, half_points: str) -> str:
    widths = ["3600", "3200", "7000", "1600"]
    cells = []
    for index in range(4):
        value = values[index] if index < len(values) else ""
        cells.append(
            f"""<w:tc><w:tcPr><w:tcW w:w="{widths[index]}" w:type="dxa"/></w:tcPr>{_paragraph_xml(value, bold=bold, font_family=font_family, half_points=half_points)}</w:tc>"""
        )
    return f"<w:tr>{''.join(cells)}</w:tr>"


def _append_table_row(tbl: ET.Element, values: list[str], *, bold: bool = False) -> None:
    tr = ET.SubElement(tbl, qn("w:tr"))
    for value in values:
        tc = ET.SubElement(tr, qn("w:tc"))
        tc_pr = ET.SubElement(tc, qn("w:tcPr"))
        width = ET.SubElement(tc_pr, qn("w:tcW"))
        width.set(qn("w:w"), "3000")
        width.set(qn("w:type"), "dxa")
        p = ET.SubElement(tc, qn("w:p"))
        r = ET.SubElement(p, qn("w:r"))
        if bold:
            r_pr = ET.SubElement(r, qn("w:rPr"))
            ET.SubElement(r_pr, qn("w:b"))
        t = ET.SubElement(r, qn("w:t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = value


def remove_unresolved_placeholders(package: Path | bytes, placeholders: Iterable[str]) -> bytes:
    replacements = {placeholder: "" for placeholder in placeholders}
    return replace_placeholders(package, replacements)


def remove_bracketed_helper_text(package: Path | bytes) -> bytes:
    """Remove visible template helper prompts such as ``[Insert trust name]``.

    The revised checklist uses bracketed helper text in cells to guide the GPT
    during completion.  Those prompts are not user-facing content in the final
    checklist, so this strips bracketed runs after population.
    """

    with _open_zip(package) as zf:
        part_names = _iter_word_xml_parts(zf.namelist())
        updates: dict[str, bytes] = {}
        for name in part_names:
            root = ET.fromstring(zf.read(name))
            for paragraph in root.findall(".//w:p", NS):
                nodes = paragraph.findall(".//w:t", NS)
                if not nodes:
                    continue
                current = "".join(node.text or "" for node in nodes)
                updated = re.sub(r"\[[^\]]+\]\.?", "", current)
                updated = re.sub(r"\s{2,}", " ", updated).strip()
                if updated != current:
                    nodes[0].text = updated
                    nodes[0].set(f"{{{XML_NS}}}space", "preserve")
                    for node in nodes[1:]:
                        node.text = ""
            updates[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return write_docx_bytes(package, updates)


def unresolved_placeholders(package: Path | bytes, placeholders: Iterable[str]) -> list[str]:
    text = package_text(package)
    return sorted({placeholder for placeholder in placeholders if placeholder and placeholder in text})


def clone_body_children(root: ET.Element) -> list[ET.Element]:
    body = root.find("w:body", NS)
    return [copy.deepcopy(child) for child in body] if body is not None else []


def xml_escape_text(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)

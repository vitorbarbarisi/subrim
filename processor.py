#!/usr/bin/env python3
"""
TTML tick-to-seconds processor

Reads a TTML file (e.g., Netflix IMSC1 subtitles) that uses tick-based timing
expressions (values ending with 't') and converts the 'begin' and 'end'
attributes to seconds offset (e.g., 186.645s), using the document's
ttp:tickRate parameter.

Usage:
  python3 processor.py <folder_name_inside_assets>

Searches the folder under the local "assets" directory (recursively) for one XML file containing "zht"
in its name and one containing "pt" (ignoring files that already contain
"_secs" or "_real"). Writes new files alongside each input with the "_secs"
suffix before the extension.

Additionally, a base TXT file is generated from the zht_secs XML with one line
per subtitle: an incremental index (starting at 1), the begin time, the zht
text, a list of strings generated via LLM no formato ["palavra: tradução", ...],
and the matched pt translation. The file is named "<zht_secs_stem>_base.txt" and saved
alongside the zht_secs file.

If a ".env" file is present next to this script, variables defined there (e.g.,
DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL) will be loaded if not
already present in the environment.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re
import os
import json
from urllib import request as urlrequest, error as urlerror
import sys
import xml.etree.ElementTree as ET


# TTML/IMSC namespaces used in the input file
NS_TTML = "http://www.w3.org/ns/ttml"
NS_TTP = "http://www.w3.org/ns/ttml#parameter"
NS_TTS = "http://www.w3.org/ns/ttml#styling"
NS_NTTM = "http://www.netflix.com/ns/ttml#metadata"


def register_namespaces() -> None:
    """Register known namespaces to preserve prefixes in output as much as possible."""
    # Preserve default TTML namespace
    ET.register_namespace("", NS_TTML)
    # Preserve commonly used prefixes present in the source
    ET.register_namespace("tt", NS_TTML)
    ET.register_namespace("ttp", NS_TTP)
    ET.register_namespace("tts", NS_TTS)
    ET.register_namespace("nttm", NS_NTTM)


@dataclass(frozen=True)
class TimingConversionConfig:
    tick_rate: int


def ticks_to_seconds_string(tick_value: int, tick_rate: int) -> str:
    """Convert a tick count to TTML seconds offset string (e.g., 12.345s).

    Uses Decimal to avoid floating-point rounding issues, rounding to
    milliseconds (3 decimal places, half-up).
    """
    if tick_rate <= 0:
        raise ValueError("tick_rate must be positive")

    total_seconds = (Decimal(tick_value) / Decimal(tick_rate)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    # Ensure fixed 3 decimal places and append TTML seconds suffix
    return f"{format(total_seconds, '.3f')}s"


def convert_timing_attributes(element: ET.Element, config: TimingConversionConfig) -> None:
    """Convert 'begin' and 'end' attributes from ticks to seconds if needed."""
    for attribute_name in ("begin", "end"):
        raw_value = element.get(attribute_name)
        if not raw_value:
            continue

        # Only convert values explicitly in ticks (ending with 't')
        if raw_value.endswith("t"):
            numeric_part = raw_value[:-1]
            if numeric_part.isdigit():
                tick_value = int(numeric_part)
                seconds_value = ticks_to_seconds_string(tick_value, config.tick_rate)
                element.set(attribute_name, seconds_value)
            # If non-digit content precedes 't', leave unchanged (could be expressions we don't parse)


def determine_output_path(input_path: Path, explicit_output: str | None) -> Path:
    if explicit_output:
        return Path(explicit_output).resolve()
    # Insert _real before the extension
    if input_path.suffix:
        return input_path.with_name(f"{input_path.stem}_real{input_path.suffix}")
    return input_path.with_name(f"{input_path.name}_real")


def determine_output_path_secs(input_path: Path) -> Path:
    """Build output path by inserting _secs before the extension."""
    if input_path.suffix:
        return input_path.with_name(f"{input_path.stem}_secs{input_path.suffix}")
    return input_path.with_name(f"{input_path.name}_secs")


def determine_base_output_path(zht_secs_path: Path) -> Path:
    """Build base TXT path: <zht_secs_stem>_base.txt alongside the zht_secs file."""
    return zht_secs_path.with_name(f"{zht_secs_path.stem}_base.txt")


def process_file(input_file: Path, output_file: Path) -> None:
    register_namespaces()

    tree = ET.parse(input_file)
    root = tree.getroot()

    # Read tickRate from the root attribute ttp:tickRate
    tick_rate_attr_name = f"{{{NS_TTP}}}tickRate"
    tick_rate_text = root.attrib.get(tick_rate_attr_name)
    if tick_rate_text is None:
        raise ValueError("Document does not define ttp:tickRate; cannot convert ticks")

    try:
        tick_rate = int(tick_rate_text)
    except ValueError as exc:
        raise ValueError(f"Invalid ttp:tickRate value: {tick_rate_text}") from exc

    config = TimingConversionConfig(tick_rate=tick_rate)

    # Iterate through all elements, converting timing attributes when applicable
    for elem in root.iter():
        convert_timing_attributes(elem, config)

    # Write output preserving XML declaration and UTF-8 encoding
    tree.write(output_file, encoding="utf-8", xml_declaration=True)


def _iter_p_elements(root: ET.Element):
    """Yield TTML <p> elements regardless of namespace prefix usage."""
    p_tag = f"{{{NS_TTML}}}p"
    yield from root.iter(p_tag)


def _extract_text_content(element: ET.Element) -> str:
    """Extract text content from an element, joining nested text.

    Collapses internal whitespace similarly to typical subtitle rendering.
    """
    raw_text = "".join(element.itertext())
    # Normalize whitespace: strip ends and collapse internal runs
    normalized = " ".join(raw_text.split())
    return normalized


def _parse_seconds_value(seconds_text: str) -> Decimal:
    """Parse a TTML seconds string like '12.345s' into Decimal seconds."""
    value = seconds_text.strip().rstrip("s").strip()
    return Decimal(value)


def _load_pt_entries(pt_secs_path: Path) -> list[tuple[Decimal, Decimal, str]]:
    """Load PT entries as a list of (begin_sec, end_sec, text)."""
    tree = ET.parse(pt_secs_path)
    root = tree.getroot()
    entries: list[tuple[Decimal, Decimal, str]] = []
    for p in _iter_p_elements(root):
        begin_text = p.get("begin") or "0s"
        end_text = p.get("end") or begin_text
        try:
            begin_sec = _parse_seconds_value(begin_text)
            end_sec = _parse_seconds_value(end_text)
        except Exception:
            # Skip unparsable entries
            continue
        text_content = _extract_text_content(p)
        entries.append((begin_sec, end_sec, text_content))
    # Keep entries sorted by begin time
    entries.sort(key=lambda e: e[0])
    return entries


def _print_progress(current: int, total: int, prefix: str = "") -> None:
    """Render a simple progress bar to stderr. Falls back to sparse counters if not a TTY."""
    if total <= 0:
        return
    try:
        is_tty = sys.stderr.isatty()
    except Exception:
        is_tty = False

    if not is_tty:
        # Print occasionally to avoid noisy logs
        if current == total or current % 50 == 0:
            print(f"{prefix} {current}/{total}", file=sys.stderr)
        return

    bar_len = 40
    filled = int(bar_len * current / total)
    bar = "█" * filled + " " * (bar_len - filled)
    percent = int((current / total) * 100)
    sys.stderr.write(f"\r{prefix} [{bar}] {percent}% ({current}/{total})")
    sys.stderr.flush()
    if current >= total:
        sys.stderr.write("\n")
        sys.stderr.flush()


def _sanitize_tsv_field(text: str) -> str:
    """Replace tabs/newlines and collapse internal whitespace to keep TSV integrity."""
    if text is None:
        return ""
    cleaned = text.replace("\t", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned


def _call_deepseek_pairs(zht_text: str, timeout_sec: float = 15.0) -> str:
    """Call DeepSeek chat API to extract list ["palavra: tradução", ...] for zht_text.

    Reads configuration from env vars:
      - DEEPSEEK_API_KEY (required to enable calls)
      - DEEPSEEK_API_BASE (default: https://api.deepseek.com)
      - DEEPSEEK_MODEL (default: deepseek-chat)

    Returns the raw model string on success, or 'N/A' on failure/unavailable.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "N/A"

    api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    url = f"{api_base.rstrip('/')}/chat/completions"

    prompt = (
        "Você é um extrator. Dada a frase em chinês tradicional (zht), responda EXTRAINDO "
        "apenas as palavras da própria frase com suas traduções para pt-BR.\n"
        "RETORNE SOMENTE uma lista JSON de strings no formato \"palavra (pinyin): tradução\";\n"
        "sem explicações, sem texto extra, sem rótulos, sem markdown.\n"
        "Exemplo de formato: [\"三 (sān): três\", \"號 (hào): número\", \"碼頭 (mǎ tóu): cais\"].\n"
        "Não invente palavras fora da frase.\n\n"
        f"Frase: {zht_text}"
    )

    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    data = json.dumps(body).encode("utf-8")

    req = urlrequest.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as resp:
            resp_data = resp.read().decode("utf-8", errors="replace")
            obj = json.loads(resp_data)
            content = obj.get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                return "N/A"
            # Try to strictly keep only a JSON array of strings
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                    return json.dumps(parsed, ensure_ascii=False)
            except Exception:
                pass
            # Fallback: sanitize raw content
            return _sanitize_tsv_field(content)
    except (urlerror.URLError, urlerror.HTTPError, TimeoutError, ValueError, KeyError):
        return "N/A"


def generate_zht_base_file(zht_secs_path: Path, pt_secs_path: Path) -> Path:
    """Create a TSV file with: index, begin, zht text, pairs, pt text.

    PT matched by time within ZHT window; pairs fetched via DeepSeek if configured.
    """
    tree = ET.parse(zht_secs_path)
    root = tree.getroot()

    lines: list[str] = []
    index_counter = 1

    pt_entries = _load_pt_entries(pt_secs_path)
    pairs_cache: dict[str, str] = {}

    def match_pt_text(zht_begin: Decimal, zht_end: Decimal) -> str:
        # Prefer PT whose begin falls within the ZHT interval
        for begin_pt, end_pt, text_pt in pt_entries:
            if begin_pt >= zht_begin and begin_pt <= zht_end:
                return text_pt
        # Otherwise take any overlapping interval
        for begin_pt, end_pt, text_pt in pt_entries:
            if (end_pt >= zht_begin) and (begin_pt <= zht_end):
                return text_pt
        return "N/A"

    p_nodes = list(_iter_p_elements(root))
    total_nodes = len(p_nodes)
    for idx, p in enumerate(p_nodes, start=1):
        begin_time = p.get("begin", "")
        end_time = p.get("end") or begin_time or ""
        text_content = _extract_text_content(p)
        # Skip empty lines (no text and no begin)
        if not begin_time and not text_content:
            continue
        # Determine PT translation match
        try:
            z_begin = _parse_seconds_value(begin_time or "0s")
            z_end = _parse_seconds_value(end_time or begin_time or "0s")
        except Exception:
            z_begin = Decimal(0)
            z_end = z_begin
        pt_text = match_pt_text(z_begin, z_end)
        # Fetch pairs for zht text (with simple cache)
        zht_norm = text_content
        if zht_norm in pairs_cache:
            pairs_str = pairs_cache[zht_norm]
        else:
            pairs_str = _call_deepseek_pairs(zht_norm)
            pairs_cache[zht_norm] = pairs_str
        # Use tab-separated fields for safety; insert pairs between zht and pt
        line = (
            f"{index_counter}\t{_sanitize_tsv_field(begin_time)}\t"
            f"{_sanitize_tsv_field(text_content)}\t{_sanitize_tsv_field(pairs_str)}\t"
            f"{_sanitize_tsv_field(pt_text)}"
        )
        lines.append(line)
        index_counter += 1
        _print_progress(idx, total_nodes, prefix="Gerando base/LLM")

    base_out_path = determine_base_output_path(zht_secs_path)
    base_out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return base_out_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert TTML tick timings to seconds (offset time)")
    parser.add_argument(
        "directory",
        help="Directory to search for 'zht' and 'pt' XML files and produce *_secs.xml outputs",
    )
    return parser.parse_args(argv)


def _select_unique(files: list[Path], label: str) -> Path:
    if not files:
        raise ValueError(f"Nenhum arquivo {label} encontrado")
    if len(files) > 1:
        # Provide deterministic choice guidance
        names = ", ".join(sorted(str(p) for p in files))
        raise ValueError(f"Mais de um arquivo {label} encontrado: {names}")
    return files[0]


def find_language_files(directory: Path) -> tuple[Path, Path]:
    """Find exactly one 'zht' and one 'pt' XML file under directory (recursive).

    Ignores files that already appear to be processed (contain '_secs' or '_real').
    Case-insensitive matching on substrings 'zht' and 'pt'.
    """
    if not directory.is_dir():
        raise ValueError(f"Diretório inválido: {directory}")

    all_xml = list(directory.rglob("*.xml"))
    if not all_xml:
        raise ValueError("Nenhum arquivo .xml encontrado no diretório informado")

    def is_candidate(path: Path) -> bool:
        name_lower = path.name.lower()
        return ("_secs" not in name_lower) and ("_real" not in name_lower)

    candidates = [p for p in all_xml if is_candidate(p)]

    zht_candidates = [p for p in candidates if re.search(r"zht", p.name, re.IGNORECASE)]
    # Simplify: substring 'pt' anywhere in the filename
    pt_candidates = [p for p in candidates if re.search(r"pt", p.name, re.IGNORECASE)]

    zht_file = _select_unique(zht_candidates, "com 'zht'")
    pt_file = _select_unique(pt_candidates, "com 'pt'")

    return zht_file, pt_file


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    # Load optional .env next to this script
    try:
        dotenv_path = Path(__file__).resolve().parent / ".env"
        if dotenv_path.exists():
            for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and (key not in os.environ):
                    os.environ[key] = value
    except Exception:
        pass
    # Interpret positional argument as a folder name inside local 'assets'
    assets_root = Path(__file__).resolve().parent / "assets"
    dir_path = (assets_root / args.directory).resolve()
    if not dir_path.exists() or not dir_path.is_dir():
        print(f"Erro: diretório dentro de 'assets' não encontrado: {dir_path}", file=sys.stderr)
        return 1
    try:
        zht_file, pt_file = find_language_files(dir_path)
    except Exception as exc:  # noqa: BLE001 - broad to surface CLI errors
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    try:
        zht_out = determine_output_path_secs(zht_file)
        process_file(zht_file, zht_out)
        print(f"Arquivo convertido: {zht_out}")

        pt_out = determine_output_path_secs(pt_file)
        process_file(pt_file, pt_out)
        print(f"Arquivo convertido: {pt_out}")

        base_txt = generate_zht_base_file(zht_out, pt_out)
        print(f"Arquivo base gerado: {base_txt}")
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao processar: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))



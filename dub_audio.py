#!/usr/bin/env python3
"""Gera uma faixa de dublagem em mandarim de Taiwan (MP3) a partir do *_base.txt.

Uso: python3 dub_audio.py <asset> [--single-voice] [--force] [--no-upload]

Pensado para séries originais em português (Próxima, Esplendor...): o
processor.py já traduziu cada fala para chinês tradicional e gravou a coluna
``zht`` do base. Este script fala esse ``zht`` com o edge-tts (vozes zh-TW) e
coloca cada fala no MESMO instante da fala original, gerando
``assets/<asset>/<asset>_dub_zht.mp3`` com a duração do vídeo original.

A queima não muda: o MP3 é um arquivo a mais, que vai para o Drive na mesma
pasta do _merged.mp4 (merge_chunks.upload_to_drive), com marcador próprio
``<asset>_dub_drive.json``. Atenção: se a queima usa o modo com pausas, o
_merged.mp4 fica mais longo e o MP3 só sincroniza com o vídeo ORIGINAL.

Etapas:
  1. Gênero por fala: piso do pitch (F0, 25º percentil) do áudio original no trecho da
     fala → voz masculina ou feminina (sem diarização; o edge-tts só tem uma
     voz masculina zh-TW). ``--single-voice`` pula isso.
  2. TTS por fala com cache em assets/<asset>/dub_zht/ (resumível).
  3. Encaixe: a fala precisa caber até o início da próxima. Se não cabe,
     regenera com rate maior (até +MAX_RATE%); se ainda não cabe, corta com
     fade-out.
  4. Mixagem em numpy sobre uma faixa silenciosa; ffmpeg codifica o MP3.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import edge_tts

FEMALE_VOICE = "zh-TW-HsiaoChenNeural"
MALE_VOICE = "zh-TW-YunJheNeural"
F0_THRESHOLD = 165.0      # Hz: abaixo → masculino
SR = 16000                # taxa do wav de análise
OUT_SR = 24000            # taxa da faixa final (a do edge-tts)
GAP = 0.08                # folga (s) antes da próxima fala
MAX_RATE = 40             # aceleração máxima do edge-tts (%)
FADE_MS = 150
CONCURRENCY = 4
SKIP_SUFFIXES = ("_chromecast", "_merged", "_processed", "_chunk")


# --------------------------------------------------------------------- entradas

def find_base(asset_dir: Path) -> Path | None:
    cands = sorted(asset_dir.rglob("*_base.txt"))
    if not cands:
        return None
    zht = [c for c in cands if "zht" in c.name]
    return (zht or cands)[0]


def find_video(asset_dir: Path) -> Path | None:
    own = asset_dir / f"{asset_dir.name}.mp4"
    if own.exists():
        return own
    cands = [m for m in sorted(asset_dir.glob("*.mp4"))
             if not any(s in m.name for s in SKIP_SUFFIXES)]
    return cands[0] if cands else None


def _secs(s: str) -> float:
    return float(s.strip().rstrip("s"))


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[♪♫♬\[\]【】()（）]", "", text)
    text = text.replace("…", "，")
    return re.sub(r"\s+", " ", text).strip()


def parse_base(path: Path) -> list[dict]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.split("\t")
        if len(parts) < 4:
            continue
        try:
            begin, end = _secs(parts[1]), _secs(parts[2])
        except ValueError:
            continue
        text = clean_text(parts[3])
        if not text or text.upper() == "N/A" or not re.search(r"[一-鿿]", text):
            continue
        lines.append({"n": int(parts[0]) if parts[0].strip().isdigit() else len(lines) + 1,
                      "begin": begin, "end": end, "text": text})
    lines.sort(key=lambda x: x["begin"])
    return lines


def probe_duration(video: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ----------------------------------------------------------------------- gênero

def load_pcm(path: Path, sr: int = SR) -> np.ndarray:
    """Decodifica qualquer áudio/vídeo para float32 mono via ffmpeg."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", str(sr), "-f", "s16le", "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="ignore")[-300:])
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def voice_f0(seg: np.ndarray) -> float | None:
    """F0 típico da voz (autocorrelação) nos frames com voz. None se não confiável.

    Usa o 25º percentil, não a mediana: exclamações sobem o pitch de uma voz
    masculina para a faixa feminina, e a autocorrelação às vezes dobra a
    oitava. O "piso" da fala separa os gêneros bem melhor.
    """
    frame, hop = int(0.04 * SR), int(0.02 * SR)
    if len(seg) < frame:
        return None
    n = 1 + (len(seg) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    frames = seg[idx] * np.hanning(frame)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    loud = rms > max(0.01, np.percentile(rms, 50))
    lo, hi = int(SR / 400), int(SR / 70)
    f0s = []
    for fr in frames[loud]:
        fr = fr - fr.mean()
        ac = np.fft.irfft(np.abs(np.fft.rfft(fr, 2 * frame)) ** 2)[:frame]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.45:
            f0s.append(SR / lag)
    if len(f0s) < 5:
        return None
    return float(np.percentile(f0s, 25))


def assign_genders(lines: list[dict], wav: np.ndarray) -> None:
    for ln in lines:
        a = int(ln["begin"] * SR)
        b = int(min(ln["end"], ln["begin"] + 8.0) * SR)
        ln["f0"] = voice_f0(wav[a:b]) if b > a else None
        ln["gender"] = None if ln["f0"] is None else ("M" if ln["f0"] < F0_THRESHOLD else "F")
    # Falas sem pitch confiável herdam da vizinha mais próxima.
    known = [i for i, ln in enumerate(lines) if ln["gender"]]
    for i, ln in enumerate(lines):
        if ln["gender"] is None:
            ln["gender"] = lines[min(known, key=lambda k: abs(k - i))]["gender"] if known else "F"


# -------------------------------------------------------------------------- TTS

def voice_for(ln: dict, args) -> str:
    if args.single_voice:
        return args.female_voice
    return args.male_voice if ln["gender"] == "M" else args.female_voice


def load_tts(path: Path) -> np.ndarray:
    """PCM da fala sem o silêncio que o edge-tts põe no início e no fim."""
    pcm = load_pcm(path, OUT_SR)
    voiced = np.nonzero(np.abs(pcm) > 10 ** (-45 / 20))[0]
    return pcm[voiced[0]:voiced[-1] + 1] if len(voiced) else pcm


async def tts(text: str, voice: str, rate: int, out: Path, sem: asyncio.Semaphore) -> bool:
    if out.exists() and out.stat().st_size > 0:
        return True
    async with sem:
        for attempt in range(4):
            tmp = out.with_suffix(".part")
            try:
                await edge_tts.Communicate(text, voice, rate=f"+{rate}%").save(str(tmp))
                if tmp.exists() and tmp.stat().st_size > 0:
                    tmp.rename(out)
                    return True
            except Exception as e:  # noqa: BLE001 - rede: tenta de novo
                if attempt == 3:
                    print(f"   ❌ TTS falhou ({out.name}): {e}")
            tmp.unlink(missing_ok=True)
            await asyncio.sleep(2 * (attempt + 1))
    return False


def cache_path(cache: Path, ln: dict, voice: str, rate: int) -> Path:
    vkey = voice.split("-")[2].replace("Neural", "")
    return cache / f"line_{ln['n']:04d}_{vkey}_r{rate:02d}.mp3"


async def synthesize(lines: list[dict], cache: Path, args) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(ln, rate):
        p = cache_path(cache, ln, ln["voice"], rate)
        ok = await tts(ln["text"], ln["voice"], rate, p, sem)
        return p if ok else None

    # 1ª passada: velocidade normal.
    paths = await asyncio.gather(*(one(ln, 0) for ln in lines))
    redo = []
    for ln, p in zip(lines, paths):
        ln["rate"], ln["audio"] = 0, None
        if p is None:
            continue
        seg = load_tts(p)
        ln["audio"] = seg
        need = len(seg) / OUT_SR / ln["slot"] if ln["slot"] > 0 else 99
        if need > 1.0:
            ln["rate"] = min(MAX_RATE, int(math.ceil((need - 1) * 100)) + 5)
            redo.append(ln)

    # 2ª passada: regenera acelerado as falas que não cabem.
    if redo:
        print(f"   ⏩ {len(redo)} fala(s) não cabem na janela — regenerando acelerado")
        paths = await asyncio.gather(*(one(ln, ln["rate"]) for ln in redo))
        for ln, p in zip(redo, paths):
            if p is not None:
                ln["audio"] = load_tts(p)


# ------------------------------------------------------------------------ drive

def upload(out: Path, asset: str, force: bool) -> None:
    marker = out.parent / f"{asset}_dub_drive.json"
    if marker.exists() and not force:
        print(f"☁️  Dublagem já enviada ao Drive ({marker.name})")
        return
    from merge_chunks import upload_to_drive
    if not upload_to_drive(out, asset, marker_suffix="dub_drive"):
        print("⚠️  Envio da dublagem ao Drive falhou — o MP3 local está pronto")


# ------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("asset")
    ap.add_argument("--single-voice", action="store_true", help="uma voz só (sem detecção de gênero)")
    ap.add_argument("--female-voice", default=FEMALE_VOICE)
    ap.add_argument("--male-voice", default=MALE_VOICE)
    ap.add_argument("--force", action="store_true", help="refaz o MP3 e reenvia ao Drive (o cache de TTS é mantido)")
    ap.add_argument("--no-upload", action="store_true", help="não envia ao Drive")
    args = ap.parse_args()

    asset_dir = Path("assets") / args.asset
    if not asset_dir.is_dir():
        print(f"❌ Diretório não encontrado: {asset_dir}")
        return 1
    out = asset_dir / f"{args.asset}_dub_zht.mp3"
    drive_on = not args.no_upload and os.environ.get("DRIVE_UPLOAD", "1") != "0"

    if out.exists() and out.stat().st_size > 0 and not args.force:
        print(f"✓ Dublagem já existe: {out}")
        if drive_on:
            upload(out, args.asset, False)
        return 0

    base = find_base(asset_dir)
    if base is None:
        print(f"❌ Nenhum *_base.txt em {asset_dir}")
        return 1
    video = find_video(asset_dir)
    lines = parse_base(base)
    if not lines:
        print(f"❌ Nenhuma fala zht em {base.name}")
        return 1

    total = probe_duration(video) if video else 0.0
    if total <= 0:
        total = max(ln["end"] for ln in lines) + 2.0
    print(f"🎙️  Dublagem zh-TW: {args.asset}")
    print(f"   base:  {base.relative_to(asset_dir)} ({len(lines)} falas)")
    print(f"   vídeo: {video.name if video else '— (sem vídeo: duração pelo base)'} ({total:.1f}s)")

    for i, ln in enumerate(lines):
        nxt = lines[i + 1]["begin"] if i + 1 < len(lines) else total
        ln["slot"] = max(0.0, min(nxt, total) - ln["begin"] - GAP)

    if args.single_voice or video is None:
        for ln in lines:
            ln["gender"], ln["f0"] = "F", None
    else:
        print("   🔎 Detectando gênero pelo pitch do áudio original...")
        assign_genders(lines, load_pcm(video))
    for ln in lines:
        ln["voice"] = voice_for(ln, args)

    cache = asset_dir / "dub_zht"
    cache.mkdir(exist_ok=True)
    print(f"   🗣️  Gerando TTS (cache em {cache.name}/)...")
    asyncio.run(synthesize(lines, cache, args))

    mix = np.zeros(int(total * OUT_SR) + 1, dtype=np.float32)
    sped = cut = missing = 0
    for ln in lines:
        seg = ln["audio"]
        if seg is None:
            missing += 1
            continue
        if ln["rate"]:
            sped += 1
        slot = max(1, int(ln["slot"] * OUT_SR))
        if len(seg) > slot:
            cut += 1
            seg = seg[:slot].copy()
            nf = min(len(seg), int(FADE_MS / 1000 * OUT_SR))
            seg[len(seg) - nf:] *= np.linspace(1.0, 0.0, nf, dtype=np.float32)
        a = int(ln["begin"] * OUT_SR)
        seg = seg[:max(0, len(mix) - a)]
        mix[a:a + len(seg)] += seg
    pcm16 = (np.clip(mix, -1.0, 1.0) * 32767).astype(np.int16)

    tmp = out.with_name(out.name + ".part")
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(OUT_SR), "-ac", "1",
                        "-i", "-", "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "-y", str(tmp)],
                       input=pcm16.tobytes(), capture_output=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        print(f"❌ Falha ao gerar o MP3: {r.stderr.decode(errors='ignore')[-300:]}")
        return 1
    tmp.rename(out)

    nm = sum(1 for ln in lines if ln["gender"] == "M")
    print(f"\n✅ {out} ({out.stat().st_size / 1e6:.1f} MB, {total / 60:.1f} min)")
    print(f"   falas: {len(lines)} | masculinas: {nm} | femininas: {len(lines) - nm}")
    print(f"   aceleradas: {sped} | cortadas: {cut} ({cut / len(lines):.1%}) | sem áudio: {missing}")

    if drive_on:
        upload(out, args.asset, args.force)
    return 0 if missing == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

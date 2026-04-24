"""
Transcritor de vídeo local usando OpenAI Whisper
------------------------------------------------
Instalação (rode uma vez):
    pip install openai-whisper
    # Windows: instale o ffmpeg em https://ffmpeg.org/download.html
    # Mac:     brew install ffmpeg
    # Linux:   sudo apt install ffmpeg

Uso:
    python transcriber.py meu_video.mp4
    python transcriber.py meu_video.mp4 --output transcript.txt
    python transcriber.py meu_video.mp4 --model medium
    python transcriber.py meu_video.mp4 --chunk-minutes 10
    python transcriber.py meu_video.mp4 --no-parallel
"""

import sys
import argparse
import json
import multiprocessing
import os
import subprocess
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------

def get_duration(video_path: str) -> float:
    """Returns video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        video_path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        info = json.loads(out)
        return float(info["format"]["duration"])
    except Exception as e:
        print(f"❌ Erro ao obter duração do vídeo: {e}")
        print("   Verifique se o ffprobe está instalado (vem junto com o ffmpeg).")
        sys.exit(1)


def detect_silences(video_path: str, min_silence_len: float = 0.5, noise_floor: int = -35) -> list[float]:
    """
    Detects silence timestamps using ffmpeg's silencedetect filter.
    Returns a sorted list of silence midpoints (in seconds).
    """
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=noise={noise_floor}dB:d={min_silence_len}",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stderr
    except FileNotFoundError:
        print("❌ ffmpeg não encontrado. Instale o ffmpeg e tente novamente.")
        sys.exit(1)

    silences = []
    start = None
    for line in output.splitlines():
        if "silence_start" in line:
            try:
                start = float(line.split("silence_start:")[1].strip())
            except (IndexError, ValueError):
                pass
        elif "silence_end" in line and start is not None:
            try:
                end = float(line.split("silence_end:")[1].split("|")[0].strip())
                silences.append((start + end) / 2)  # midpoint of silence
                start = None
            except (IndexError, ValueError):
                pass

    return sorted(silences)


def find_best_cut(silences: list[float], target: float, window: float = 60.0) -> float:
    """
    Finds the silence midpoint closest to `target` within +-window seconds.
    Falls back to exact target if no silence found in window.
    """
    candidates = [s for s in silences if abs(s - target) <= window]
    if not candidates:
        return target
    return min(candidates, key=lambda s: abs(s - target))


def build_chunks(duration: float, chunk_seconds: float, overlap: float, silences: list[float]) -> list[tuple[float, float]]:
    """
    Splits the video into (start, end) pairs aligned to silence points.
    Each chunk overlaps the next by `overlap` seconds as safety margin.
    """
    chunks = []
    start = 0.0

    while start < duration:
        raw_end = start + chunk_seconds
        if raw_end >= duration:
            chunks.append((start, duration))
            break

        # Snap end to nearest silence within +-60s of the target
        end = find_best_cut(silences, raw_end, window=60.0)
        end = min(end, duration)

        # Extend end by overlap so the next chunk has context
        extended_end = min(end + overlap, duration)
        chunks.append((start, extended_end))

        # Next chunk starts at the clean cut (no overlap on the start side)
        start = end

    return chunks


def extract_audio_chunk(args: tuple) -> tuple[int, str]:
    """
    Extracts a chunk of audio from the video as a temp WAV file.
    Returns (index, temp_file_path).
    """
    video_path, start, end, tmp_dir, index = args
    out_path = os.path.join(tmp_dir, f"chunk_{index:04d}.wav")
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-ac", "1",       # mono
        "-ar", "16000",   # 16kHz (Whisper native rate)
        "-vn",            # no video
        out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return index, out_path


# ---------------------------------------------------------------------------
# Whisper worker (runs in a separate process)
# ---------------------------------------------------------------------------

def transcribe_chunk(args: tuple) -> tuple[int, str]:
    """
    Transcribes a single audio chunk. Designed to run in a worker process.
    Returns (index, transcript_text).
    """
    index, audio_path, model_name = args
    import whisper  # imported inside worker to avoid pickling issues
    model = whisper.load_model(model_name)
    result = model.transcribe(
        audio_path,
        language="en",
        verbose=False,
        fp16=False,
    )
    return index, result["text"].strip()


# ---------------------------------------------------------------------------
# Overlap deduplication
# ---------------------------------------------------------------------------

def deduplicate_overlap(texts: list[str], overlap_words: int = 30) -> str:
    """
    Joins chunk transcripts removing duplicated text from overlapping regions.
    Compares the tail of the previous chunk with the head of the next one
    and finds the best joining point using a sliding window.
    """
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0]

    merged = texts[0]
    for next_text in texts[1:]:
        merged_words = merged.split()
        next_words = next_text.split()

        best_cut = 0
        best_score = -1

        # Slide a window of `overlap_words` over the tail of merged
        tail = merged_words[-overlap_words:]
        for i in range(len(next_words)):
            head = next_words[i: i + overlap_words]
            # Count matching words between tail and head
            matches = sum(a == b for a, b in zip(tail, head))
            if matches > best_score:
                best_score = matches
                best_cut = i

        # Only deduplicate if we found a reasonable match
        if best_score >= max(3, overlap_words // 5):
            merged = " ".join(merged_words) + " " + " ".join(next_words[best_cut + overlap_words:])
        else:
            merged = " ".join(merged_words) + " " + next_text

    return merged.strip()


# ---------------------------------------------------------------------------
# Main transcription logic
# ---------------------------------------------------------------------------

def transcribe(video_path: str, model_name: str, output_path: str | None,
               chunk_minutes: int, use_parallel: bool):
    try:
        import whisper  # noqa: F401 — validate install early
    except ImportError:
        print("❌ Whisper não encontrado. Instale com:")
        print("   pip install openai-whisper")
        sys.exit(1)

    video = Path(video_path)
    if not video.exists():
        print(f"❌ Arquivo não encontrado: {video_path}")
        sys.exit(1)

    # --- Determine worker count ---
    total_cores = multiprocessing.cpu_count()
    workers = max(1, total_cores // 2)
    print(f"💻 Núcleos detectados: {total_cores} → usando {workers} workers")

    # --- Get duration ---
    duration = get_duration(str(video))
    chunk_seconds = chunk_minutes * 60
    overlap = 30.0  # seconds of safety overlap between chunks

    print(f"⏱️  Duração do vídeo: {duration / 60:.1f} min")

    # Short videos: skip chunking entirely
    if duration <= chunk_seconds:
        print("📹 Vídeo curto — transcrevendo diretamente sem chunks.")
        print(f"⏳ Carregando modelo '{model_name}'...")
        import whisper
        model = whisper.load_model(model_name)
        result = model.transcribe(str(video), language="en", verbose=False, fp16=False)
        transcript = result["text"].strip()
    else:
        # --- Detect silences for smart cuts ---
        print("🔇 Detectando silêncios para cortes inteligentes...")
        silences = detect_silences(str(video))
        print(f"   {len(silences)} pontos de silêncio encontrados.")

        # --- Build chunks ---
        chunks = build_chunks(duration, chunk_seconds, overlap, silences)
        print(f"✂️  Vídeo dividido em {len(chunks)} chunks (~{chunk_minutes} min cada)")

        with tempfile.TemporaryDirectory() as tmp_dir:
            # --- Extract audio chunks ---
            print("🎵 Extraindo áudio dos chunks...")
            extract_args = [
                (str(video), start, end, tmp_dir, i)
                for i, (start, end) in enumerate(chunks)
            ]
            # Audio extraction is I/O bound — safe to use all cores
            with multiprocessing.Pool(processes=min(workers * 2, total_cores)) as pool:
                chunk_files_unordered = pool.map(extract_audio_chunk, extract_args)
            chunk_files = [path for _, path in sorted(chunk_files_unordered)]

            # --- Transcribe in parallel ---
            if use_parallel and workers > 1:
                print(f"🚀 Transcrevendo {len(chunks)} chunks em paralelo ({workers} workers)...")
            else:
                workers = 1
                print(f"🔄 Transcrevendo {len(chunks)} chunks sequencialmente...")

            transcribe_args = [
                (i, audio_path, model_name)
                for i, audio_path in enumerate(chunk_files)
            ]

            results_unordered = []
            with multiprocessing.Pool(processes=workers) as pool:
                for idx, text in pool.imap_unordered(transcribe_chunk, transcribe_args):
                    results_unordered.append((idx, text))
                    print(f"   ✓ Chunk {idx + 1}/{len(chunks)} concluído")

        # Sort results by chunk index and deduplicate overlaps
        ordered_texts = [text for _, text in sorted(results_unordered)]
        print("🔗 Juntando chunks e removendo sobreposições...")
        transcript = deduplicate_overlap(ordered_texts)

    # --- Output ---
    print("\n" + "=" * 60)
    print("TRANSCRIPT")
    print("=" * 60)
    print(transcript)
    print("=" * 60 + "\n")

    if output_path is None:
        output_path = video.stem + "_transcript.txt"

    Path(output_path).write_text(transcript, encoding="utf-8")
    print(f"✅ Transcript salvo em: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Transcreve vídeo local para inglês usando Whisper com chunks paralelos."
    )
    parser.add_argument("video", help="Caminho do arquivo de vídeo (mp4, mkv, etc.)")
    parser.add_argument(
        "--model",
        default="large",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Modelo Whisper (padrão: large)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Arquivo de saída (padrão: <nome_do_video>_transcript.txt)",
    )
    parser.add_argument(
        "--chunk-minutes",
        type=int,
        default=10,
        help="Tamanho alvo de cada chunk em minutos (padrão: 10)",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="Desativa paralelismo (processa chunks sequencialmente)",
    )
    args = parser.parse_args()

    transcribe(
        video_path=args.video,
        model_name=args.model,
        output_path=args.output,
        chunk_minutes=args.chunk_minutes,
        use_parallel=not args.no_parallel,
    )


if __name__ == "__main__":
    main()
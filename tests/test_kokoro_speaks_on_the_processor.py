# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1728` — Kokoro speaks on this server's own processor, with no GPU.

The owner, 2026-11-01: *"Need something for realistic voice synthesis for the
LLM's response back to the user (toggleable)"*, and on the card that followed,
*"Kokoro, plus Chatterbox for a GPU"*. Kokoro-82M runs here exported to ONNX,
on the ONNX Runtime Piper already brings, and its phonemes come from the
espeak-ng Piper already carries (`services/tts/kokoro_cpu.py`).

Driven (`Law 20`) through the module's own functions. The stand-ins are the
model's session (no 325 MB model in CI) and, where said, espeak; the real
espeak and the real model are used whenever they are installed, and the model
is found where Pantheon looks for it (`PANTHEON_SEED_MODELS/kokoro`, as the
image bakes it).
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import random
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from services.tts import kokoro_cpu as K

ROOT = Path(__file__).resolve().parents[1]


def _wav(data: bytes):
    with wave.open(io.BytesIO(data)) as wf:
        frames = wf.readframes(wf.getnframes())
        return {"rate": wf.getframerate(), "channels": wf.getnchannels(),
                "width": wf.getsampwidth(), "frames": wf.getnframes(),
                "samples": np.frombuffer(frames, dtype="<i2")}


# ── Phonemes ──


class _Espeak:
    """`piper.espeakbridge`, answering each text with the clauses given."""

    def __init__(self, clauses):
        self.clauses = clauses
        self.initialized: list = []
        self.voices: list = []
        self.texts: list = []

    def initialize(self, path):
        self.initialized.append(path)

    def set_voice(self, language):
        self.voices.append(language)

    def get_phonemes(self, text):
        self.texts.append(text)
        return self.clauses


@pytest.fixture()
def espeak(monkeypatch):
    bridge = _Espeak([])
    piper = types.ModuleType("piper")
    piper.espeakbridge = bridge
    data = types.ModuleType("piper.phonemize_espeak")
    data.ESPEAK_DATA_DIR = "/espeak-data"
    monkeypatch.setitem(sys.modules, "piper", piper)
    monkeypatch.setitem(sys.modules, "piper.espeakbridge", bridge)
    monkeypatch.setitem(sys.modules, "piper.phonemize_espeak", data)
    monkeypatch.setattr(K, "_espeak_ready", False)
    return bridge


def test_phonemes_keep_each_clause_and_its_mark_and_drop_what_kokoro_cannot_read(espeak):
    espeak.clauses = [
        ("həlˈoʊ", ".", True),
        # A language switch espeak marks, the palatal mark Piper's espeak
        # adds, a symbol outside the vocabulary, and doubled spaces.
        ("(en)ðˈɛɹ(fr)  wˈʌnʲ  ☃tˈuː", "?", True),
        # A clause espeak ended with no mark (an ellipsis) is still its own.
        ("ənd", "", False),
        ("", "", True),
    ]
    out = K.phonemize("Hello. There one two? And", "en-gb-x-rp")
    assert out == ["həlˈoʊ.", "ðˈɛɹ wˈʌn tˈuː?", "ənd"]
    assert all(c in K.VOCAB for clause in out for c in clause)
    assert espeak.voices == ["en-gb-x-rp"]
    assert espeak.initialized == ["/espeak-data"], "espeak is set up once, where Piper keeps its data"
    K.phonemize("Again.", "es")
    assert espeak.initialized == ["/espeak-data"], "and not again"
    assert espeak.voices == ["en-gb-x-rp", "es"]


def test_nothing_to_say_never_reaches_espeak(espeak):
    assert K.phonemize("   ") == []
    assert K.phonemize(None) == []
    assert espeak.texts == [] and espeak.initialized == []


def test_the_espeak_piper_carries_speaks_every_language_kokoro_is_offered_in(monkeypatch):
    pytest.importorskip("piper.espeakbridge")
    monkeypatch.setattr(K, "_espeak_ready", K._espeak_ready)
    said = {
        "en-us": "Hello there. How are you today?",
        "en-gb-x-rp": "Good morning, how do you do?",
        "es": "Hola, ¿qué tal?",
        "fr": "Bonjour, comment ça va ?",
        "hi": "नमस्ते, आप कैसे हैं?",
        "it": "Ciao, come stai?",
        "pt-br": "Olá, tudo bem?",
    }
    assert set(said) == {code for code, _name in K.LANGUAGES.values()}
    for code, text in said.items():
        clauses = K.phonemize(text, code)
        assert clauses, (code, "espeak gave nothing")
        assert all(c in K.VOCAB for clause in clauses for c in clause), (code, clauses)
    english = K.phonemize("Hello there. How are you today?", "en-us")
    assert len(english) == 2 and english[0].endswith(".") and english[1].endswith("?"), english


# ── Batches ──


def test_clauses_are_joined_into_runs_the_model_can_read_whole():
    assert K.batches(["ab", "cd"], limit=5) == ["ab cd"]
    assert K.batches(["abc", "def"], limit=5) == ["abc", "def"]
    # A clause too long for one run is cut at its spaces.
    assert K.batches(["aa bb cc dd"], limit=5) == ["aa bb", "cc dd"]
    # And a "word" too long for one (no word is) at the limit.
    assert K.batches(["abcdefghijkl"], limit=5) == ["abcde", "fghij", "kl"]
    assert K.batches([]) == []


def test_no_run_is_longer_than_the_model_reads_and_nothing_is_lost():
    rng = random.Random(1727)
    letters = "abcdeɪəʊ"
    for _ in range(200):
        clauses = [" ".join("".join(rng.choice(letters) for _ in range(rng.randint(1, 9)))
                            for _ in range(rng.randint(1, 30))) + rng.choice(".,?!")
                   for _ in range(rng.randint(1, 12))]
        limit = rng.randint(12, 80)
        runs = K.batches(clauses, limit)
        assert all(0 < len(r) <= limit for r in runs), (limit, runs)
        assert " ".join(runs).split() == " ".join(clauses).split()
    assert K.MAX_TOKENS == 510, "the model's 512 tokens, less the two pads"


# ── The engine, with a stand-in for the model ──


class _Input:
    def __init__(self, name):
        self.name, self.type = name, "tensor(int64)"


class _Session:
    """ONNX Runtime's session, as far as Kokoro reaches it: each run answers
    one sample per token, valued by its run's number."""

    def __init__(self, path, tokens_name="input_ids"):
        self.path = path
        self.feeds: list = []
        self._inputs = [_Input(tokens_name), _Input("style"), _Input("speed")]
        self._tokens = tokens_name

    def get_inputs(self):
        return self._inputs

    def run(self, _outputs, feed):
        self.feeds.append(feed)
        n = feed[self._tokens].shape[1]
        return [np.full((1, n * 10), 0.1 * len(self.feeds), dtype=np.float32)]


def _voices_file(path: Path, rows: int = 8) -> Path:
    """A voices file of the real one's shape, smaller: each voice a table
    of styles by length, row i holding i (so a test can see which was read)."""
    table = np.stack([np.full((1, 4), float(i), dtype=np.float32) for i in range(rows)])
    with open(path, "wb") as f:   # a file object: `savez` would add ".npz" to a name
        np.savez(f, af_heart=table, bf_emma=table + 100)
    return path


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    spoken = []

    def phonemes(text, language="en-us"):
        spoken.append((text, language))
        return {"Hi.": ["hˈaɪ."], "Two.": ["tˈuː.", "θɹˈiː!"], "Mute.": [],
                "Long.": ["a" * 20]}.get(text, ["ə"])

    monkeypatch.setattr(K, "phonemize", phonemes)
    model = tmp_path / K.KOKORO_MODEL
    model.write_bytes(b"onnx")
    voices = _voices_file(tmp_path / K.KOKORO_VOICES)
    made = []

    def factory(path, tokens_name="input_ids"):
        made.append(_Session(path, tokens_name))
        return made[-1]

    eng = K.KokoroEngine(session_factory=factory, files=lambda: (model, voices))
    return types.SimpleNamespace(engine=eng, made=made, spoken=spoken, model=model, voices=voices,
                                 factory=factory)


def test_one_run_is_the_tokens_between_two_pads_with_the_style_for_its_length(engine):
    wav = _wav(engine.engine.synthesize("Hi.", "af_heart", 1.0))
    (feed,) = engine.made[0].feeds
    tokens = [K.VOCAB[c] for c in "hˈaɪ."]
    assert feed["input_ids"].dtype == np.int64
    assert feed["input_ids"].tolist() == [[0, *tokens, 0]]
    assert feed["style"].shape == (1, 4)
    assert feed["style"][0][0] == len(tokens) - 1, "a run of n tokens reads the style row n - 1"
    assert feed["speed"].tolist() == [1.0] and feed["speed"].dtype == np.float32
    assert (wav["rate"], wav["channels"], wav["width"]) == (24000, 1, 2)
    assert wav["frames"] == len(tokens) * 10 + 20


def test_two_runs_are_said_with_a_short_breath_between(engine, monkeypatch):
    monkeypatch.setattr(K, "batches", lambda clauses, limit=K.MAX_TOKENS: list(clauses))
    wav = _wav(engine.engine.synthesize("Two.", "af_heart"))
    first, second = engine.made[0].feeds
    gap = int(24000 * 0.08)
    n1, n2 = first["input_ids"].shape[1] * 10, second["input_ids"].shape[1] * 10
    assert wav["frames"] == n1 + gap + n2
    s = wav["samples"]
    assert np.all(s[n1:n1 + gap] == 0), "silence between the two"
    assert s[0] == int(0.1 * 32767) and s[-1] == int(0.2 * 32767)


def test_a_voice_speaks_its_own_language_and_a_name_it_does_not_have_is_heart(engine):
    engine.engine.synthesize("Hi.", "bf_emma")
    assert engine.spoken[-1] == ("Hi.", "en-gb-x-rp")
    assert engine.made[0].feeds[-1]["style"][0][0] == 100 + len("hˈaɪ.") - 1, "Emma's own styles"
    engine.engine.synthesize("Hi.", "alloy")   # the shared setting's default, an OpenAI voice
    assert engine.spoken[-1] == ("Hi.", "en-us")
    assert engine.made[0].feeds[-1]["style"][0][0] == len("hˈaɪ.") - 1, "Heart's"
    assert K.kokoro_voice("  bm_george ") == "bm_george"
    assert K.kokoro_voice("en_US-ljspeech-medium") == K.KOKORO_DEFAULT_VOICE == "af_heart"


def test_a_run_longer_than_the_voice_table_reads_its_last_row(engine):
    engine.engine.synthesize("Long.", "af_heart")
    assert engine.made[0].feeds[-1]["style"][0][0] == 7, "the table has 8 rows"


@pytest.mark.parametrize(("asked", "said"), [(5, 2.0), (0.1, 0.5), (1.25, 1.25), (None, 1.0), (0, 1.0)])
def test_speed_is_held_between_half_and_twice(engine, asked, said):
    engine.engine.synthesize("Hi.", "af_heart", asked)
    assert engine.made[0].feeds[-1]["speed"].tolist() == [pytest.approx(said)]


def test_the_model_loads_once_and_only_when_there_is_something_to_say(engine):
    assert engine.engine.synthesize("Mute.") is None
    assert engine.made == [] and not engine.engine.loaded(), "nothing to say loads nothing"
    engine.engine.synthesize("Hi.")
    engine.engine.synthesize("Two.")
    assert len(engine.made) == 1 and engine.engine.loaded()
    assert engine.made[0].path == str(engine.model)


def test_an_older_export_that_names_its_tokens_tokens_is_spoken_too(engine):
    eng = K.KokoroEngine(session_factory=lambda p: engine.factory(p, "tokens"),
                         files=lambda: (engine.model, engine.voices))
    assert eng.synthesize("Hi.") is not None
    assert "tokens" in engine.made[-1].feeds[0] and "input_ids" not in engine.made[-1].feeds[0]


def test_a_voices_file_that_is_not_arrays_is_refused_not_run(engine, tmp_path):
    bad = tmp_path / "pickled.bin"
    with open(bad, "wb") as f:
        np.save(f, np.array([{"af_heart": "code"}], dtype=object), allow_pickle=True)
    eng = K.KokoroEngine(session_factory=engine.factory, files=lambda: (engine.model, bad))
    with pytest.raises(ValueError):
        eng.synthesize("Hi.")
    assert not eng.loaded()


def test_warming_says_why_it_could_not_and_does_not_raise(tmp_path):
    def missing():
        raise FileNotFoundError("no model here")
    eng = K.KokoroEngine(session_factory=lambda p: None, files=missing)
    eng.warm()
    assert not eng.loaded()


# ── Where the model is, and how it arrives ──


def _sparse(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    return path


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    import src.constants as constants
    data, seed = tmp_path / "data", tmp_path / "seed"
    monkeypatch.setattr(constants, "DATA_DIR", str(data))
    monkeypatch.setenv("PANTHEON_SEED_MODELS", str(seed))
    return types.SimpleNamespace(here=data / "models" / "kokoro", seed=seed / "kokoro")


def test_the_model_is_found_in_the_data_folder_first_then_where_the_image_baked_it(dirs):
    assert K.kokoro_dirs() == [dirs.here, dirs.seed]
    assert K.find_kokoro_files() is None
    for name, (_sha, size) in K.KOKORO_FILES.items():
        _sparse(dirs.seed / name, size)
    assert K.find_kokoro_files() == (dirs.seed / K.KOKORO_MODEL, dirs.seed / K.KOKORO_VOICES)
    for name, (_sha, size) in K.KOKORO_FILES.items():
        _sparse(dirs.here / name, size)
    assert K.find_kokoro_files() == (dirs.here / K.KOKORO_MODEL, dirs.here / K.KOKORO_VOICES)


def test_a_file_cut_short_is_no_model_and_a_smaller_export_put_there_by_hand_is_one(dirs):
    _sparse(dirs.here / K.KOKORO_VOICES, K.KOKORO_FILES[K.KOKORO_VOICES][1])
    _sparse(dirs.here / K.KOKORO_MODEL, 1000)   # a full disk's model
    assert K.find_kokoro_files() is None
    (dirs.here / "kokoro-v1.0.int8.onnx").write_bytes(b"int8")
    assert K.find_kokoro_files() == (dirs.here / "kokoro-v1.0.int8.onnx", dirs.here / K.KOKORO_VOICES)
    (dirs.here / "kokoro-v1.0.fp16.onnx").write_bytes(b"fp16")
    assert K.find_kokoro_files()[0].name == "kokoro-v1.0.fp16.onnx", "half precision before 8-bit"
    _sparse(dirs.here / K.KOKORO_VOICES, 1000)   # and voices cut short are no voices
    assert K.find_kokoro_files() is None


def test_with_downloads_off_the_model_is_asked_for_in_a_sentence_and_nothing_is_fetched(dirs, monkeypatch):
    import src.embedding_lanes as lanes
    from src import paced_http
    calls = []
    monkeypatch.setattr(lanes, "model_download_allowed", lambda: False)
    monkeypatch.setattr(paced_http, "call_sync", lambda *a, **k: calls.append(a))
    with pytest.raises(lanes.ModelDownloadNotPermitted) as refused:
        K.ensure_kokoro_files()
    said = str(refused.value)
    assert "Download models from the internet" in said and "Settings → System" in said
    assert str(dirs.here) in said and K.KOKORO_MODEL in said and K.KOKORO_VOICES in said
    assert calls == [] and not dirs.here.exists()


def _small_files(monkeypatch):
    """`KOKORO_FILES` for two small files, so a fetch can arrive whole here."""
    bodies = {K.KOKORO_VOICES: b"the voices", K.KOKORO_MODEL: b"the model, smaller"}
    monkeypatch.setattr(K, "KOKORO_FILES", {
        name: (hashlib.sha256(body).hexdigest(), len(body)) for name, body in bodies.items()})
    return bodies


def test_with_downloads_on_both_files_come_from_github_paced_voices_first(dirs, monkeypatch):
    import src.embedding_lanes as lanes
    from src import paced_http
    bodies = _small_files(monkeypatch)
    asked = []

    def call_sync(host, fn, name, dest):
        asked.append((host, name))
        return fn(name, dest, download=lambda url, path: (
            asked.append(url), Path(path).write_bytes(bodies[name])))

    monkeypatch.setattr(lanes, "model_download_allowed", lambda: True)
    monkeypatch.setattr(paced_http, "call_sync", call_sync)
    assert K.ensure_kokoro_files() == (dirs.here / K.KOKORO_MODEL, dirs.here / K.KOKORO_VOICES)
    assert asked == [("github.com", K.KOKORO_VOICES), K.KOKORO_RELEASE + K.KOKORO_VOICES,
                     ("github.com", K.KOKORO_MODEL), K.KOKORO_RELEASE + K.KOKORO_MODEL]
    assert K.KOKORO_RELEASE.startswith("https://github.com/thewh1teagle/kokoro-onnx/releases/download/")
    assert sorted(p.name for p in dirs.here.iterdir()) == [K.KOKORO_MODEL, K.KOKORO_VOICES]
    asked.clear()
    assert K.ensure_kokoro_files()[0] == dirs.here / K.KOKORO_MODEL
    assert asked == [], "a model on disk costs no network"


def test_a_file_that_is_not_the_one_named_is_refused_and_leaves_nothing(tmp_path, monkeypatch):
    bodies = _small_files(monkeypatch)
    dest = tmp_path / "kokoro"
    wrong = bodies[K.KOKORO_MODEL][::-1]   # the right size, not the right bytes
    with pytest.raises(ValueError, match="is not the one Pantheon expects") as refused:
        K.fetch_kokoro_file(K.KOKORO_MODEL, dest,
                            download=lambda url, path: Path(path).write_bytes(wrong))
    assert "nothing was kept" in str(refused.value)
    assert list(dest.iterdir()) == []

    def cut_off(url, path):
        Path(path).write_bytes(bodies[K.KOKORO_MODEL][:5])
        raise ConnectionResetError("cut off")
    with pytest.raises(ConnectionResetError):
        K.fetch_kokoro_file(K.KOKORO_MODEL, dest, download=cut_off)
    assert list(dest.iterdir()) == [], "a fetch cut off leaves no part behind"
    got = K.fetch_kokoro_file(K.KOKORO_MODEL, dest,
                              download=lambda url, path: Path(path).write_bytes(bodies[K.KOKORO_MODEL]))
    assert got.read_bytes() == bodies[K.KOKORO_MODEL] and list(dest.iterdir()) == [got]


def test_the_hashes_written_are_the_real_files_when_they_are_here():
    found = K.find_kokoro_files()
    if found is None or found[0].name != K.KOKORO_MODEL:
        pytest.skip("Kokoro's model is not on this machine (PANTHEON_SEED_MODELS/kokoro)")
    for path in found:
        assert K._sha256(path) == K.KOKORO_FILES[path.name][0], path


# ── The image bakes it ──


@pytest.fixture()
def bake(tmp_path, monkeypatch):
    """`docker/bake_kokoro.py` beside a copy of `kokoro_cpu.py`, as the
    Dockerfile lays them out in /tmp/kokoro-bake."""
    folder = tmp_path / "kokoro-bake"
    folder.mkdir()
    for src in (ROOT / "docker" / "bake_kokoro.py", ROOT / "services" / "tts" / "kokoro_cpu.py"):
        (folder / src.name).write_bytes(src.read_bytes())
    monkeypatch.syspath_prepend(str(folder))
    saved = sys.modules.pop("kokoro_cpu", None)
    spec = importlib.util.spec_from_file_location("bake_kokoro", folder / "bake_kokoro.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield types.SimpleNamespace(mod=mod, folder=folder)
    sys.modules.pop("kokoro_cpu", None)
    if saved is not None:
        sys.modules["kokoro_cpu"] = saved


def test_the_bake_fetches_the_voices_then_the_model_through_the_checked_fetch(bake, tmp_path, monkeypatch):
    dest = tmp_path / "seed" / "kokoro"
    fetched = []
    assert bake.mod.bake(str(dest), fetch=lambda name, folder: fetched.append((name, folder))) == [
        K.KOKORO_VOICES, K.KOKORO_MODEL]
    assert fetched == [(K.KOKORO_VOICES, dest), (K.KOKORO_MODEL, dest)], "the model is found only beside its voices"
    beside = sys.modules["kokoro_cpu"]
    assert Path(beside.__file__).parent == bake.folder, "the module copied beside the script is the one used"
    fetched.clear()
    monkeypatch.setattr(beside, "fetch_kokoro_file", lambda name, folder: fetched.append(name))
    bake.mod.bake(str(dest))
    assert fetched == [K.KOKORO_VOICES, K.KOKORO_MODEL], "unless given, the module's own checked fetch"
    assert bake.mod.main([]) == 2, "no folder: the usage, and a failure"


def test_the_dockerfile_bakes_kokoro_where_the_voice_service_reads_it():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY docker/bake_kokoro.py /tmp/kokoro-bake/bake_kokoro.py" in text
    assert "COPY services/tts/kokoro_cpu.py /tmp/kokoro-bake/kokoro_cpu.py" in text
    run = text[text.index("python /tmp/kokoro-bake/bake_kokoro.py"):]
    run = run[:run.index("rm -rf /tmp/kokoro-bake") + 1]
    assert '"$PANTHEON_SEED_MODELS/kokoro"' in run
    for name in (K.KOKORO_MODEL, K.KOKORO_VOICES):
        assert f'test -f "$PANTHEON_SEED_MODELS/kokoro/{name}"' in run, name
    before = text[:text.index("python /tmp/kokoro-bake/bake_kokoro.py")]
    gate = before[before.rindex("RUN "):]
    assert "BAKE_MODELS" in gate and "INSTALL_VOICE" in gate, "baked only where models and voice are"


# ── The real model, when it is here ──


@pytest.fixture(scope="module")
def real():
    pytest.importorskip("piper.espeakbridge")
    pytest.importorskip("onnxruntime")
    found = K.find_kokoro_files()
    if found is None:
        pytest.skip("Kokoro's model is not on this machine (PANTHEON_SEED_MODELS/kokoro)")
    return K.KokoroEngine()


def test_every_voice_offered_is_in_the_real_voices_file(real):
    _model, voices = K.find_kokoro_files()
    table = np.load(str(voices), allow_pickle=False)
    assert {v.id for v in K.VOICES} <= set(table.files)
    assert len(K.VOICES) == 41
    assert table["af_heart"].shape == (510, 1, 256)


def test_the_real_model_says_a_sentence_in_about_the_time_it_takes_to_say(real):
    wav = _wav(real.synthesize("Hello there. This is Kokoro, speaking on the processor.", "af_heart"))
    seconds = wav["frames"] / wav["rate"]
    assert wav["rate"] == 24000 and 2.0 < seconds < 8.0, seconds
    loud = np.sqrt(np.mean((wav["samples"].astype(np.float64) / 32767) ** 2))
    assert loud > 0.02, "speech, not silence"


def test_the_real_model_speaks_one_voice_of_every_language(real):
    said = {"af_bella": "Hello.", "bm_george": "Good morning.", "ef_dora": "Hola.",
            "ff_siwis": "Bonjour.", "hf_alpha": "नमस्ते।", "if_sara": "Ciao.", "pm_alex": "Olá."}
    assert {v[0] for v in said} == set(K.LANGUAGES)
    for voice, text in said.items():
        wav = _wav(real.synthesize(text, voice))
        assert wav["frames"] / wav["rate"] > 0.3, (voice, text)

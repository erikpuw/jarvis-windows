import asyncio
import wave
import io

import engine.server.vieneu_tts as v


class _FakeEngine:
    sample_rate = 48_000

    def infer(self, text, voice):
        self.seen = (text, voice)
        return [0.0, 0.5, -0.5] * 100


def test_synthesize_passes_prepared_text_voice_and_rate(monkeypatch):
    fake = _FakeEngine()
    monkeypatch.setattr(v, "_get_engine", lambda: fake)
    monkeypatch.delenv("VIENEU_VOICE_ID", raising=False)
    wav = asyncio.run(v.synthesize_vieneu_wav("Gia vích xin chào"))
    assert fake.seen == ("Gia vích xin chào", v.DEFAULT_VOICE)
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 48_000


def test_stream_is_one_valid_wav_when_concatenated(monkeypatch):
    import numpy as np

    class _Stream(_FakeEngine):
        def infer_stream(self, text, voice):
            self.seen = (text, voice)
            yield np.full(480, 0.5, dtype=np.float32)
            yield np.full(480, -0.5, dtype=np.float32)

    fake = _Stream()
    monkeypatch.setattr(v, "_get_engine", lambda: fake)

    async def collect():
        return [c async for c in v.stream_vieneu_wav("Gia vích xin chào")]

    parts = asyncio.run(collect())
    assert len(parts) == 3  # header + 2 chunks
    assert parts[0][:4] == b"RIFF" and len(parts[0]) == 44
    assert sum(len(p) for p in parts[1:]) == 960 * 2
    assert fake.seen[0] == "Gia vích xin chào"


def test_tts_stream_route_returns_wav_stream_for_vieneu(monkeypatch):
    from fastapi.testclient import TestClient
    import engine.server.stream_tts as st

    async def fake_stream(text, voice_id=None):
        yield b"RIFF"
        yield b"pcm"

    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")
    monkeypatch.setattr(st, "stream_vieneu_wav", fake_stream)
    r = TestClient(st.app, client=("127.0.0.1", 50000)).post("/tts/stream", json={"text": "xin chào"})
    assert r.status_code == 200 and r.headers["x-tts-engine"] == "vieneu"
    assert r.content == b"RIFFpcm"


def test_tts_stream_route_503_when_vieneu_fails_before_audio(monkeypatch):
    from fastapi.testclient import TestClient
    import engine.server.stream_tts as st

    async def broken(text, voice_id=None):
        raise RuntimeError("boom")
        yield b""

    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")
    monkeypatch.setattr(st, "stream_vieneu_wav", broken)
    r = TestClient(st.app, client=("127.0.0.1", 50000)).post("/tts/stream", json={"text": "xin chào"})
    assert r.status_code == 503


def test_pcm_stream_skips_wav_header_and_keeps_samples_whole(monkeypatch):
    import base64
    import httpx
    import engine.server.tts_manager as tm

    header = b"RIFF" + b"\xff" * 4 + b"WAVEfmt " + (16).to_bytes(4, "little") + b"\x01\x00\x01\x00" \
        + (48000).to_bytes(4, "little") + (96000).to_bytes(4, "little") + b"\x02\x00\x10\x00" \
        + b"data" + b"\xff" * 4
    pcm = bytes(range(10))  # 5 mẫu 16-bit
    body = header + pcm

    async def handler(request):
        return httpx.Response(200, content=body)

    async def fake_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(tm, "get_tts_client", fake_client)
    monkeypatch.setattr("engine.server.llm_server.check_stream_tts_server", lambda force=False: (True, "", 8082))  # không phụ thuộc server :8082 thật

    async def collect():
        return [x async for x in tm.stream_synthesize_pcm("xin chào")]

    out = asyncio.run(collect())
    assert out and all(rate == 48000 for _, rate in out)
    assert b"".join(base64.b64decode(b) for b, _ in out) == pcm


def test_voice_streamer_forwards_vieneu_pcm_as_it_arrives(monkeypatch):
    import engine.server.tts_manager as tm
    from engine.server import voice_streamer as vs

    async def fake_pcm(text, ws=None):
        yield "AAA=", 48000
        yield "BBB=", 48000

    monkeypatch.setattr(tm, "stream_synthesize_pcm", fake_pcm)
    monkeypatch.setattr(vs, "_resolve_tts_engine", lambda: "vieneu")

    class WS:
        tts_disabled = cancel_requested = tts_active = media_active = False

    sent = []

    async def send(_ws, payload):
        sent.append(payload)

    async def scenario():
        s = vs.VoiceStreamer(WS(), send_fn=send)
        s.start()
        await s.put("Xin chào bạn.")
        await s.stop()

    asyncio.run(scenario())
    pcm = [p for p in sent if p["type"] == "pcm_chunk"]
    assert [p["data"] for p in pcm] == ["AAA=", "BBB="]
    assert pcm[0]["gap_ms"] == vs._VIENEU_SENTENCE_PAUSE_MS and pcm[1]["gap_ms"] == 0
    assert not any(p["type"] == "audio_chunk" for p in sent)


def test_tts_stream_accepts_non_latin1_voice_name(monkeypatch):
    """Tên giọng như "Minh Triết" từng làm header X-TTS-Voice nổ 500 (latin-1)."""
    from fastapi.testclient import TestClient
    import engine.server.stream_tts as st

    async def fake_stream(text, voice_id=None):
        yield b"RIFF"

    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")
    monkeypatch.setattr(st, "stream_vieneu_wav", fake_stream)
    r = TestClient(st.app, client=("127.0.0.1", 50000)).post(
        "/tts/stream", json={"text": "xin chào", "voice": "Minh Triết"}
    )
    assert r.status_code == 200
    assert r.headers["x-tts-voice"] == "Minh%20Tri%E1%BA%BFt"






def test_stream_cue_filter_hides_cues_split_across_tokens():
    from engine.server.text_streamer import StreamCueFilter, strip_voice_cues

    f = StreamCueFilter()
    out = "".join(f.filter_chunk(t) for t in ["Nghe vui đó ", "[", "cư", "ời", "]", ". Tiếp nào ", "[thở ", "dài]", "."]) + f.flush()
    assert out == "Nghe vui đó. Tiếp nào."
    f = StreamCueFilter()
    assert f.filter_chunk("giá [tham khảo] nhé") + f.flush() == "giá [tham khảo] nhé"  # ngoặc thường giữ nguyên
    assert strip_voice_cues("Haha [cười]. Xong.") == "Haha. Xong."


def test_system_prompt_mentions_cues_only_for_vieneu(monkeypatch):
    from engine.turn.prompt import system_prompt

    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")
    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    assert "<voice_cues>" in system_prompt([])
    monkeypatch.setenv("VIENEU_TTS_ENABLED", "false")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "true")
    assert "<voice_cues>" not in system_prompt([])




def test_tts_server_warms_up_vieneu_on_startup_but_not_edge(monkeypatch):
    import threading
    from fastapi.testclient import TestClient
    import engine.server.stream_tts as st

    called = threading.Event()
    monkeypatch.setattr(st, "warm_up", called.set)

    monkeypatch.setenv("VIENEU_TTS_ENABLED", "false")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "true")
    with TestClient(st.app):
        assert not called.wait(0.3)

    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")
    with TestClient(st.app):
        assert called.wait(3)


def test_server_logs_vieneu_warmup_done(monkeypatch, caplog):
    import logging
    import time as _time
    import httpx
    import server

    replies = iter([
        {"engine": "vieneu", "ready": False},
        {"engine": "vieneu", "ready": True},
    ])

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return httpx.Response(200, json=next(replies), request=httpx.Request("GET", url))

    async def fast_sleep(_):
        return None

    monkeypatch.setattr(server.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(server.asyncio, "sleep", fast_sleep)
    with caplog.at_level(logging.INFO, logger="jarvis"):
        asyncio.run(server._watch_vieneu_warmup(_time.monotonic()))
    text = caplog.text
    assert "[vieneu] warm-up started" in text and "[vieneu] warm-up done" in text


def test_stream_tts_env_offline_toggle(monkeypatch):
    import server

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("VIENEU_HF_OFFLINE", raising=False)
    assert server._stream_tts_env()["HF_HUB_OFFLINE"] == "1"  # mặc định offline
    monkeypatch.setenv("VIENEU_HF_OFFLINE", "0")
    assert "HF_HUB_OFFLINE" not in server._stream_tts_env()  # mở để cập nhật
    assert "HF_HUB_OFFLINE" not in __import__("os").environ  # server chính không bị đổi


def _split(tokens):
    from engine.server.text_streamer import SentenceSplitter

    sp = SentenceSplitter()
    out = []
    for t in tokens:
        out += sp.push(t)
    return out + sp.flush()


def test_sentence_splitter_keeps_file_names_together():
    # log thật: "context_manager." | "py`)…" từng bị tách và "py" đọc thành câu riêng
    tokens = ["Bao gồm ", "quản lý (`", "context", "_manager", ".", "py", "`), ", "bộ nhớ (`", "memory", ".", "py", "`", ").", " Tiếp theo."]
    assert _split(tokens) == ["Bao gồm quản lý (`context_manager.py`), bộ nhớ (`memory.py`).", "Tiếp theo."]


def test_sentence_splitter_still_splits_normal_sentences():
    assert _split(["Xong rồi", ".", " Ngài cần gì", " nữa", "?", " Dạ", "."]) == ["Xong rồi.", "Ngài cần gì nữa?", "Dạ."]
    assert _split(["Nhiệt độ 3", ".", "5", " độ", ".", "\n\n", "Hết", "!"]) == ["Nhiệt độ 3.5 độ.", "Hết!"]
    assert _split(["Đã xong", ".", "**", " Tiếp", "."]) == ["Đã xong.", "** Tiếp."]  # như hành vi cũ


def test_split_for_tts_cuts_long_blob_without_breaking_file_names():
    from engine.server.text_streamer import split_for_tts

    blob = (
        "Màn hình đang mở Visual Studio Code với tệp context_manager.py ở giữa. "
        "Bên trái là cây thư mục có engine và tests. Phía dưới là terminal chạy pytest, "
        "kết quả 164 test đạt. Ngài cần tôi đọc thêm phần nào không?"
    )
    parts = split_for_tts(blob)
    assert len(parts) == 4
    assert "context_manager.py" in parts[0]
    assert parts[2].endswith("164 test đạt.")


def test_voice_streamer_put_splits_long_blob_into_sentences():
    from engine.server import voice_streamer as vs

    class WS:
        tts_disabled = cancel_requested = tts_active = media_active = False

    blob = " ".join(f"Đây là câu số {i} của một đoạn mô tả màn hình khá dài." for i in range(1, 8))
    assert len(blob) > vs._PUT_SPLIT_THRESHOLD

    async def scenario():
        s = vs.VoiceStreamer(WS(), send_fn=lambda *_: None)
        await s.put(blob)
        await s.put("Câu ngắn.")
        items = []
        while not s.text_queue.empty():
            items.append(s.text_queue.get_nowait())
        return items

    items = asyncio.run(scenario())
    assert len(items) == 8 and items[-1] == "Câu ngắn." and items[0].startswith("Đây là câu số 1")


def test_sentence_splitter_raw_mode_reassembles_text_exactly():
    from engine.server.text_streamer import SentenceSplitter

    tokens = ["Hôm nay ", "trời ", "đẹp", ".", " Nhiệt độ ", "3", ".", "5", " độ", ".", " Xem ", "context", ".", "py", " nhé", "."]
    sp = SentenceSplitter(raw=True)
    segments = []
    for t in tokens:
        segments += sp.push(t)
    segments += sp.flush()
    assert "".join(segments) == "".join(tokens)  # hiển thị ghép lại không mất khoảng trắng
    assert [x.strip() for x in segments] == ["Hôm nay trời đẹp.", "Nhiệt độ 3.5 độ.", "Xem context.py nhé."]








def test_tts_gate_follows_button_and_media():
    import types
    import server

    ws = types.SimpleNamespace()

    def button(on):
        ws.user_tts_disabled = not on
        server._sync_tts_gate(ws)

    def media(active):
        ws.media_active = active
        server._sync_tts_gate(ws)

    # 1) nút bật: media mở → TTS tắt, media tắt → TTS bật lại
    button(True); media(True)
    assert ws.tts_disabled and ws.cancel_requested
    media(False)
    assert not ws.tts_disabled and not ws.cancel_requested
    # 2) nút tắt: media không ảnh hưởng, media tắt vẫn không mở lại
    button(False); media(True); media(False)
    assert ws.tts_disabled and ws.cancel_requested
    # 3) bật nút giữa lúc media đang phát: vẫn tắt cho tới khi media dừng
    media(True); button(True)
    assert ws.tts_disabled
    media(False)
    assert not ws.tts_disabled

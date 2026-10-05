"""Regression tests for engine.server.voice_streamer. Run: python tests/test_voice_streamer.py"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.server import voice_streamer as vs
from engine.server.voice_streamer import VoiceStreamer


class FakeWS:
    def __init__(self):
        self.tts_disabled = False
        self.cancel_requested = False
        self.tts_active = False
        self.media_active = False


class Sent:
    """Captures everything the streamer would push over the websocket."""
    def __init__(self):
        self.payloads = []

    async def send(self, _ws, payload):
        self.payloads.append(payload)

    def types(self):
        return [p["type"] for p in self.payloads]

    def count(self, msg_type):
        return sum(1 for p in self.payloads if p["type"] == msg_type)


def _gen(chunks=("YWJj", "ZGVm"), delay=0.0):
    async def speech_gen(_text):
        for c in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield c
    return speech_gen


def test_double_stop_returns_promptly():
    """server.py calls stop() twice on barge-in. The second call used to block
    on audio_queue.put(None) for the full 30s timeout with no worker left."""
    async def scenario():
        ws = FakeWS()
        sent = Sent()
        s = VoiceStreamer(ws, speech_gen_fn=_gen(), send_fn=sent.send)
        s.start()
        await s.put("cau mot.")
        await s.put("cau hai.")
        await asyncio.sleep(0.05)
        ws.cancel_requested = True  # barge-in
        started = time.monotonic()
        await s.stop(clear_queue=True)
        await s.stop()  # the second call server.py makes
        return time.monotonic() - started
    elapsed = asyncio.run(scenario())
    assert elapsed < 5.0, f"double stop took {elapsed:.1f}s — it is blocking on the queue again"


def test_stop_does_not_block_when_worker_already_exited():
    """The exact hang: a full audio_queue with no consumer left. put(None)
    then waited out its whole 30s timeout, freezing the session."""
    async def scenario():
        ws = FakeWS()
        sent = Sent()
        s = VoiceStreamer(ws, speech_gen_fn=_gen(), send_fn=sent.send)
        s.start()
        await asyncio.sleep(0.02)
        ws.cancel_requested = True
        s.audio_queue.put_nowait(("wake", []))  # let the worker notice and exit
        await asyncio.wait_for(s.worker_task, timeout=5)
        while not s.audio_queue.full():  # now nothing can ever drain it
            s.audio_queue.put_nowait(("stuck", []))
        started = time.monotonic()
        await s.stop()
        return time.monotonic() - started
    elapsed = asyncio.run(scenario())
    assert elapsed < 5.0, f"stop() blocked {elapsed:.1f}s on a full queue with no worker"


def test_stop_is_idempotent_many_times():
    async def scenario():
        ws = FakeWS()
        sent = Sent()
        s = VoiceStreamer(ws, speech_gen_fn=_gen(), send_fn=sent.send)
        s.start()
        await s.put("xin chao.")
        started = time.monotonic()
        await s.stop()
        await s.stop()
        await s.stop()
        return time.monotonic() - started
    elapsed = asyncio.run(scenario())
    assert elapsed < 5.0, f"repeated stop took {elapsed:.1f}s"


def test_normal_flow_emits_chunks_and_end_per_sentence():
    async def scenario():
        ws = FakeWS()
        sent = Sent()
        s = VoiceStreamer(ws, speech_gen_fn=_gen(chunks=("AA", "BB")), send_fn=sent.send)
        s.start()
        await s.put("cau mot.")
        await s.put("cau hai.")
        await s.stop()
        return sent
    sent = asyncio.run(scenario())
    assert sent.count("audio_chunk") == 4, sent.types()
    assert sent.count("audio_chunk_end") == 2, sent.types()
    assert sent.payloads[-1] == {"type": "status", "state": "idle", "source": "tts"}


def test_cancel_before_put_drops_the_sentence():
    async def scenario():
        ws = FakeWS()
        sent = Sent()
        s = VoiceStreamer(ws, speech_gen_fn=_gen(), send_fn=sent.send)
        s.start()
        ws.cancel_requested = True
        await s.put("khong duoc doc.")
        await s.stop(clear_queue=True)
        return sent
    sent = asyncio.run(scenario())
    assert sent.count("audio_chunk") == 0, sent.types()


def test_prefetch_overlaps_synthesis_with_playback():
    """Depth 1 made the synthesizer wait for the player on every sentence."""
    assert vs._PREFETCH_DEPTH > 1, vs._PREFETCH_DEPTH


def test_sentence_gap_does_not_dominate_long_answers():
    """A flat 0.4s per sentence added ~4s of dead air to a ten sentence reply."""
    assert vs._SENTENCE_GAP < 0.2, vs._SENTENCE_GAP


def test_worker_crash_does_not_cancel_the_text_stream():
    """A transient send failure must not set cancel_requested — that flag also
    stops LLM text generation, not just audio."""
    async def scenario():
        ws = FakeWS()
        calls = {"n": 0}

        async def flaky_send(_ws, payload):
            calls["n"] += 1
            if payload.get("type") == "audio_chunk":
                raise RuntimeError("socket hiccup")

        s = VoiceStreamer(ws, speech_gen_fn=_gen(), send_fn=flaky_send)
        s.start()
        await s.put("cau mot.")
        await s.stop()
        return ws
    ws = asyncio.run(scenario())
    assert ws.cancel_requested is False, "audio failure wrongly cancelled the whole turn"


def test_no_waiting_status_after_the_last_sentence():
    """Sau câu cuối không còn câu nào để chờ: không được gửi "Đang trả lời 2..."
    ngay trước idle, nếu không nhãn đó kẹt trên UI khi client hoãn idle lúc audio còn phát."""
    async def scenario():
        ws = FakeWS()
        sent = Sent()
        s = VoiceStreamer(ws, speech_gen_fn=_gen(), send_fn=sent.send)
        s.start()
        await s.put("cau mot.")
        await s.put("cau hai.")
        await s.stop()
        return sent
    sent = asyncio.run(scenario())
    statuses = [p for p in sent.payloads if p["type"] == "status"]
    assert statuses[-1]["state"] == "idle", statuses
    with_message = [p for p in statuses if p.get("message")]
    assert len(with_message) == 1, statuses  # chỉ trạng thái chuẩn bị ban đầu


if __name__ == "__main__":
    test_no_waiting_status_after_the_last_sentence()
    test_double_stop_returns_promptly()
    test_stop_does_not_block_when_worker_already_exited()
    test_stop_is_idempotent_many_times()
    test_normal_flow_emits_chunks_and_end_per_sentence()
    test_cancel_before_put_drops_the_sentence()
    test_prefetch_overlaps_synthesis_with_playback()
    test_sentence_gap_does_not_dominate_long_answers()
    test_worker_crash_does_not_cancel_the_text_stream()
    print("OK: all voice_streamer regression tests passed")

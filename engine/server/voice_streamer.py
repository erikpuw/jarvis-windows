"""
engine/server/voice_streamer.py — Centralized TTS queue worker and speech player
=============================================================================
Manages voice output background tasks, handles play/pause state collision,
and stops streaming immediately when client turns off speaking.
"""

import asyncio
import logging
import os

from engine.server.text_streamer import split_for_tts
from engine.server.tts_manager import _resolve_tts_engine

log = logging.getLogger("jarvis.voice_streamer")

# How many synthesized sentences may sit ahead of playback. At the old depth of
# 1 the synthesizer stalled on put() until the player finished the previous
# sentence, so synthesis and playback never really overlapped.
_PREFETCH_DEPTH = max(1, int(os.getenv("TTS_PREFETCH_DEPTH", "3")))
# Pause inserted between sentences. This was a flat 0.4s, which on a ten
# sentence answer added four seconds of dead air; the player already sequences
# chunks itself. Tunable so it can be raised again if playback sounds rushed.
_SENTENCE_GAP = max(0.0, float(os.getenv("TTS_SENTENCE_GAP_SECONDS", "0.08")))
# Pause between fetching one sentence's audio and asking edge-tts for the
# next. Prefetch already overlaps synthesis with playback (see _PREFETCH_DEPTH
# above); without this, consecutive sentences hit Microsoft's edge-tts back to
# back with zero gap the moment each finishes, which reads as a burst.
_PREFETCH_GAP_SECONDS = max(0.0, float(os.getenv("TTS_PREFETCH_GAP_SECONDS", "0.25")))
# VieNeu chỉ: mỗi câu là một request riêng nên SDK không chèn nghỉ giữa các câu;
# client cộng khoảng lặng này trước câu kế tiếp để nhịp đọc không bị dính.
_VIENEU_SENTENCE_PAUSE_MS = max(0, int(os.getenv("VIENEU_SENTENCE_PAUSE_MS", "450")))


# Văn bản dài hơn ngưỡng này được cắt thành câu trước khi vào hàng đợi TTS.
_PUT_SPLIT_THRESHOLD = 200


class VoiceStreamer:
    def __init__(self, ws, speech_gen_fn=None, send_fn=None):
        self.ws = ws
        self.speech_gen_fn = speech_gen_fn
        self.text_queue = asyncio.Queue()
        self.audio_queue = asyncio.Queue(maxsize=_PREFETCH_DEPTH)
        self.prefetch_task = None
        self.worker_task = None
        self._stopped = False
        self._send_fn = send_fn

    async def _send(self, payload):
        """Send through the injected sender, falling back to server's."""
        if self._send_fn is None:
            from server import safe_ws_send_json
            self._send_fn = safe_ws_send_json
        return await self._send_fn(self.ws, payload)

    def start(self):
        self.prefetch_task = asyncio.create_task(self._prefetch_worker())
        self.worker_task = asyncio.create_task(self._tts_worker())
        if self.ws:
            self.ws.tts_active = True
        return self.worker_task

    async def put(self, sentence: str):
        if self.is_cancelled():
            return
        # Một số nơi (read_screen, synthesizer.deliver, kết quả công cụ) đưa cả đoạn văn
        # vào một lần. TTS phải nhận từng câu: cả cục thì chờ lâu mới có tiếng đầu và
        # dễ bị cắt cụt giữa chừng. Câu ngắn (luồng LLM đã tự cắt) đi thẳng như cũ.
        pieces = split_for_tts(sentence) if len(sentence) > _PUT_SPLIT_THRESHOLD else [sentence]
        for piece in pieces:
            await self.text_queue.put(piece)

    async def stop(self, clear_queue=False):
        # server.py stops the streamer twice on the cancel path: once with
        # clear_queue on barge-in, then again in the finalize step. The second
        # call used to block for the full 30s audio_queue timeout, because the
        # worker had already exited and nothing was left to drain the queue —
        # so a barge-in froze the session for half a minute.
        if self._stopped:
            return
        self._stopped = True
        if clear_queue:
            # Clear text queue
            while not self.text_queue.empty():
                try:
                    self.text_queue.get_nowait()
                    self.text_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            # Clear audio queue
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.task_done()
                except asyncio.QueueEmpty:
                    break

        await self.text_queue.put(None)
        if self.prefetch_task:
            # Không đặt timeout ngắn ở đây: prefetch_task phải tổng hợp giọng
            # tuần tự cho TOÀN BỘ câu còn lại trong hàng đợi (audio_queue chỉ
            # giữ tối đa _PREFETCH_DEPTH câu nên nó vẫn bị chặn chờ _tts_worker).
            # Một timeout ngắn (vd. 5s) sẽ hủy ngang prefetch_task giữa chừng
            # với câu trả lời dài — làm JARVIS chỉ đọc được đoạn đầu tiên rồi
            # im bặt. Mỗi lần gọi TTS đã tự có timeout riêng (30-90s) nên ở
            # đây chỉ cần một giới hạn rộng làm lưới an toàn chống treo thật sự.
            try:
                await asyncio.wait_for(self.prefetch_task, timeout=180)
            except asyncio.TimeoutError:
                log.warning("VoiceStreamer prefetch task join timed out (180s); cancelling")
                self.prefetch_task.cancel()
            except (Exception, asyncio.CancelledError) as e:
                log.warning(f"VoiceStreamer prefetch task error on join: {e}")

        # Only hand the worker its sentinel if it is still there to take it.
        if self.worker_task and not self.worker_task.done():
            try:
                await asyncio.wait_for(self.audio_queue.put(None), timeout=30)
            except asyncio.TimeoutError:
                log.warning("VoiceStreamer audio_queue.put(None) timed out; worker likely already stopped")

        if self.worker_task:
            try:
                await asyncio.wait_for(self.worker_task, timeout=60)
            except asyncio.TimeoutError:
                log.warning("VoiceStreamer worker task join timed out (60s); cancelling")
                self.worker_task.cancel()
            except (Exception, asyncio.CancelledError) as e:
                log.warning(f"VoiceStreamer worker task error on join: {e}")

    def is_cancelled(self) -> bool:
        if not self.ws:
            return True
        return getattr(self.ws, "tts_disabled", False) or getattr(self.ws, "cancel_requested", False)

    async def _prefetch_worker(self):
        try:
            import re as _pf_re
            pending_sentence = ""
            while True:
                if self.is_cancelled():
                    break
                sentence = await self.text_queue.get()

                reached_end = sentence is None
                if reached_end:
                    sentence = pending_sentence
                    pending_sentence = ""
                    if not sentence:
                        self.text_queue.task_done()
                        break
                elif pending_sentence:
                    sentence = pending_sentence + sentence
                    pending_sentence = ""

                # Token streaming có thể ngắt câu ngay tại dấu chấm trong URL.
                # Chờ link khép kín rồi mới lọc và gửi sang TTS.
                markdown_link_open = sentence.rfind("](") > sentence.rfind(")")
                raw_url_open = _pf_re.search(
                    r"(?:https?://|www\.)(?:[A-Za-z0-9-]+)\.$",
                    sentence,
                    flags=_pf_re.I,
                )
                if not reached_end and (markdown_link_open or raw_url_open):
                    pending_sentence = sentence
                    self.text_queue.task_done()
                    continue

                if self.is_cancelled():
                    self.text_queue.task_done()
                    break

                chunks = []
                streamed = False  # vieneu: audio_queue đã nhận câu này (phát dần)
                try:
                    clean_text = sentence  # tts_manager chuẩn bị văn bản (một nơi duy nhất); ở đây chỉ kiểm tra có gì để đọc
                    if clean_text and len(clean_text.strip()) >= 2 and _pf_re.search(r"[a-zA-Z0-9\u00C0-\u1EF9]", clean_text):
                        if self.speech_gen_fn:
                            async for chunk_b64 in self.speech_gen_fn(clean_text):
                                if self.is_cancelled():
                                    break
                                if chunk_b64:
                                    chunks.append(chunk_b64)
                        elif _resolve_tts_engine() == "vieneu":
                            from engine.server.tts_manager import stream_synthesize_pcm
                            pcm_queue = asyncio.Queue()
                            await self.audio_queue.put((sentence, pcm_queue))
                            streamed = True
                            try:
                                async for piece in stream_synthesize_pcm(clean_text, ws=self.ws):
                                    if self.is_cancelled():
                                        break
                                    pcm_queue.put_nowait(piece)
                            finally:
                                pcm_queue.put_nowait(None)
                        else:
                            from engine.server.tts_manager import stream_synthesize_speech
                            async for chunk_b64 in stream_synthesize_speech(clean_text, ws=self.ws):
                                if self.is_cancelled():
                                    break
                                if chunk_b64:
                                    chunks.append(chunk_b64)
                except Exception as e:
                    log.warning(f"Prefetch failed for: {sentence[:40]!r}. Error: {e}")

                if not self.is_cancelled() and not streamed:
                    await self.audio_queue.put((sentence, chunks))
                self.text_queue.task_done()
                if reached_end:
                    break
                # Nghỉ này chỉ để tránh dồn dập lên edge-tts (Microsoft). VieNeu chạy local:
                # nghỉ thêm ở đây làm câu ngắn kế tiếp tới muộn hơn audio đang phát → hụt/giật.
                if _PREFETCH_GAP_SECONDS and not streamed and not self.is_cancelled():
                    await asyncio.sleep(_PREFETCH_GAP_SECONDS)
        except Exception as e:
            log.error(f"VoiceStreamer prefetch worker error: {e}")

    async def _tts_worker(self):
        try:
            # Trạng thái đầu: chưa có tiếng, đang chờ câu đầu tiên được tổng hợp
            if not self.is_cancelled():
                await self._send({"type": "status", "state": "speaking", "message": "Đang chuẩn bị…", "source": "tts"})
            
            while True:
                if self.is_cancelled():
                    break
                item = await self.audio_queue.get()
                if item is None:
                    self.audio_queue.task_done()
                    break
                if self.is_cancelled():
                    self.audio_queue.task_done()
                    break

                sentence, chunks = item
                if isinstance(chunks, asyncio.Queue):
                    # VieNeu: đẩy PCM xuống client ngay khi từng đoạn được sinh ra.
                    first = True
                    while True:
                        piece = await chunks.get()
                        if piece is None:
                            break
                        if self.is_cancelled():
                            self.audio_queue.task_done()
                            return
                        if first:
                            await self._send({"type": "status", "state": "speaking", "source": "tts"})
                        b64, rate = piece
                        await self._send({
                            "type": "pcm_chunk",
                            "sample_rate": rate,
                            "data": b64,
                            "gap_ms": _VIENEU_SENTENCE_PAUSE_MS if first else 0,
                        })
                        first = False
                elif chunks and not self.is_cancelled():
                    # Chuyển sang speaking khi bắt đầu phát âm thanh câu đó
                    await self._send({"type": "status", "state": "speaking", "source": "tts"})

                    for chunk_b64 in chunks:
                        if self.is_cancelled():
                            self.audio_queue.task_done()
                            return
                        await self._send({
                            "type": "audio_chunk",
                            "sentence_idx": 0,
                            "data": chunk_b64,
                        })

                    await self._send({"type": "audio_chunk_end"})
                    # Ngắt nghỉ giữa các câu cho tự nhiên, giữ nhỏ để không cộng
                    # dồn thành vài giây im lặng trên câu trả lời dài.
                    if _SENTENCE_GAP:
                        await asyncio.sleep(_SENTENCE_GAP)

                self.audio_queue.task_done()
        except Exception as e:
            # KHÔNG set ws.cancel_requested ở đây: cờ này dùng chung để dừng
            # cả luồng sinh TEXT từ LLM (xem server.py), không chỉ audio. Một
            # lỗi thoáng qua trong lúc phát 1 câu (vd. gửi websocket lỗi tạm
            # thời) không nên làm dừng toàn bộ phần còn lại của câu trả lời.
            log.error(f"VoiceStreamer worker loop crashed: {e}", exc_info=True)
        finally:
            await self._send({"type": "status", "state": "idle", "source": "tts"})
            if self.ws:
                self.ws.tts_active = False

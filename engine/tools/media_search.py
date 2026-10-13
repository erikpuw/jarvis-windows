import asyncio
import json
import logging
import re
import subprocess
import unicodedata
from pathlib import Path

log = logging.getLogger("jarvis.media_search")


async def search_media(query: str, source: str = "auto") -> list[dict]:
    if source == "local":
        results = search_local(query)
        if results:
            return results
    return await search_youtube(query)


def _strip_noise(text: str) -> str:
    """Strip common routing keywords that LLM sometimes leaves in the query."""
    _noise = re.compile(
        r'\b(?:hhpanda|hhpada|hhpand|hpanda|phim|xem\s*phim|youtube|video|nhạc|music|bài\s*hát|nghe|mở|tìm)\b',
        re.IGNORECASE
    )
    return _noise.sub('', text).strip()


_REQUEST_WORDS = re.compile(
    r'(?<!\w)(?:tôi|mình|em|muốn|cần|giúp|hãy|bạn|cho|của|với|nha|nhé|nhá|đi|bật|phát|xem)(?!\w)',
    re.IGNORECASE,
)


def _strip_request_words(text: str) -> str:
    """Bỏ từ đệm của câu nói tự nhiên ("tôi muốn nghe … của …") trước khi xếp hạng YouTube:
    reranking chấm từng từ, nên "của" từng kéo một video drama lên trên bài hát chính chủ.
    ponytail: danh sách từ cố định; tên bài có đúng các từ này mất vài điểm khớp, yt-dlp vẫn tìm ra."""
    return " ".join(_REQUEST_WORDS.sub(" ", text).split())


def no_accent(text: str) -> str:
    """Loại bỏ dấu tiếng Việt để so khớp chuỗi không dấu."""
    text = text.lower()
    text = text.replace('\u0111', 'd')  # đ -> d
    text = unicodedata.normalize('NFKD', text)
    return "".join(c for c in text if not unicodedata.combining(c))


async def search_youtube(query: str, max_results: int = 4) -> list[dict]:
    try:
        query = _strip_request_words(_strip_noise(query)) or query
        # Tìm nhiều hơn 10 video để lọc Shorts, sau đó cắt lấy tối đa 4 video
        result = await asyncio.to_thread(_yt_search, query, max_results=12)
        # Lọc bỏ các video ngắn (Shorts) có thời lượng dưới 60 giây (giữ lại None vì Live Stream có duration là None)
        filtered = []
        for r in result:
            dur = r.get("duration")
            if dur is None or (isinstance(dur, (int, float)) and dur >= 60):
                filtered.append(r)
                
        # Thuật toán Reranking & Live Boost
        query_normalized = no_accent(query)
        query_words = [w for w in query_normalized.split() if len(w) > 1]
        
        # Nhận diện xem người dùng có đang muốn xem live stream không
        live_keywords = ["live", "truc tiep", "livestream", "streaming"]
        is_searching_live = any(lk in query_normalized for lk in live_keywords)
        
        # Danh sách từ khóa định dạng phụ dễ gây sai lệch bài gốc
        format_keywords = ["live", "remix", "cover", "karaoke", "fancam", "vietsub", "lyrics", "acoustic", "mashup", "loop", "instrumental", "remake"]
        # Danh sách từ khóa chính thức của ca sĩ
        official_keywords = ["official", "mv", "music video", "visualizer", "audio"]
        
        def get_match_score(item: dict) -> float:
            title_normalized = no_accent(item.get("title", ""))
            
            # 1. Điểm khớp từ đơn lẻ
            matches = sum(1 for w in query_words if w in title_normalized)
            
            # 2. Điểm khớp cụm từ liên tục (Phrases)
            phrase_score = 0
            for i in range(len(query_words) - 1):
                phrase2 = f"{query_words[i]} {query_words[i+1]}"
                if phrase2 in title_normalized:
                    phrase_score += 2
            for i in range(len(query_words) - 2):
                phrase3 = f"{query_words[i]} {query_words[i+1]} {query_words[i+2]}"
                if phrase3 in title_normalized:
                    phrase_score += 4
                    
            # 3. Live Boost: Ưu tiên kết quả trực tiếp nếu truy vấn yêu cầu xem live
            if is_searching_live:
                if any(lk in title_normalized for lk in live_keywords):
                    phrase_score += 5
            
            # 4. Format Penalty: Trừ điểm nếu tiêu đề chứa từ khóa định dạng mà truy vấn của user không yêu cầu
            for fk in format_keywords:
                if fk in title_normalized and fk not in query_normalized:
                    phrase_score -= 5
                    
            # 5. Official Bonus: Cộng điểm thưởng cho các ấn bản chính thức
            if any(ok in title_normalized for ok in official_keywords):
                phrase_score += 2
                
            # 6. Channel & Official Channel Boost: Ưu tiên kênh chính chủ của ca sĩ
            channel_normalized = no_accent(item.get("channel", ""))
            channel_words_matched = sum(1 for w in query_words if w in channel_normalized)
            if channel_words_matched > 0:
                phrase_score += channel_words_matched * 2
                # Thưởng thêm nếu có nhãn chính thức trong tên kênh
                if any(ok in channel_normalized for ok in ["official", "vevo", "artist", "chinh chu"]):
                    phrase_score += 5
            else:
                # Phạt kênh re-upload không khớp tên ca sĩ
                phrase_score -= 4
                    
            return matches + phrase_score

        filtered.sort(key=get_match_score, reverse=True)
        return filtered[:4]
    except Exception as e:
        log.warning(f"YouTube search failed: {e}")
        return []


def _yt_search(query: str, max_results: int = 12) -> list[dict]:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        f"ytsearch{max_results}:{query}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    results = []
    for line in proc.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            video_id = data.get("id")
            if not video_id:
                continue
            
            # Lọc sơ bộ nếu tiêu đề chứa Shorts hoặc shorts
            title = data.get("title", "")
            if "shorts" in title.lower():
                continue

            results.append({
                "id": video_id,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "embed_url": f"https://www.youtube.com/embed/{video_id}",
                "thumbnail": data.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
                "duration": data.get("duration"),
                "channel": data.get("channel", ""),
                "source": "youtube",
            })
        except json.JSONDecodeError:
            continue
    return results


def format_media_table(results: list[dict]) -> str:
    """Chuyển list kết quả search_media thành bảng Markdown YouTube: thumbnail nhỏ | tên video | kênh | thời lượng."""
    if not results:
        return ""

    rows = []
    rows.append("| Poster | Tên bài | Nghệ sĩ | Thời Lượng |")
    rows.append("| :---: | :--- | :--- | :---: |")
    for r in results:
        title = r.get("title", "").strip()
        video_id = r.get("id", "")
        channel = r.get("channel", "").strip()
        duration = r.get("duration")
        url = r.get("url", "")

        if video_id:
            thumb_url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
        else:
            thumb_url = r.get("thumbnail", "")

        # Lọc ký tự | trong alt
        alt_text = title[:20].replace("|", "-").strip()
        poster_cell = f"![{alt_text}]({thumb_url})" if thumb_url else "▶️"

        # Dọn dẹp ngoặc vuông, ngoặc tròn rác khỏi tên bài
        clean_title = re.sub(r'\s*[\[\(](?:OFFICIAL|Official|MV|Lyrics|LỜI|Linh|Karaoke|Vietsub|Visualizer|Audio|HD|1080p|4K|Remix|Cover|Live|Video|Teaser|Performance|Music Video|Visualizer Video).*?[\]\)]', '', title, flags=re.IGNORECASE).strip()
        # Dọn dẹp các cụm từ đứng tự do hoặc sau dấu gạch đứng/ngang
        clean_title = re.sub(r'\b(?:OFFICIAL VISUALIZER|OFFICIAL MUSIC VIDEO|MUSIC VIDEO|VISUALIZER|OFFICIAL AUDIO|OFFICIAL|MV|AUDIO|LYRIC VIDEO|TEASER|PERFORMANCE)\b', '', clean_title, flags=re.IGNORECASE).strip()
        # Dọn dẹp các vệt ký tự gạch hoặc gạch đứng dư thừa ở cuối tên bài
        clean_title = re.sub(r'[\s|:-]+$', '', clean_title).strip()

        if not clean_title:
            clean_title = title

        # Cột 2: Tên bài (Chứa link)
        if url:
            title_link = f"**[{clean_title}]({url})**"
        else:
            title_link = f"**{clean_title}**"

        # Cột 3: Nghệ sĩ (Chữ sạch)
        artist_cell = channel

        # Cột 4: Thời lượng
        if duration:
            mins = int(duration) // 60
            secs = int(duration) % 60
            duration_cell = f"{mins}:{secs:02d}"
        else:
            duration_cell = "N/A"

        rows.append(f"| {poster_cell} | {title_link} | {artist_cell} | {duration_cell} |")

    return "\n".join(rows)


def search_local(query: str, max_results: int = 8) -> list[dict]:
    media_dirs = [
        Path.home() / "Videos",
        Path.home() / "Music",
        Path.home() / "Downloads",
    ]
    try:
        from engine.tools.skill_manager import get_skill_manager
        config = getattr(get_skill_manager(), "config", {})
        extra = config.get("media_dirs", [])
        if isinstance(extra, list):
            media_dirs.extend(Path(d) for d in extra)
    except Exception:
        pass

    exts = {".mp4", ".mkv", ".avi", ".mov", ".mp3", ".flac", ".wav", ".m4a", ".webm"}
    results = []
    ql = query.lower()

    for d in media_dirs:
        if not d.exists():
            continue
        try:
            for f in d.iterdir():
                if f.suffix.lower() in exts and ql in f.stem.lower():
                    results.append({
                        "id": str(f),
                        "title": f.stem,
                        "url": str(f),
                        "source": "local",
                    })
        except PermissionError:
            continue
    return results


async def execute_media_search(arguments: dict, ws=None, safe_ws_send_json=None) -> str | dict:
    """Tìm nhạc/video (YouTube hoặc file local) và gửi mã điều khiển phát tới client."""
    query = arguments.get("query") or arguments.get("user_text", "")
    source = arguments.get("source", "auto")
    if not query:
        return "Lỗi: Thiếu nội dung tìm kiếm."

    if ws and safe_ws_send_json is None:
        try:
            from server import safe_ws_send_json as _sws
            safe_ws_send_json = _sws
        except Exception:
            pass

    query = _strip_noise(query)
    results = await search_media(query, source)
    if not results:
        return f"Không tìm thấy nội dung cho '{query}'."

    # Nguồn thực tế lấy từ kết quả đầu tiên (local không có embed_url nên không tự phát)
    actual_source = results[0].get("source", source)
    embed_url = results[0].get("embed_url", "") if actual_source == "youtube" else ""
    resolved_title = results[0].get("title", "") if actual_source == "youtube" else ""

    lines = [f"Tìm thấy {len(results)} kết quả cho '{query}':", "", format_media_table(results)]

    if embed_url and resolved_title:
        lines.append(f"\n✅ ĐANG PHÁT: {resolved_title}")
        if ws and safe_ws_send_json:
            try:
                await safe_ws_send_json(ws, {
                    "type": "media_open",
                    "query": query,
                    "embed_url": embed_url,
                    "title": resolved_title,
                    "source": actual_source,
                })
            except Exception as ws_err:
                log.warning(f"Failed to send media_open via WebSocket: {ws_err}")

    return {
        "text": "\n".join(lines),
        "results": results,
        "query": query,
        "embed_url": embed_url,
        "title": resolved_title,
        "episodes": [],
    }

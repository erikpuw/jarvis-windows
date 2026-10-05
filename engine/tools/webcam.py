import cv2
import logging
import base64
import os
import urllib.request

log = logging.getLogger("jarvis.webcam")

def download_hand_landmarker_model(model_path: str):
    url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    try:
        log.info(f"Downloading hand_landmarker.task from {url}...")
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        # Sử dụng header User-Agent để tránh bị chặn tải
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=20.0) as response, open(model_path, 'wb') as out_file:
            out_file.write(response.read())
        log.info("Download completed successfully.")
    except Exception as e:
        log.error(f"Failed to download model: {e}")

def detect_and_draw_hands(frame):
    try:
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError as e:
        log.warning(f"MediaPipe not installed, skipping hand landmark detection: {e}")
        return frame

    model_path = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")
    if not os.path.exists(model_path):
        download_hand_landmarker_model(model_path)

    if not os.path.exists(model_path):
        log.error("hand_landmarker.task model file not found and download failed.")
        return frame

    try:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2
        )

        with vision.HandLandmarker.create_from_options(options) as landmarker:
            detection_result = landmarker.detect(mp_image)
            
            if not detection_result.hand_landmarks:
                return frame

            h, w, _ = frame.shape
            tips = [4, 8, 12, 16, 20]

            for hand_landmarks in detection_result.hand_landmarks:
                for tip_idx in tips:
                    if tip_idx < len(hand_landmarks):
                        lm = hand_landmarks[tip_idx]
                        cx, cy = int(lm.x * w), int(lm.y * h)
                        
                        # Vẽ điểm phát sáng neon mờ màu cyan
                        # BGR: (255, 212, 0) là màu xanh cyan rực rỡ
                        cv2.circle(frame, (cx, cy), 10 if tip_idx == 8 else 7, (255, 212, 0), -1)
                        # Vẽ nhân màu trắng rực rỡ ở giữa
                        cv2.circle(frame, (cx, cy), 4 if tip_idx == 8 else 3, (255, 255, 255), -1)
                        # Viền ngoài sắc nét
                        cv2.circle(frame, (cx, cy), 13 if tip_idx == 8 else 9, (255, 212, 0), 1)

        log.info("Successfully detected and drew hand landmarks on frame.")
    except Exception as ex:
        log.error(f"Error in hand landmarker processing: {ex}")
        
    return frame

async def capture_webcam_frame() -> str | None:
    """Capture a single frame from the client-side webcam (laptop or phone) via WebSocket and return as base64 JPEG."""
    try:
        import server
        ws = server._active_ws_session
        if not ws:
            log.error("No active WebSocket connection to client.")
            return None
        
        import asyncio
        # Thiết lập sự kiện nhận ảnh và reset ảnh cũ
        server._latest_webcam_image = None
        server._webcam_image_event = asyncio.Event()
        
        # Gửi tín hiệu yêu cầu Client chụp hình
        log.info("Sending webcam_capture_request to client...")
        await ws.send_json({"type": "webcam_capture_request"})
        
        # Chờ phản hồi từ Client với timeout 6 giây
        try:
            await asyncio.wait_for(server._webcam_image_event.wait(), timeout=6.0)
        except asyncio.TimeoutError:
            log.error("Timeout waiting for client webcam frame response.")
            return None
            
        img_b64 = server._latest_webcam_image
        if not img_b64:
            log.error("Received empty image data from client.")
            return None
            
        if img_b64.startswith("ERROR:"):
            log.error(f"Client reported webcam capture error: {img_b64}")
            return None
            
        # Decode base64 to check frame quality (Anti-Hallucination)
        import numpy as np
        image_bytes = base64.b64decode(img_b64)
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            log.error("Failed to decode base64 image bytes to frame.")
            return None
            
        # --- Frame Quality Check (Anti-Hallucination) ---
        # Calculate mean brightness to detect covered lens or black frames
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        avg_brightness = cv2.mean(gray)[0]
        log.info(f"Captured frame brightness: {avg_brightness:.2f}")
        
        if avg_brightness < 10:
            log.warning("Webcam frame is too dark (likely covered or disabled). Rejecting to prevent hallucination.")
            return "ERROR:DARK_FRAME"
        if avg_brightness > 245:
            log.warning("Webcam frame is too bright (overexposed).")
            return "ERROR:OVEREXPOSED"
            
        # Phát hiện bàn tay và vẽ các landmarks
        frame = await asyncio.to_thread(detect_and_draw_hands, frame)
        
        # Mã hóa ngược lại thành base64 JPEG
        try:
            _, buffer = cv2.imencode('.jpg', frame)
            img_b64 = base64.b64encode(buffer).decode('utf-8')
            
            # Gửi ngược lại cho client qua websocket để cập nhật hiển thị lên UI
            await ws.send_json({"type": "webcam_processed", "image": img_b64})
        except Exception as encode_err:
            log.error(f"Error encoding processed hand frame to base64: {encode_err}")

        log.info("Webcam frame captured and processed with MediaPipe successfully.")
        return img_b64
        
    except Exception as e:
        log.error(f"Webcam capture error: {e}")
        return None

async def webcam_analyze(client, prompt: str = "What do you see through the webcam?", is_vi: bool = False) -> str:
    """Capture a frame and analyze it with a multimodal model."""
    img_b64 = await capture_webcam_frame()
    if not img_b64:
        return "Không thể truy cập webcam, thưa ngài. Hãy kiểm tra kết nối hoặc xem có ứng dụng nào đang dùng webcam không."
    
    if img_b64 == "ERROR:DARK_FRAME":
        return "Tôi không thể nhìn thấy gì qua webcam (hình ảnh tối đen). Ngài vui lòng kiểm tra xem ống kính có bị che không, hoặc nếu là webcam điện thoại thì đã bật camera chưa?" if is_vi else "I can't see anything through the webcam (the image is pitch black). Please check if the lens is covered or if the camera is enabled."
    
    if img_b64 == "ERROR:OVEREXPOSED":
        return "Hình ảnh từ webcam bị lóa sáng quá mức, tôi không thể phân tích được." if is_vi else "The webcam image is overexposed, I cannot analyze it properly."
    
    lang_instruction = (
        " IMPORTANT: Describe COMPLETELY in Vietnamese.\n"
        "QUY TẮC CẤU TRÚC:\n"
        "1. Trình bày ngắn gọn, rõ ràng những gì bạn thấy qua webcam.\n"
        "2. Không lạm dụng emoji, tối đa 1 emoji phù hợp cho toàn bộ câu trả lời.\n"
        "3. Rút gọn mọi liên kết dài: Không được in ra URL trần dài dòng, luôn bọc URL bằng cú pháp `[Tên liên kết hoặc Xem chi tiết](url)`.\n"
        "4. Giữ nguyên 100% cú pháp hình ảnh Markdown dạng `![title](url)` nếu có.\n"
        "5. Định dạng bảng biểu chuẩn: Khi biểu diễn danh sách thông số, thống kê (như giá xăng, tỷ giá, chứng khoán), bắt buộc dựng bảng Markdown có header `| Cột 1 | Cột 2 |` rõ ràng. Không để dòng trống xen kẽ trong bảng."
    ) if is_vi else ""
    
    try:
        # Qua client chung (có API key); model + tham số theo model đang chạy, tắt thinking
        from engine.server.llm_server import strip_think, vision_model_name, vision_request_kwargs

        response = await client.chat.completions.create(
            model=vision_model_name(),
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": f"{prompt}{lang_instruction}"},
                ],
            }],
            **vision_request_kwargs(),
        )
        return strip_think(response.choices[0].message.content or "")
        
    except Exception as e:
        log.error(f"Webcam analysis failed: {e}")
        return f"Error analyzing webcam feed: {e}"



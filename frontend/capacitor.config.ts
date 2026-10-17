import type { CapacitorConfig } from "@capacitor/cli";

// App iOS mở giao diện JARVIS đang chạy trên PC qua Tailscale.
// Đặt JARVIS_SERVER_URL trước khi build, ví dụ: http://100.x.y.z:5173
const serverUrl = process.env.JARVIS_SERVER_URL;
if (!serverUrl) {
  // Thiếu biến này thì app mở giao diện đóng gói sẵn và màn hình đen, nên dừng build ngay.
  throw new Error("Thiếu JARVIS_SERVER_URL: kiểm tra nhóm biến 'jarvis' trên Codemagic.");
}

const config: CapacitorConfig = {
  appId: "com.erikpuw.jarvis",
  appName: "JARVIS",
  webDir: "dist",
  server: "https://jarvis.tail8b8885.ts.net:8304",
};

export default config;

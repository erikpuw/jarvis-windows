import type { CapacitorConfig } from "@capacitor/cli";

// App iOS mở giao diện JARVIS đang chạy trên PC qua Tailscale.
// Đặt JARVIS_SERVER_URL trước khi build, ví dụ: http://100.x.y.z:5173
const serverUrl = process.env.JARVIS_SERVER_URL;

const config: CapacitorConfig = {
  appId: "com.erikpuw.jarvis",
  appName: "JARVIS",
  webDir: "dist",
  server: serverUrl ? { url: serverUrl, cleartext: true } : undefined,
};

export default config;

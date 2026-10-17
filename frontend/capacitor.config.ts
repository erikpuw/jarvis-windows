import type { CapacitorConfig } from "@capacitor/cli";

// App iOS mở giao diện JARVIS đang chạy trên PC qua Tailscale (HTTPS, cổng 8340).
const config: CapacitorConfig = {
  appId: "com.erikpuw.jarvis",
  appName: "JARVIS",
  webDir: "dist",
  server: {
    url: "https://example.com",
    cleartext: true,
  },
};

export default config;

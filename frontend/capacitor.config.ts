import type { CapacitorConfig } from "@capacitor/cli";

// App iOS mở giao diện JARVIS đang chạy trên PC qua Tailscale (HTTPS, cổng 8340).
const config: CapacitorConfig = {
  appId: "com.erikpuw.jarvis",
  appName: "JARVIS",
  webDir: "dist",
  server: {
    url: "https://jarvis.tail8b8885.ts.net:8340",
    cleartext: true,
  },
};

export default config;

import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    allowedHosts: [
      "ada-rc-front-wrtc-1-markk-ma.amvera.io",
    ],
  },
});

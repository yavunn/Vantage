import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirmede API istekleri backend'e (8000) yönlenir; üretimde
// build çıktısı FastAPI tarafından aynı origin'den sunulur.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});

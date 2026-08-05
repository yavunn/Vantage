import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { LangProvider } from "./i18n.jsx";
import "./styles.css";

// Dil sağlayıcısı EN DIŞTA: giriş ekranı da (henüz oturum yokken) çeviriye
// erişebilmeli — dil tercihi hesaba değil cihaza aittir.
createRoot(document.getElementById("root")).render(
  <LangProvider>
    <App />
  </LangProvider>,
);

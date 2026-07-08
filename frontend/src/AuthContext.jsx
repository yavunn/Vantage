// Hafif auth context (Faz 2): /api/me çıktısı (hesap + rol + geliştirici
// profili) alt bileşenlere buradan akar; ayrı state kütüphanesi yok.
import { createContext, useContext } from "react";

export const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

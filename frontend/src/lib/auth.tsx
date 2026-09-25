"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, refreshSession } from "./api";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  can: (permission: string) => boolean;
  reload: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    // Restore the session from the httpOnly refresh cookie on first load.
    refreshSession().then(async (ok) => { if (ok) await reload(); }).finally(() => setLoading(false));
    const onLogout = () => setUser(null);
    window.addEventListener("ie:logout", onLogout);
    return () => window.removeEventListener("ie:logout", onLogout);
  }, [reload]);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  const can = useCallback((p: string) => !!user?.permissions?.includes(p), [user]);

  return <AuthContext.Provider value={{ user, loading, can, reload, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

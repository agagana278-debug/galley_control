import { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
  fetchAuthConfig,
  fetchCurrentUser,
  loginUser,
  logoutUser,
  registerStudent,
  registerUnauthorizedHandler,
} from "../api/client";

const AuthContext = createContext(null);

export function getDefaultRouteForRole(role) {
  if (role === "student") return "/student";
  if (role === "outlet_manager") return "/manager";
  if (role === "admin") return "/admin";
  return "/login";
}

export function getRoleLabel(role) {
  if (role === "student") return "Student";
  if (role === "outlet_manager") return "Outlet Manager";
  if (role === "admin") return "System Admin";
  return "Guest";
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [authConfig, setAuthConfig] = useState({
    environment: "production",
    demo_mode: false,
    registration_enabled: true,
    email_reset_configured: false,
    ai_provider: "unconfigured",
    ai_live_configured: false,
  });
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    registerUnauthorizedHandler(() => {
      setUser(null);
    });

    let cancelled = false;

    Promise.allSettled([fetchCurrentUser(), fetchAuthConfig()])
      .then(([meRes, cfgRes]) => {
        if (cancelled) return;
        if (meRes.status === "fulfilled") {
          setUser(meRes.value?.user || null);
        } else {
          setUser(null);
        }
        if (cfgRes.status === "fulfilled" && cfgRes.value) {
          setAuthConfig(cfgRes.value);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setAuthLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (identifier, password) => {
    const res = await loginUser(identifier, password);
    setUser(res.user);
    return res.user;
  }, []);

  const register = useCallback(async (payload) => {
    const res = await registerStudent(payload);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutUser();
    } catch {
      // Clear state even if server session already expired
    } finally {
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, authConfig, authLoading, login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside an AuthProvider");
  }
  return ctx;
}

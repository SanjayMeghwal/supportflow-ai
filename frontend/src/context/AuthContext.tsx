/**
 * SupportFlow AI — AuthContext & Provider
 * Manages client authentication state, token storage, and user profile lifecycle.
 */

import React, { createContext, useContext, useEffect, useState } from "react";
import { authApi, apiClient } from "@/services/api";
import { LoginPayload, RegisterPayload, User } from "@/types";

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (payload: LoginPayload) => Promise<User>;
  register: (payload: RegisterPayload) => Promise<User>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => apiClient.getToken());
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const fetchCurrentUser = async () => {
    try {
      const currentUser = await authApi.getMe();
      setUser(currentUser);
      setToken(apiClient.getToken());
    } catch {
      setUser(null);
      setToken(null);
      apiClient.setToken(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // Intercept 401s from any API request
    apiClient.onUnauthorized(() => {
      setUser(null);
      setToken(null);
    });

    if (apiClient.getToken()) {
      fetchCurrentUser();
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (payload: LoginPayload): Promise<User> => {
    setIsLoading(true);
    try {
      const response = await authApi.login(payload);
      setUser(response.user);
      setToken(response.access_token);
      return response.user;
    } finally {
      setIsLoading(false);
    }
  };

  const register = async (payload: RegisterPayload): Promise<User> => {
    setIsLoading(true);
    try {
      const newUser = await authApi.register(payload);
      // Automatically log in after registration
      await login({ email: payload.email, password: payload.password });
      return newUser;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    authApi.logout();
    setUser(null);
    setToken(null);
  };

  const refreshUser = async () => {
    await fetchCurrentUser();
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

type DisplayCurrency = "AUD" | "USD";

interface CurrencyContextType {
  displayCurrency: DisplayCurrency;
  toggleCurrency: () => void;
  setCurrency: (c: DisplayCurrency) => void;
}

const CurrencyContext = createContext<CurrencyContextType | null>(null);

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [displayCurrency, setDisplayCurrency] = useState<DisplayCurrency>(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("display_currency") as DisplayCurrency) || "AUD";
    }
    return "AUD";
  });

  const setCurrency = useCallback((c: DisplayCurrency) => {
    setDisplayCurrency(c);
    localStorage.setItem("display_currency", c);
  }, []);

  const toggleCurrency = useCallback(() => {
    setCurrency(displayCurrency === "AUD" ? "USD" : "AUD");
  }, [displayCurrency, setCurrency]);

  return (
    <CurrencyContext.Provider value={{ displayCurrency, toggleCurrency, setCurrency }}>
      {children}
    </CurrencyContext.Provider>
  );
}

export function useCurrency() {
  const ctx = useContext(CurrencyContext);
  if (!ctx) throw new Error("useCurrency must be used within CurrencyProvider");
  return ctx;
}

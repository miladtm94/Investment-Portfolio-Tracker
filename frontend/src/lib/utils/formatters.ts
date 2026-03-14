/**
 * Formatters — AUD-primary with optional currency override.
 *
 * Default currency is AUD (Australian Dollar) throughout.
 * All functions accept an optional `currency` parameter for
 * non-AUD display (e.g. for raw USD transaction amounts).
 */

// ─── Currency ────────────────────────────────────────────────────────────────

/**
 * Format a monetary amount.
 * Defaults to AUD with en-AU locale (e.g. "$1,234.56" with AU locale conventions).
 */
export function formatCurrency(
  value: number,
  compact = false,
  currency = "AUD",
): string {
  const locale = currency === "AUD" ? "en-AU" : "en-US";
  if (compact && Math.abs(value) >= 1_000_000) {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/** Alias: explicitly format as AUD. */
export const formatAUD = (value: number, compact = false) =>
  formatCurrency(value, compact, "AUD");

// ─── Percent ─────────────────────────────────────────────────────────────────

/**
 * Percentage formatter — always includes sign for non-zero values.
 */
export function formatPercent(value: number, decimals = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

// ─── Numbers ─────────────────────────────────────────────────────────────────

/**
 * Generic number formatter.
 */
export function formatNumber(value: number, decimals = 2): string {
  return new Intl.NumberFormat("en-AU", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

// ─── Dates ───────────────────────────────────────────────────────────────────

/**
 * Australian short date: 14 Mar 2026  (DD Mon YYYY)
 */
export function formatDate(date: string | Date): string {
  return new Date(date).toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * Australian numeric date: 14/03/2026  (DD/MM/YYYY)
 */
export function formatDateNumeric(date: string | Date): string {
  return new Date(date).toLocaleDateString("en-AU");
}

/**
 * Australian financial year label: "2024-25" from a calendar year end.
 * Pass the FY end year (e.g. 2025 → "2024-25").
 */
export function formatFinancialYear(fyEndYear: number): string {
  return `${fyEndYear - 1}-${String(fyEndYear).slice(2)}`;
}

/**
 * Derive the current Australian financial year end year.
 * FY ends 30 June — so if month >= 7, we're in the next FY.
 */
export function currentAUFinancialYear(): number {
  const now = new Date();
  return now.getMonth() >= 6 ? now.getFullYear() + 1 : now.getFullYear();
}

/**
 * Relative time: "2 hours ago"
 */
export function formatRelativeTime(date: string | Date): string {
  const diff = Date.now() - new Date(date).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

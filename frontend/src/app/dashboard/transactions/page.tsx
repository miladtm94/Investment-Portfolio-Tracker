"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, apiSlow } from "@/lib/api/client";
import { formatCurrency, formatDate } from "@/lib/utils/formatters";
import {
  Plus, Upload, X, ChevronDown, ChevronRight, Trash2,
  FileText, AlertTriangle, Eye, EyeOff, Key, RefreshCw, Loader2, Check,
  FlaskConical, Briefcase,
} from "lucide-react";
import clsx from "clsx";
import { useDropzone } from "react-dropzone";
import toast from "react-hot-toast";

// ─── Type Styles ──────────────────────────────────────────────────────────

const TYPE_STYLES: Record<string, string> = {
  BUY: "text-green-400 bg-green-400/10",
  SELL: "text-red-400 bg-red-400/10",
  DIVIDEND: "text-blue-400 bg-blue-400/10",
  DISTRIBUTION: "text-blue-400 bg-blue-400/10",
  STAKE_REWARD: "text-purple-400 bg-purple-400/10",
  TRANSFER_IN: "text-teal-400 bg-teal-400/10",
  TRANSFER_OUT: "text-orange-400 bg-orange-400/10",
  FEE: "text-gray-400 bg-gray-400/10",
  DEPOSIT: "text-green-400 bg-green-400/10",
  WITHDRAWAL: "text-red-400 bg-red-400/10",
  INTEREST: "text-cyan-400 bg-cyan-400/10",
};

const TYPE_LABELS: Record<string, string> = {
  BUY: "Buy",
  SELL: "Sell",
  DIVIDEND: "Dividend",
  DISTRIBUTION: "Distribution",
  STAKE_REWARD: "Staking",
  TRANSFER_IN: "Transfer In",
  TRANSFER_OUT: "Transfer Out",
  FEE: "Fee",
  DEPOSIT: "Deposit",
  WITHDRAWAL: "Withdrawal",
  INTEREST: "Interest",
};

const MANUAL_TRANSACTION_TYPES = [
  "BUY",
  "SELL",
  "DIVIDEND",
  "DISTRIBUTION",
  "TRANSFER_IN",
  "TRANSFER_OUT",
  "FEE",
  "DEPOSIT",
  "WITHDRAWAL",
  "INTEREST",
] as const;

const API_TRANSACTION_SOURCES = new Set(["KRAKEN_API", "COINBASE", "BINANCE", "IBKR_API", "PLAID"]);
const ASSET_REQUIRED_TYPES = new Set([
  "BUY",
  "SELL",
  "DIVIDEND",
  "DISTRIBUTION",
  "TRANSFER_IN",
  "TRANSFER_OUT",
]);

type ManualTransactionForm = {
  transacted_at: string;
  transaction_type: string;
  asset_symbol: string;
  quantity: string;
  price_per_unit: string;
  fees: string;
  net_amount: string;
  currency: string;
  notes: string;
};

type PayoutProjection = {
  symbol: string;
  transaction_type: string;
  next_date: string;
  cadence_months: number;
  quantity: number | null;
  price_per_unit: number | null;
  net_amount: number;
  currency: string;
};

function initialManualForm(currency: string): ManualTransactionForm {
  return {
    transacted_at: new Date().toISOString().slice(0, 10),
    transaction_type: "BUY",
    asset_symbol: "",
    quantity: "",
    price_per_unit: "",
    fees: "0",
    net_amount: "",
    currency,
    notes: "",
  };
}

function toDateInput(value: string | Date): string {
  return new Date(value).toISOString().slice(0, 10);
}

function addMonths(dateStr: string, months: number): string {
  const date = new Date(`${dateStr}T12:00:00`);
  const originalDay = date.getDate();
  date.setMonth(date.getMonth() + months);
  if (date.getDate() < originalDay) {
    date.setDate(0);
  }
  return date.toISOString().slice(0, 10);
}

function monthDiff(a: string, b: string): number {
  const first = new Date(`${a}T12:00:00`);
  const second = new Date(`${b}T12:00:00`);
  return (second.getFullYear() - first.getFullYear()) * 12 + second.getMonth() - first.getMonth();
}

function inferCadenceMonths(sortedDates: string[]): number {
  if (sortedDates.length < 2) return 3;
  const diff = monthDiff(sortedDates[sortedDates.length - 2], sortedDates[sortedDates.length - 1]);
  if (diff <= 4) return 3;
  if (diff <= 8) return 6;
  return 12;
}

// Demo account prefix — accounts with this name prefix are treated as demo
const DEMO_PREFIX = "Demo - ";

// Demo portfolios to load
const DEMO_PORTFOLIOS = [
  {
    name: `${DEMO_PREFIX}CommSec`,
    institution: "CommSec",
    type: "BROKERAGE",
    currency: "AUD",
    file: "/samples/demo_commsec.csv",
    description: "26 ASX trades — CBA, BHP, CSL, NDQ, VAS and more",
  },
  {
    name: `${DEMO_PREFIX}Kraken`,
    institution: "Kraken",
    type: "CRYPTO_EXCHANGE",
    currency: "USD",
    file: "/samples/demo_kraken.csv",
    description: "17 crypto trades — BTC, ETH, SOL",
  },
  {
    name: `${DEMO_PREFIX}IBKR`,
    institution: "Interactive Brokers (IBKR)",
    type: "BROKERAGE",
    currency: "USD",
    file: "/samples/demo_ibkr.csv",
    description: "19 US equity trades — NVDA, AAPL, MSFT, META, AMZN",
  },
];

// ─── Broker Definitions ───────────────────────────────────────────────────

interface BrokerInfo {
  id: string;
  label: string;
  country: string;
  currency: string;
  instructions: string[];
  fileTypes: string;
  notes?: string;
  supportsApiSync?: boolean;
  apiProvider?: string;
  apiCredentialType?: "exchange_key" | "ibkr_flex";
  apiPanelTitle?: string;
  apiKeyLabel?: string;
  apiKeyPlaceholder?: string;
  apiSecretLabel?: string;
  apiSecretPlaceholder?: string;
  apiWarning?: string;
  apiInstructions?: string[];
  allowPortfolioName?: boolean;
}

const BROKERS: BrokerInfo[] = [
  {
    id: "betashares_direct",
    label: "Betashares Direct",
    country: "AU",
    currency: "AUD",
    instructions: [
      "Login to the Betashares Direct web app (the export is not currently available through a public investor API)",
      "Open Activity and set the start date early enough to include your complete transaction history",
      "Select Export to download the full Activity CSV",
      "For holdings transferred from another broker, make sure the original parcel purchase dates and cost bases have been recorded in Betashares Direct",
      "Upload the CSV below; fractional ASX units are supported",
    ],
    fileTypes: "Activity CSV",
    notes: "Consolidated holdings: import into one Betashares account here, then exclude the old portfolio accounts from Dashboard calculations to avoid double-counting. Keep the old records until you have confirmed every transferred parcel and cost base.",
    allowPortfolioName: true,
  },
  {
    id: "commsec",
    label: "CommSec",
    country: "AU",
    currency: "AUD",
    instructions: [
      "Login to your CommSec account",
      "Go to Trade > Manage Orders > Confirmations",
      "Select the date range and click Search",
      "Click the Download CSV link",
      "Upload your file below",
    ],
    fileTypes: "CSV",
  },
  {
    id: "cmc",
    label: "CMC Invest",
    country: "AU",
    currency: "AUD",
    instructions: [
      "Login to your CMC Invest account",
      "Click on Account",
      "Select Confirmations",
      "Select the Open Advanced Search option",
      "Set Start Date to include all trading history; End date to today's date",
      "Download as a CSV file",
      "Upload your file below",
    ],
    fileTypes: "CSV",
  },
  {
    id: "ibkr",
    label: "Interactive Brokers (IBKR)",
    country: "INTL",
    currency: "USD",
    instructions: [
      "Login to your Interactive Brokers account",
      "Click on the Reports tab and select Flex Queries",
      "Click '+' next to Activity Flex Query",
      "Select Trades under Sections",
      "Select Executions on the pop up window",
      "Tick SELECT ALL and click Save",
      "Enter a Query Name",
      "Change Date Format to mm/dd/yyyy under General Configuration",
      "Click Create",
      "Run the Activity Flex Query",
      "Under Period, select Custom Date Range to cover all trades",
      "Set Format as CSV, click Run and download your trades",
      "Upload your file below",
    ],
    fileTypes: "CSV",
    notes: "For dividend and distribution data, also export the 'Dividends' and 'Payments in Lieu of Dividends' sections in your Flex Query.",
    supportsApiSync: true,
    apiProvider: "IBKR",
    apiCredentialType: "ibkr_flex",
    apiPanelTitle: "How to set up IBKR Flex Web Service",
    apiKeyLabel: "Flex Query ID",
    apiKeyPlaceholder: "e.g. 123456",
    apiSecretLabel: "Flex Web Service Token",
    apiSecretPlaceholder: "Paste your IBKR Flex token",
    apiWarning: "Use an Activity Flex Query in XML format. The token/query ID only grants statement-report access; do not share your IBKR username, password, or trading session.",
    apiInstructions: [
      "Login to the IBKR Client Portal",
      "Go to Performance & Reports > Flex Queries",
      "Create a new Activity Flex Query or edit an existing one",
      "In Sections, include Trades > Executions and Cash Transactions",
      "For dividend tracking, make sure Cash Transactions includes Dividends, Withholding Tax, Interest, Fees and Deposits/Withdrawals",
      "Set the Period to include your full investing history, or use a rolling range only after you have imported history once",
      "Under General Configuration, set Format to XML and Date Format to yyyyMMdd",
      "Save the query, then copy its Flex Query ID",
      "Go to Performance & Reports > Flex Web Service",
      "Enable Flex Web Service if needed, generate/copy the Current Token, then paste the Query ID and Token below",
    ],
  },
  {
    id: "stake",
    label: "Stake",
    country: "AU",
    currency: "USD",
    instructions: [
      "Login to your Stake account",
      "Go to Activity or Trade History",
      "Select your date range",
      "Click Export or Download as CSV",
      "Upload your file below",
    ],
    fileTypes: "CSV",
  },
  {
    id: "moomoo",
    label: "Moomoo",
    country: "AU",
    currency: "USD",
    instructions: [
      "Login to your Moomoo account",
      "Select Account on the left navigation bar (bottom bar on mobile)",
      "Select More if using the mobile app",
      "Select Tax Documents",
      "Select Sync to Sharesight, then select Manual Import",
      "Select the date range to cover all trading history",
      "Click Download",
      "Upload your file below",
    ],
    fileTypes: "CSV",
  },
  {
    id: "kraken",
    label: "Kraken",
    country: "INTL",
    currency: "USD",
    instructions: [
      "Login to your Kraken account",
      "Go to History > Export",
      "Select 'Trades' as the export type",
      "Choose your date range (select all for complete history)",
      "Click Export and download the CSV file",
      "Upload your file below",
    ],
    fileTypes: "CSV",
    supportsApiSync: true,
    apiProvider: "KRAKEN",
    apiInstructions: [
      "Login to your Kraken Pro account",
      "Go to Settings > API",
      "Click Generate New Key and give it a name (e.g. InvestIQ)",
      "Under Funds permissions: enable Query",
      "Under Orders and trades: enable Query closed orders & trades",
      "Under Data: enable Query ledger entries",
      "Do NOT enable Deposit, Withdraw, Create/Modify/Cancel orders",
      "Click Generate key, then copy your API Key and Private Key below",
    ],
  },
];

// ─── Currency Display ─────────────────────────────────────────────────────

function formatInCurrency(value: number | null | undefined, currency: string = "AUD"): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(currency === "AUD" ? "en-AU" : "en-US", {
    style: "currency",
    currency: currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
}

// ─── Broker Upload Panel ──────────────────────────────────────────────────

function BrokerUploadPanel({
  broker,
  accounts,
  onImportDone,
}: {
  broker: BrokerInfo;
  accounts: any[];
  onImportDone: () => void;
}) {
  const [showInstructions, setShowInstructions] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [portfolioName, setPortfolioName] = useState(broker.label);
  const queryClient = useQueryClient();

  const targetAccountName = portfolioName.trim() || broker.label;
  const existingAccount = accounts.find((a: any) =>
    !a.name.startsWith(DEMO_PREFIX) && (
      broker.allowPortfolioName
        ? a.name === targetAccountName
        : a.institution_name === broker.label || a.name === broker.label
    )
  );

  const getOrCreateAccountId = async (): Promise<string | null> => {
    if (existingAccount) return existingAccount.id;

    setIsCreating(true);
    try {
      const resp = await api.post("/portfolio/accounts", {
        name: targetAccountName,
        institution_name: broker.label,
        account_type: broker.id === "kraken" ? "CRYPTO_EXCHANGE" : "BROKERAGE",
        currency: broker.currency,
      });
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      return resp.data.id;
    } catch {
      toast.error("Failed to create account");
      return null;
    } finally {
      setIsCreating(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: {
      "text/csv": [".csv"],
      "text/plain": [".csv", ".txt"],
      "application/csv": [".csv"],
      "text/x-csv": [".csv"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/octet-stream": [".csv", ".txt"],
    },
    disabled: isCreating,
    onDrop: async (files) => {
      const accountId = await getOrCreateAccountId();
      if (!accountId) return;

      const file = files[0];
      const formData = new FormData();
      formData.append("file", file);
      formData.append("account_id", accountId);
      formData.append("broker_hint", broker.id);

      const toastId = toast.loading(`Importing ${file.name}…`);
      try {
        // Do NOT set Content-Type manually — axios sets multipart/form-data with boundary automatically
        const resp = await api.post("/transactions/import", formData);
        const r = resp.data;
        const brokerLabel = r.broker_detected && r.broker_detected !== "Unknown"
          ? ` (${r.broker_detected})` : "";
        toast.success(
          `Imported ${r.imported} transaction${r.imported !== 1 ? "s" : ""}${brokerLabel}` +
          (r.duplicates ? ` · ${r.duplicates} duplicates skipped` : "") +
          (r.errors ? ` · ${r.errors} errors` : ""),
          { id: toastId, duration: 5000 }
        );
        queryClient.invalidateQueries({ queryKey: ["transactions"] });
        queryClient.invalidateQueries({ queryKey: ["portfolio"] });
        queryClient.invalidateQueries({ queryKey: ["analytics"] });
        onImportDone();
      } catch (e: any) {
        toast.error(`Import failed: ${e?.response?.data?.detail ?? "Check file format."}`, { id: toastId });
      }
    },
  });

  return (
    <div className="space-y-4">
      {/* Instructions */}
      <div className="bg-gray-800/40 rounded-lg border border-gray-700/50 overflow-hidden">
        <button
          onClick={() => setShowInstructions((s) => !s)}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-800/60 transition-colors"
        >
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-blue-400" />
            <span className="text-sm font-medium text-gray-200">
              How to export from {broker.label}
            </span>
          </div>
          {showInstructions ? <ChevronDown className="w-4 h-4 text-gray-500" /> : <ChevronRight className="w-4 h-4 text-gray-500" />}
        </button>
        {showInstructions && (
          <div className="px-4 pb-4 pt-1">
            <ol className="space-y-2 ml-1">
              {broker.instructions.map((step, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-500/20 text-blue-400 text-xs font-medium flex items-center justify-center mt-0.5">
                    {i + 1}
                  </span>
                  <span className="text-gray-400">{step}</span>
                </li>
              ))}
            </ol>
            {broker.notes && (
              <div className="mt-3 flex items-start gap-2 text-xs text-amber-400 bg-amber-400/10 rounded-lg px-3 py-2">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                <span>{broker.notes}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Account info */}
      {broker.allowPortfolioName && (
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1.5">
            Portfolio name
          </label>
          <input
            type="text"
            value={portfolioName}
            onChange={(event) => setPortfolioName(event.target.value)}
            placeholder="e.g. Betashares Direct – Consolidated"
            className="w-full px-3 py-2.5 bg-gray-800/60 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30"
          />
          <p className="mt-1.5 text-xs text-gray-500">
            Use one name for a consolidated account, or a different name for each Managed or Custom Portfolio export.
          </p>
        </div>
      )}

      {existingAccount && (
        <div className="flex items-center gap-2 text-xs text-gray-400 bg-gray-800/30 rounded-lg px-3 py-2 border border-gray-800">
          <span>Importing into existing account: <strong className="text-gray-200">{existingAccount.name}</strong> ({existingAccount.currency})</span>
        </div>
      )}

      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={clsx(
          "border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all",
          isCreating && "opacity-40 pointer-events-none",
          isDragActive ? "border-blue-500 bg-blue-500/10" : "border-gray-700 hover:border-gray-600"
        )}
      >
        <input {...getInputProps()} />
        <Upload className="w-6 h-6 text-gray-500 mx-auto mb-2" />
        <p className="text-gray-300 text-sm">
          {isCreating
            ? "Creating account…"
            : isDragActive
              ? "Drop your file here"
              : `Drop your ${broker.label} ${broker.fileTypes} file here`}
        </p>
        <p className="text-gray-600 text-xs mt-1">
          or click to browse · Trades in {broker.currency} will be auto-detected
        </p>
        {!existingAccount && (
          <p className="text-gray-500 text-xs mt-2">
            A {broker.label} account will be created automatically on upload
          </p>
        )}
      </div>
    </div>
  );
}

// ─── API Sync Panel ─────────────────────────────────────────────────────

function ApiSyncPanel({
  broker,
  accounts,
  onImportDone,
}: {
  broker: BrokerInfo;
  accounts: any[];
  onImportDone: () => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ imported: number; error?: string; mode?: string } | null>(null);
  const queryClient = useQueryClient();
  const isIbkrFlex = broker.apiCredentialType === "ibkr_flex";
  const apiKeyLabel = broker.apiKeyLabel ?? "API Key";
  const apiSecretLabel = broker.apiSecretLabel ?? "Private Key (Secret)";
  const apiKeyPlaceholder = broker.apiKeyPlaceholder ?? "Enter your API Key";
  const apiSecretPlaceholder = broker.apiSecretPlaceholder ?? "Enter your Private Key";
  const supportsRecentSync = broker.id === "kraken";

  const existingAccount = accounts.find(
    (a: any) => !a.name.startsWith(DEMO_PREFIX) && (a.institution_name === broker.label || a.name === broker.label)
  );

  const isConnected = existingAccount?.sync_status === "SYNCED" || existingAccount?.sync_status === "ERROR";

  const getOrCreateAccountId = async (): Promise<string | null> => {
    if (existingAccount) return existingAccount.id;
    try {
      const resp = await api.post("/portfolio/accounts", {
        name: broker.label,
        institution_name: broker.label,
        account_type: broker.id === "kraken" ? "CRYPTO_EXCHANGE" : "BROKERAGE",
        currency: broker.currency,
      });
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      return resp.data.id;
    } catch {
      toast.error("Failed to create account");
      return null;
    }
  };

  const handleConnect = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      toast.error(`Please enter both ${apiKeyLabel} and ${apiSecretLabel}`);
      return;
    }

    setIsConnecting(true);
    setSyncResult(null);
    try {
      const accountId = await getOrCreateAccountId();
      if (!accountId) return;

      if (isIbkrFlex) {
        await api.post("/sync/connect/broker", {
          account_id: accountId,
          provider: broker.apiProvider,
          query_id: apiKey.trim(),
          access_token: apiSecret.trim(),
        });
      } else {
        await api.post("/sync/connect/exchange", {
          account_id: accountId,
          provider: broker.apiProvider,
          api_key: apiKey.trim(),
          api_secret: apiSecret.trim(),
        });
      }

      toast.success("API credentials saved. Syncing transactions...");

      setIsSyncing(true);
      const syncResp = await apiSlow.post(`/sync/accounts/${accountId}/trigger`);
      const result = syncResp.data;

      if (result.error) {
        setSyncResult({ imported: 0, error: result.error });
        toast.error(`Sync error: ${result.error}`);
      } else {
        setSyncResult({ imported: result.imported, mode: result.mode });
        toast.success(`Imported ${result.imported} transaction${result.imported !== 1 ? "s" : ""} from ${broker.label}`);
        queryClient.invalidateQueries({ queryKey: ["transactions"] });
        queryClient.invalidateQueries({ queryKey: ["portfolio"] });
        queryClient.invalidateQueries({ queryKey: ["analytics"] });
        onImportDone();
      }
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? "Connection failed. Check your API credentials.";
      setSyncResult({ imported: 0, error: detail });
      toast.error(detail);
    } finally {
      setIsConnecting(false);
      setIsSyncing(false);
    }
  };

  const handleResync = async () => {
    if (!existingAccount) return;
    setIsSyncing(true);
    setSyncResult(null);
    try {
      const syncResp = await apiSlow.post(
        `/sync/accounts/${existingAccount.id}/trigger${supportsRecentSync ? "?recent=true" : ""}`
      );
      const result = syncResp.data;
      if (result.error) {
        setSyncResult({ imported: 0, error: result.error });
        toast.error(`Sync error: ${result.error}`);
      } else {
        setSyncResult({ imported: result.imported, mode: result.mode });
        const syncScope = result.mode === "recent" ? "recent " : "";
        toast.success(`Imported ${result.imported} ${syncScope}transaction${result.imported !== 1 ? "s" : ""}`);
        queryClient.invalidateQueries({ queryKey: ["transactions"] });
        queryClient.invalidateQueries({ queryKey: ["portfolio"] });
        queryClient.invalidateQueries({ queryKey: ["analytics"] });
      }
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? "Sync failed");
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-gray-800/40 rounded-lg border border-gray-700/50 px-4 py-3">
        <div className="flex items-center gap-2 mb-2">
          <Key className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-medium text-gray-200">
            {broker.apiPanelTitle ?? `How to get your ${broker.label} API Key`}
          </span>
        </div>
        <ol className="space-y-1.5 ml-1">
          {broker.apiInstructions?.map((step, i) => (
            <li key={i} className="flex gap-3 text-sm">
              <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-500/20 text-blue-400 text-xs font-medium flex items-center justify-center mt-0.5">
                {i + 1}
              </span>
              <span className="text-gray-400">{step}</span>
            </li>
          ))}
        </ol>
        <div className="mt-3 flex items-start gap-2 text-xs text-amber-400 bg-amber-400/10 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span>{broker.apiWarning ?? "Only grant read-only permissions. Never enable trading or withdrawal access for third-party apps."}</span>
        </div>
      </div>

      {existingAccount && (
        <div className="flex items-center justify-between text-xs bg-gray-800/30 rounded-lg px-3 py-2 border border-gray-800">
          <span className="text-gray-400">
            Account: <strong className="text-gray-200">{existingAccount.name}</strong>
            {existingAccount.last_synced_at && (
              <> · Last synced: {new Date(existingAccount.last_synced_at).toLocaleString()}</>
            )}
          </span>
          {isConnected && (
            <button
              onClick={handleResync}
              disabled={isSyncing}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
            >
              {isSyncing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              {isSyncing ? "Syncing..." : supportsRecentSync ? "Sync recent" : "Sync account"}
            </button>
          )}
        </div>
      )}

      {(!isConnected || isIbkrFlex) && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">{apiKeyLabel}</label>
            <input
              type="text"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={apiKeyPlaceholder}
              className="w-full px-3 py-2.5 bg-gray-800/60 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">{apiSecretLabel}</label>
            <div className="relative">
              <input
                type={showSecret ? "text" : "password"}
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                placeholder={apiSecretPlaceholder}
                className="w-full px-3 py-2.5 bg-gray-800/60 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 font-mono pr-10"
              />
              <button
                type="button"
                onClick={() => setShowSecret(!showSecret)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              >
                {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <button
            onClick={handleConnect}
            disabled={isConnecting || !apiKey.trim() || !apiSecret.trim()}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {isConnecting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {isSyncing ? "Syncing transactions..." : "Connecting..."}
              </>
            ) : (
              <>
                <Key className="w-4 h-4" />
                {isConnected ? "Update Details & Sync" : "Connect & Sync"}
              </>
            )}
          </button>
        </div>
      )}

      {syncResult && (
        <div className={clsx(
          "flex items-center gap-2 text-sm rounded-lg px-4 py-3 border",
          syncResult.error
            ? "text-red-400 bg-red-400/10 border-red-400/20"
            : "text-green-400 bg-green-400/10 border-green-400/20"
        )}>
          {syncResult.error ? (
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          ) : (
            <Check className="w-4 h-4 flex-shrink-0" />
          )}
          <span>
            {syncResult.error
              ? syncResult.error
              : `Successfully imported ${syncResult.imported} transaction${syncResult.imported !== 1 ? "s" : ""}`}
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Account Card with Transactions ───────────────────────────────────────

function AccountCard({
  account,
  transactions,
  onToggle,
  onRemove,
  isDemo,
}: {
  account: any;
  transactions: any[];
  onToggle: (id: string, active: boolean) => void;
  onRemove: (id: string, name: string) => void;
  isDemo?: boolean;
}) {
  const [expanded, setExpanded] = useState(account.is_active);
  const [showManualForm, setShowManualForm] = useState(false);
  const [manualForm, setManualForm] = useState<ManualTransactionForm>(() => initialManualForm(account.currency || "AUD"));
  const queryClient = useQueryClient();
  const isActive = account.is_active;
  const txCount = transactions.length;
  const isInflow = (t: string) =>
    ["BUY", "TRANSFER_IN", "DEPOSIT", "STAKE_REWARD", "DIVIDEND", "DISTRIBUTION", "INTEREST"].includes(t);
  const isApiManaged =
    Boolean(account.has_api_connection) ||
    account.sync_status === "SYNCED" ||
    account.sync_status === "SYNCING" ||
    account.sync_status === "ERROR" ||
    transactions.some((t: any) => API_TRANSACTION_SOURCES.has(t.source));
  const canSyncApi = !isDemo && Boolean(account.has_api_connection);
  const apiProvider = String(account.api_provider || account.institution_name || account.name || "").toUpperCase();
  const supportsRecentSync = apiProvider.includes("KRAKEN");
  const canAddManual = !isDemo && !isApiManaged;
  const manualTxnType = manualForm.transaction_type;
  const isIncomeRow = ["DIVIDEND", "DISTRIBUTION", "INTEREST"].includes(manualTxnType);
  const isBuySellRow = ["BUY", "SELL"].includes(manualTxnType);
  const quantityLabel = isIncomeRow ? "Units held" : "Qty";
  const priceLabel = isIncomeRow ? "Payout/unit" : "Price";
  const amountPlaceholder = isIncomeRow || isBuySellRow ? "Auto" : "Optional";
  const manualHelpText = isIncomeRow
    ? "For ETF distributions/dividends: enter one row per symbol and payment/ex-date. Units held × payout/unit − tax/fees becomes the positive income amount."
    : "BUY/SELL amounts are calculated from quantity × price ± fees if Amount is blank. Dashboard and Analytics refresh after save.";
  const payoutProjections: PayoutProjection[] = Object.values(
    transactions
      .filter((txn: any) => ["DIVIDEND", "DISTRIBUTION"].includes(txn.transaction_type) && txn.symbol && txn.net_amount)
      .reduce((acc: Record<string, any[]>, txn: any) => {
        const symbol = txn.symbol;
        if (!acc[symbol]) acc[symbol] = [];
        acc[symbol].push(txn);
        return acc;
      }, {})
  )
    .map((rows: any[]) => {
      const sorted = [...rows].sort(
        (a, b) => new Date(a.transacted_at).getTime() - new Date(b.transacted_at).getTime()
      );
      const latest = sorted[sorted.length - 1];
      const dates = sorted.map((txn) => toDateInput(txn.transacted_at));
      const cadence = inferCadenceMonths(dates);
      return {
        symbol: latest.symbol,
        transaction_type: latest.transaction_type,
        next_date: addMonths(toDateInput(latest.transacted_at), cadence),
        cadence_months: cadence,
        quantity: latest.quantity ?? null,
        price_per_unit: latest.price_per_unit ?? null,
        net_amount: latest.net_amount,
        currency: latest.currency || account.currency || "AUD",
      };
    })
    .sort((a, b) => a.next_date.localeCompare(b.next_date) || a.symbol.localeCompare(b.symbol));

  const totalInvested = transactions
    .filter((t) => t.transaction_type === "BUY")
    .reduce((sum: number, t: any) => sum + Math.abs(t.net_amount ?? 0), 0);

  const setManualField = (field: keyof ManualTransactionForm, value: string) => {
    setManualForm((prev) => ({ ...prev, [field]: value }));
  };

  const parseOptionalNumber = (value: string) => {
    const trimmed = value.trim();
    return trimmed === "" ? undefined : Number(trimmed);
  };

  const createManualMutation = useMutation({
    mutationFn: () => {
      const txnType = manualForm.transaction_type;
      const requiresAsset = ASSET_REQUIRED_TYPES.has(txnType);
      const assetSymbol = manualForm.asset_symbol.trim().toUpperCase();
      if (requiresAsset && !assetSymbol) {
        throw new Error("Asset symbol is required for this transaction type.");
      }
      if (!manualForm.transacted_at) {
        throw new Error("Transaction date is required.");
      }

      return api.post("/transactions/", {
        account_id: account.id,
        asset_symbol: assetSymbol || undefined,
        transaction_type: txnType,
        quantity: parseOptionalNumber(manualForm.quantity),
        price_per_unit: parseOptionalNumber(manualForm.price_per_unit),
        fees: parseOptionalNumber(manualForm.fees) ?? 0,
        net_amount: parseOptionalNumber(manualForm.net_amount),
        currency: manualForm.currency.trim().toUpperCase() || account.currency || "AUD",
        transacted_at: new Date(`${manualForm.transacted_at}T12:00:00`).toISOString(),
        notes: manualForm.notes.trim() || undefined,
      }).then((r) => r.data);
    },
    onSuccess: async () => {
      toast.success("Transaction added");
      setManualForm(initialManualForm(account.currency || "AUD"));
      setShowManualForm(false);
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      await queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail ?? error?.message ?? "Failed to add transaction";
      toast.error(detail);
    },
  });

  const deleteTransactionMutation = useMutation({
    mutationFn: (transactionId: string) => api.delete(`/transactions/${transactionId}`),
    onSuccess: async () => {
      toast.success("Transaction deleted");
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      await queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (error: any) => {
      toast.error(error?.response?.data?.detail ?? "Failed to delete transaction");
    },
  });

  const syncAccountMutation = useMutation({
    mutationFn: () =>
      apiSlow
        .post(`/sync/accounts/${account.id}/trigger${supportsRecentSync ? "?recent=true" : ""}`)
        .then((response) => response.data),
    onSuccess: async (result) => {
      if (result?.error) {
        toast.error(`Sync error: ${result.error}`);
        return;
      }
      const syncScope = result?.mode === "recent" ? "recent " : "";
      toast.success(`Imported ${result?.imported ?? 0} ${syncScope}transaction${result?.imported === 1 ? "" : "s"}`);
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      await queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (error: any) => {
      toast.error(error?.response?.data?.detail ?? "Sync failed");
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["portfolio", "accounts", "all"] });
    },
  });

  const handleDeleteTransaction = (txn: any) => {
    const label = `${txn.transaction_type} ${txn.symbol || ""}`.trim();
    if (confirm(`Delete this transaction row?\n\n${label} · ${formatDate(txn.transacted_at)}\n\nDashboard and Analytics will be recalculated after deletion.`)) {
      deleteTransactionMutation.mutate(txn.id);
    }
  };

  const usePayoutProjection = (projection: PayoutProjection) => {
    setManualForm({
      transacted_at: projection.next_date,
      transaction_type: projection.transaction_type,
      asset_symbol: projection.symbol,
      quantity: projection.quantity != null ? String(projection.quantity) : "",
      price_per_unit: projection.price_per_unit != null ? String(projection.price_per_unit) : "",
      fees: "0",
      net_amount: String(projection.net_amount),
      currency: projection.currency,
      notes: `Projected ${projection.transaction_type.toLowerCase()} based on prior ${projection.symbol} payout; review before saving.`,
    });
    setShowManualForm(true);
  };

  return (
    <div className={clsx(
      "card-glass overflow-hidden transition-all",
      !isActive && "opacity-60",
      isDemo && "border-violet-500/20"
    )}>
      {/* Account Header */}
      <div className="flex items-center gap-3 p-4 border-b border-gray-800">
        {/* Checkbox */}
        <button
          onClick={() => onToggle(account.id, !isActive)}
          className={clsx(
            "flex-shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center transition-all",
            isActive
              ? "bg-blue-600 border-blue-600"
              : "border-gray-600 hover:border-gray-400"
          )}
          title={isActive ? "Included in dashboard — click to exclude" : "Excluded from dashboard — click to include"}
        >
          {isActive && (
            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
        </button>

        {/* Account Info */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex-1 flex items-center gap-3 text-left min-w-0"
        >
          <div className={clsx(
            "w-9 h-9 rounded-lg border flex items-center justify-center text-xs font-bold flex-shrink-0",
            isDemo
              ? "bg-violet-900/30 border-violet-700/40 text-violet-300"
              : "bg-gray-800 border-gray-700 text-gray-300"
          )}>
            {(account.institution_name || account.name).replace(DEMO_PREFIX, "").slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="font-medium text-gray-100 text-sm truncate flex items-center gap-2">
              {account.name.replace(DEMO_PREFIX, "")}
              {isDemo && (
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-violet-500/20 text-violet-400 font-medium flex-shrink-0">
                  demo
                </span>
              )}
            </div>
            <div className="text-xs text-gray-500 flex items-center gap-2">
              <span>{account.currency}</span>
              <span>·</span>
              <span>{txCount} transaction{txCount !== 1 ? "s" : ""}</span>
              {totalInvested > 0 && (
                <>
                  <span>·</span>
                  <span>{formatCurrency(totalInvested, true, account.currency)} invested</span>
                </>
              )}
            </div>
          </div>
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-gray-500 ml-auto flex-shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-500 ml-auto flex-shrink-0" />
          )}
        </button>

        {/* Status + Remove */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={clsx(
            "text-xs px-2 py-0.5 rounded-full font-medium",
            isActive
              ? "text-green-400 bg-green-400/10"
              : "text-gray-500 bg-gray-500/10"
          )}>
            {isActive ? "Active" : "Excluded"}
          </span>
          {isApiManaged && (
            <span
              className="text-xs px-2 py-0.5 rounded-full font-medium text-amber-400 bg-amber-400/10"
              title="Transactions for API-connected accounts are managed by provider sync."
            >
              API read-only
            </span>
          )}
          {canSyncApi && (
            <button
              onClick={() => syncAccountMutation.mutate()}
              disabled={syncAccountMutation.isPending || account.sync_status === "SYNCING"}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg text-blue-400 bg-blue-400/10 hover:bg-blue-400/20 transition-colors disabled:opacity-50 disabled:cursor-wait"
              title={supportsRecentSync ? "Fetch recent transactions for this API account" : "Fetch transactions for this API account"}
            >
              {syncAccountMutation.isPending || account.sync_status === "SYNCING" ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
              {syncAccountMutation.isPending || account.sync_status === "SYNCING"
                ? "Syncing..."
                : supportsRecentSync
                ? "Sync recent"
                : "Sync account"}
            </button>
          )}
          {canAddManual && (
            <button
              onClick={() => {
                setExpanded(true);
                setShowManualForm((s) => !s);
              }}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg text-blue-400 bg-blue-400/10 hover:bg-blue-400/20 transition-colors"
              title="Add a manual transaction to this CSV/manual portfolio"
            >
              <Plus className="w-3 h-3" />
              Add row
            </button>
          )}
          <button
            onClick={() => onRemove(account.id, account.name)}
            className="text-gray-600 hover:text-red-400 transition-colors p-1 rounded hover:bg-red-400/10"
            title="Permanently delete account and all transactions"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {expanded && isApiManaged && (
        <div className="px-4 py-2 text-xs text-amber-300 bg-amber-400/5 border-b border-amber-400/10">
          This portfolio is API-connected. Transactions are read-only here so provider sync remains the source of truth.
        </div>
      )}

      {expanded && showManualForm && canAddManual && (
        <div className="p-4 border-b border-gray-800 bg-gray-900/30">
          <div className="grid grid-cols-2 md:grid-cols-5 xl:grid-cols-10 gap-2">
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">Date</label>
              <input
                type="date"
                value={manualForm.transacted_at}
                onChange={(e) => setManualField("transacted_at", e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">Type</label>
              <select
                value={manualForm.transaction_type}
                onChange={(e) => setManualField("transaction_type", e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200"
              >
                {MANUAL_TRANSACTION_TYPES.map((type) => (
                  <option key={type} value={type}>{TYPE_LABELS[type] ?? type}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">Asset</label>
              <input
                value={manualForm.asset_symbol}
                onChange={(e) => setManualField("asset_symbol", e.target.value.toUpperCase())}
                placeholder={ASSET_REQUIRED_TYPES.has(manualForm.transaction_type) ? "Required" : "Optional"}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600 font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">{quantityLabel}</label>
              <input
                type="number"
                step="any"
                value={manualForm.quantity}
                onChange={(e) => setManualField("quantity", e.target.value)}
                placeholder="0"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600 font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">{priceLabel}</label>
              <input
                type="number"
                step="any"
                value={manualForm.price_per_unit}
                onChange={(e) => setManualField("price_per_unit", e.target.value)}
                placeholder={isIncomeRow ? "e.g. 0.125" : "Auto if blank"}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600 font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">Fees</label>
              <input
                type="number"
                step="any"
                value={manualForm.fees}
                onChange={(e) => setManualField("fees", e.target.value)}
                placeholder="0"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600 font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">Amount</label>
              <input
                type="number"
                step="any"
                value={manualForm.net_amount}
                onChange={(e) => setManualField("net_amount", e.target.value)}
                placeholder={amountPlaceholder}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600 font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 uppercase mb-1">CCY</label>
              <input
                value={manualForm.currency}
                onChange={(e) => setManualField("currency", e.target.value.toUpperCase())}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono"
                maxLength={5}
              />
            </div>
            <div className="col-span-2">
              <label className="block text-[10px] text-gray-500 uppercase mb-1">Notes</label>
              <input
                value={manualForm.notes}
                onChange={(e) => setManualField("notes", e.target.value)}
                placeholder="Optional"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600"
              />
            </div>
          </div>
          <div className="flex items-center justify-between gap-3 mt-3">
            <p className="text-xs text-gray-500">
              {manualHelpText}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowManualForm(false)}
                className="px-3 py-1.5 text-xs rounded-lg text-gray-400 hover:text-gray-200 border border-gray-700 hover:bg-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => createManualMutation.mutate()}
                disabled={createManualMutation.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition-colors"
              >
                {createManualMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                Save transaction
              </button>
            </div>
          </div>
          {payoutProjections.length > 0 && (
            <div className="mt-3 rounded-lg border border-blue-500/20 bg-blue-500/5 p-3">
              <div className="mb-2 text-xs font-medium text-blue-300">
                Project next payout from previous rows
              </div>
              <div className="flex flex-wrap gap-2">
                {payoutProjections.map((projection) => (
                  <button
                    key={`${projection.symbol}-${projection.next_date}`}
                    type="button"
                    onClick={() => usePayoutProjection(projection)}
                    className="rounded-lg border border-gray-700 bg-gray-900/60 px-2.5 py-1.5 text-left text-xs text-gray-300 hover:border-blue-500/50 hover:bg-blue-500/10 transition-colors"
                    title="Prefill the form. You can edit all fields before saving."
                  >
                    <span className="font-semibold text-gray-100">{projection.symbol}</span>
                    <span className="mx-1 text-gray-500">·</span>
                    <span>{projection.next_date}</span>
                    <span className="mx-1 text-gray-500">·</span>
                    <span>{formatCurrency(projection.net_amount, false, projection.currency)}</span>
                    <span className="ml-1 text-gray-500">({projection.cadence_months}m)</span>
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-gray-500">
                These are editable projections based on the latest saved payout and inferred cadence. Saving is manual.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Transactions Table */}
      {expanded && txCount > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800/50">
                <th className="text-left p-2.5 pl-4">Date</th>
                <th className="text-left p-2.5">Type</th>
                <th className="text-left p-2.5">Asset</th>
                <th className="text-right p-2.5">Qty</th>
                <th className="text-right p-2.5">Price</th>
                <th className="text-right p-2.5">Fees</th>
                <th className="text-right p-2.5">Amount</th>
                <th className="text-center p-2.5 pr-4">CCY</th>
                {canAddManual && <th className="text-right p-2.5 pr-4">Action</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/30">
              {transactions.map((txn: any) => {
                const typeStyle = TYPE_STYLES[txn.transaction_type] || "text-gray-400 bg-gray-400/10";
                const inflow = isInflow(txn.transaction_type);
                const ccy = txn.currency || "USD";

                return (
                  <tr key={txn.id} className="hover:bg-gray-800/20 transition-colors">
                    <td className="p-2.5 pl-4 text-gray-400 whitespace-nowrap text-xs">
                      {formatDate(txn.transacted_at)}
                    </td>
                    <td className="p-2.5">
                      <span className={clsx("text-xs font-medium px-2 py-0.5 rounded-full", typeStyle)}>
                        {TYPE_LABELS[txn.transaction_type] || txn.transaction_type}
                      </span>
                    </td>
                    <td className="p-2.5 font-medium text-gray-100 text-xs">
                      {txn.symbol || "—"}
                    </td>
                    <td className="p-2.5 text-right font-mono text-xs">
                      {txn.quantity != null ? (
                        <span className={inflow ? "text-green-400" : "text-red-400"}>
                          {inflow ? "+" : "-"}{Math.abs(txn.quantity).toLocaleString(undefined, { maximumFractionDigits: 6 })}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="p-2.5 text-right font-mono text-gray-400 text-xs">
                      {txn.price_per_unit ? formatInCurrency(txn.price_per_unit, ccy) : "—"}
                    </td>
                    <td className="p-2.5 text-right font-mono text-gray-500 text-xs">
                      {txn.fees && txn.fees > 0 ? formatInCurrency(txn.fees, ccy) : "—"}
                    </td>
                    <td className="p-2.5 text-right font-mono text-xs font-medium">
                      {txn.net_amount != null ? (
                        <span className={txn.net_amount >= 0 ? "text-green-400" : "text-red-400"}>
                          {formatInCurrency(txn.net_amount, ccy)}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="p-2.5 pr-4 text-center">
                      <span className={clsx(
                        "text-xs px-1.5 py-0.5 rounded font-medium",
                        ccy === "AUD" ? "text-blue-400 bg-blue-400/10" :
                        ccy === "USD" ? "text-green-400 bg-green-400/10" :
                        "text-gray-400 bg-gray-400/10"
                      )}>
                        {ccy}
                      </span>
                    </td>
                    {canAddManual && (
                      <td className="p-2.5 pr-4 text-right">
                        <button
                          type="button"
                          onClick={() => handleDeleteTransaction(txn)}
                          disabled={deleteTransactionMutation.isPending}
                          className="inline-flex items-center justify-center rounded p-1 text-gray-600 hover:text-red-400 hover:bg-red-400/10 disabled:opacity-50 transition-colors"
                          title="Delete this transaction row"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {expanded && txCount === 0 && (
        <div className="p-6 text-center text-gray-500 text-sm">
          {canAddManual
            ? "No transactions yet. Import a CSV file or add a manual row to populate this account."
            : "No transactions yet. Sync this API-connected account from its provider."}
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────

export default function TransactionsPage() {
  const [showImport, setShowImport] = useState(false);
  const [selectedBroker, setSelectedBroker] = useState<BrokerInfo | null>(null);
  const [importTab, setImportTab] = useState<"csv" | "api">("csv");
  const [demoMode, setDemoMode] = useState(false);
  const [isDemoLoading, setIsDemoLoading] = useState(false);
  const queryClient = useQueryClient();

  const { data: allAccounts = [], isLoading: accountsLoading } = useQuery<any[]>({
    queryKey: ["portfolio", "accounts", "all"],
    queryFn: () => api.get("/portfolio/accounts/all").then((r) => r.data),
  });

  const { data: transactions = [], isLoading: txLoading } = useQuery({
    queryKey: ["transactions"],
    queryFn: () => api.get("/transactions/?limit=1000").then((r) => r.data),
  });

  // Separate real accounts from demo accounts
  const realAccounts = allAccounts.filter((a) => !a.name.startsWith(DEMO_PREFIX));
  const demoAccounts = allAccounts.filter((a) => a.name.startsWith(DEMO_PREFIX));
  const hasDemoAccounts = demoAccounts.length > 0;

  // Which accounts to display
  const displayAccounts = demoMode ? demoAccounts : realAccounts;

  // Group transactions by account_id
  const txByAccount = transactions.reduce((acc: Record<string, any[]>, txn: any) => {
    const key = txn.account_id;
    if (!acc[key]) acc[key] = [];
    acc[key].push(txn);
    return acc;
  }, {} as Record<string, any[]>);

  // Toggle account active/inactive
  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.patch(`/portfolio/accounts/${id}`, { is_active }).then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.is_active ? `${data.name} included in dashboard` : `${data.name} excluded from dashboard`);
      queryClient.setQueryData<any[]>(["portfolio", "accounts", "all"], (old) =>
        old?.map((account) => (account.id === data.id ? { ...account, ...data } : account)) ?? old
      );
      queryClient.invalidateQueries({ queryKey: ["portfolio", "accounts", "all"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio", "accounts"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: () => toast.error("Failed to update account"),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/portfolio/accounts/${id}`),
    onSuccess: () => {
      toast.success("Account and transactions permanently deleted");
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
    onError: () => toast.error("Failed to delete account"),
  });

  const handleToggle = (id: string, active: boolean) => {
    toggleMutation.mutate({ id, is_active: active });
  };

  const handleRemove = (id: string, name: string) => {
    if (confirm(`Permanently delete "${name}" and all its transactions?\n\nThis action cannot be undone. To temporarily exclude an account, use the checkbox instead.`)) {
      removeMutation.mutate(id);
    }
  };

  // Load all 3 demo portfolios from public CSV files
  const loadDemoPortfolio = async () => {
    setIsDemoLoading(true);
    const toastId = toast.loading("Loading demo portfolio…");
    let totalImported = 0;
    let totalDuplicates = 0;

    try {
      for (const demo of DEMO_PORTFOLIOS) {
        // Find or create demo account
        let existing = allAccounts.find((a) => a.name === demo.name);
        let accountId: string;

        if (!existing) {
          const resp = await api.post("/portfolio/accounts", {
            name: demo.name,
            institution_name: demo.institution,
            account_type: demo.type,
            currency: demo.currency,
          });
          accountId = resp.data.id;
          // Immediately exclude from dashboard so it doesn't affect real data
          await api.patch(`/portfolio/accounts/${accountId}`, { is_active: false });
        } else {
          accountId = existing.id;
        }

        // Fetch the demo CSV from the public folder
        const fileResp = await fetch(demo.file);
        if (!fileResp.ok) {
          toast.error(`Could not load demo file for ${demo.name}`, { id: toastId });
          continue;
        }
        const blob = await fileResp.blob();
        const fileName = demo.file.split("/").pop() ?? "demo.csv";
        const file = new File([blob], fileName, { type: "text/csv" });

        const formData = new FormData();
        formData.append("file", file);
        formData.append("account_id", accountId);

        const importResp = await api.post("/transactions/import", formData);

        totalImported += importResp.data.imported ?? 0;
        totalDuplicates += importResp.data.duplicates ?? 0;
      }

      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["analytics"] });

      const msg = totalImported > 0
        ? `Demo portfolio loaded — ${totalImported} transactions imported${totalDuplicates ? ` (${totalDuplicates} already present)` : ""}`
        : `Demo portfolio already loaded (${totalDuplicates} transactions already present)`;

      toast.success(msg, { id: toastId, duration: 5000 });
      setDemoMode(true);
    } catch (e: any) {
      toast.error(`Demo load failed: ${e?.message ?? "Unknown error"}`, { id: toastId });
    } finally {
      setIsDemoLoading(false);
    }
  };

  const activeCount = realAccounts.filter((a) => a.is_active).length;
  const totalTx = transactions.filter((t: any) => {
    const acc = realAccounts.find((a) => a.id === t.account_id);
    return !!acc;
  }).length;
  const isLoading = accountsLoading || txLoading;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ── Demo Mode Banner ── */}
      {demoMode && (
        <div className="flex items-center gap-3 px-4 py-3 bg-violet-500/10 border border-violet-500/30 rounded-xl">
          <FlaskConical className="w-4 h-4 text-violet-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium text-violet-300">Demo Mode</span>
            <span className="text-xs text-violet-400/70 ml-2">
              Showing sample portfolio — your real data is unchanged and unaffected
            </span>
          </div>
          <button
            onClick={() => setDemoMode(false)}
            className="text-xs text-violet-400 hover:text-violet-200 border border-violet-500/40 rounded-lg px-3 py-1.5 hover:bg-violet-500/20 transition-colors flex-shrink-0"
          >
            Back to My Portfolio
          </button>
        </div>
      )}

      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {demoMode ? "Demo Portfolio" : "Investments"}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {demoMode
              ? `${demoAccounts.length} demo account${demoAccounts.length !== 1 ? "s" : ""} · sample data only`
              : `${activeCount} of ${realAccounts.length} account${realAccounts.length !== 1 ? "s" : ""} active · ${totalTx} transaction${totalTx !== 1 ? "s" : ""}`
            }
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Demo mode toggle */}
          {hasDemoAccounts && !demoMode && (
            <button
              onClick={() => setDemoMode(true)}
              className="flex items-center gap-1.5 text-sm text-violet-400 border border-violet-500/30 hover:border-violet-400/60 hover:bg-violet-500/10 rounded-lg px-3 py-2 transition-colors"
            >
              <FlaskConical className="w-3.5 h-3.5" />
              Demo Mode
            </button>
          )}

          {/* Load demo portfolio (only if not loaded yet) */}
          {!hasDemoAccounts && !demoMode && (
            <button
              onClick={loadDemoPortfolio}
              disabled={isDemoLoading}
              className="flex items-center gap-1.5 text-sm text-violet-400 border border-violet-500/30 hover:border-violet-400/60 hover:bg-violet-500/10 rounded-lg px-3 py-2 transition-colors disabled:opacity-50"
            >
              {isDemoLoading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <FlaskConical className="w-3.5 h-3.5" />
              )}
              {isDemoLoading ? "Loading…" : "Load Demo"}
            </button>
          )}

          {/* Add Portfolio button (hidden in demo mode) */}
          {!demoMode && (
            <button
              onClick={() => { setShowImport(!showImport); setSelectedBroker(null); }}
              className="btn-primary flex items-center gap-2 text-sm"
            >
              <Plus className="w-4 h-4" />
              Add Portfolio
            </button>
          )}
        </div>
      </div>

      {/* ── Add Portfolio Panel ── */}
      {showImport && !demoMode && (
        <div className="card-glass p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-gray-100">
              {selectedBroker ? `Import from ${selectedBroker.label}` : "Choose your broker"}
            </h3>
            <button
              onClick={() => { setShowImport(false); setSelectedBroker(null); }}
              className="text-gray-500 hover:text-gray-300"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {!selectedBroker ? (
            <div>
              <p className="text-sm text-gray-400 mb-4">
                Select your broker or exchange to get specific export instructions.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {BROKERS.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => { setSelectedBroker(b); setImportTab(b.supportsApiSync ? "api" : "csv"); }}
                    className="flex flex-col items-center gap-2 p-4 rounded-xl border border-gray-700/50 bg-gray-800/30 hover:bg-gray-800/60 hover:border-gray-600 transition-all text-center group"
                  >
                    <div className="w-10 h-10 rounded-lg bg-gray-700/50 flex items-center justify-center text-lg font-bold text-gray-300 group-hover:text-blue-400 transition-colors">
                      {b.label.slice(0, 2).toUpperCase()}
                    </div>
                    <span className="text-sm font-medium text-gray-200">{b.label}</span>
                    <span className="text-xs text-gray-500">
                      {b.currency} · {b.country}
                      {b.supportsApiSync && " · API"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div>
              <button
                onClick={() => setSelectedBroker(null)}
                className="text-xs text-blue-400 hover:text-blue-300 mb-3 flex items-center gap-1"
              >
                <ChevronRight className="w-3 h-3 rotate-180" /> Back to all brokers
              </button>

              {selectedBroker.supportsApiSync && (
                <div className="flex gap-1 mb-4 bg-gray-800/40 rounded-lg p-1 border border-gray-700/50">
                  <button
                    onClick={() => setImportTab("api")}
                    className={clsx(
                      "flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                      importTab === "api"
                        ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                        : "text-gray-400 hover:text-gray-200 border border-transparent"
                    )}
                  >
                    <Key className="w-3.5 h-3.5" />
                    Connect API
                  </button>
                  <button
                    onClick={() => setImportTab("csv")}
                    className={clsx(
                      "flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                      importTab === "csv"
                        ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                        : "text-gray-400 hover:text-gray-200 border border-transparent"
                    )}
                  >
                    <Upload className="w-3.5 h-3.5" />
                    Upload CSV
                  </button>
                </div>
              )}

              {importTab === "csv" || !selectedBroker.supportsApiSync ? (
                <BrokerUploadPanel
                  broker={selectedBroker}
                  accounts={allAccounts}
                  onImportDone={() => {
                    setShowImport(false);
                    setSelectedBroker(null);
                    queryClient.invalidateQueries({ queryKey: ["transactions"] });
                    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
                    queryClient.invalidateQueries({ queryKey: ["analytics"] });
                  }}
                />
              ) : (
                <ApiSyncPanel
                  broker={selectedBroker}
                  accounts={allAccounts}
                  onImportDone={() => {
                    setShowImport(false);
                    setSelectedBroker(null);
                    queryClient.invalidateQueries({ queryKey: ["transactions"] });
                    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
                    queryClient.invalidateQueries({ queryKey: ["analytics"] });
                  }}
                />
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Info Banner (real mode only) ── */}
      {!demoMode && realAccounts.length > 0 && (
        <div className="flex items-start gap-2 text-xs text-gray-400 bg-gray-800/30 rounded-lg px-4 py-3 border border-gray-800">
          <Eye className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-blue-400" />
          <span>
            Use the checkboxes to include or exclude accounts from your Dashboard and Analytics calculations.
            Transactions are displayed in their original currency. Currency conversion is applied in the Dashboard and Analytics tabs.
          </span>
        </div>
      )}

      {/* ── Demo portfolio description (demo mode) ── */}
      {demoMode && (
        <div className="grid grid-cols-3 gap-3">
          {DEMO_PORTFOLIOS.map((d) => (
            <div key={d.name} className="bg-violet-500/5 border border-violet-500/20 rounded-xl px-4 py-3">
              <div className="text-sm font-medium text-violet-300 mb-0.5">{d.name.replace(DEMO_PREFIX, "")}</div>
              <div className="text-xs text-violet-400/60">{d.description}</div>
            </div>
          ))}
        </div>
      )}

      {/* ── Loading skeleton ── */}
      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card-glass p-4">
              <div className="h-12 bg-gray-800/50 rounded animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {/* ── Empty state ── */}
      {!isLoading && displayAccounts.length === 0 && !showImport && (
        <div className="card-glass text-center py-16 space-y-3">
          {demoMode ? (
            <>
              <FlaskConical className="w-10 h-10 text-violet-700 mx-auto" />
              <p className="text-gray-500 text-sm">No demo portfolio loaded yet</p>
              <button
                onClick={loadDemoPortfolio}
                disabled={isDemoLoading}
                className="mx-auto flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600/20 text-violet-400 hover:bg-violet-600/30 transition-colors text-sm disabled:opacity-50"
              >
                {isDemoLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FlaskConical className="w-4 h-4" />}
                {isDemoLoading ? "Loading…" : "Load Demo Portfolio"}
              </button>
            </>
          ) : (
            <>
              <Briefcase className="w-10 h-10 text-gray-700 mx-auto" />
              <p className="text-gray-500 text-sm">No investment accounts yet</p>
              <p className="text-gray-600 text-xs">
                Click <strong className="text-gray-400">Add Portfolio</strong> above to import your trade history.
              </p>
            </>
          )}
        </div>
      )}

      {/* ── Account Cards ── */}
      {!isLoading && displayAccounts.map((account: any) => (
        <AccountCard
          key={account.id}
          account={account}
          transactions={txByAccount[account.id] || []}
          onToggle={handleToggle}
          onRemove={handleRemove}
          isDemo={account.name.startsWith(DEMO_PREFIX)}
        />
      ))}
    </div>
  );
}

"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { formatCurrency, formatDate } from "@/lib/utils/formatters";
import {
  Plus, Upload, X, ChevronDown, ChevronRight, Trash2,
  FileText, AlertTriangle, Eye, EyeOff, Key, RefreshCw, Loader2, Check,
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
  apiProvider?: string;  // provider name for /sync/connect/exchange
  apiInstructions?: string[];
}

const BROKERS: BrokerInfo[] = [
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
  const queryClient = useQueryClient();

  // Find or auto-create account for this broker
  const existingAccount = accounts.find(
    (a: any) => a.institution_name === broker.label || a.name === broker.label
  );

  const getOrCreateAccountId = async (): Promise<string | null> => {
    if (existingAccount) return existingAccount.id;

    setIsCreating(true);
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
    } finally {
      setIsCreating(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: {
      "text/csv": [".csv"],
      "text/plain": [".csv", ".txt"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
    },
    disabled: isCreating,
    onDrop: async (files) => {
      const accountId = await getOrCreateAccountId();
      if (!accountId) return;

      const file = files[0];
      const formData = new FormData();
      formData.append("file", file);
      formData.append("account_id", accountId);

      const toastId = toast.loading(`Importing ${file.name}…`);
      try {
        const resp = await api.post("/transactions/import", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
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
  const [syncResult, setSyncResult] = useState<{ imported: number; error?: string } | null>(null);
  const queryClient = useQueryClient();

  const existingAccount = accounts.find(
    (a: any) => a.institution_name === broker.label || a.name === broker.label
  );

  // Check if already connected (has synced before)
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
      toast.error("Please enter both API Key and Private Key");
      return;
    }

    setIsConnecting(true);
    setSyncResult(null);
    try {
      const accountId = await getOrCreateAccountId();
      if (!accountId) return;

      // Store credentials
      await api.post("/sync/connect/exchange", {
        account_id: accountId,
        provider: broker.apiProvider,
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
      });

      toast.success("API credentials saved. Syncing trades...");

      // Trigger sync immediately
      setIsSyncing(true);
      const syncResp = await api.post(`/sync/accounts/${accountId}/trigger`);
      const result = syncResp.data;

      if (result.error) {
        setSyncResult({ imported: 0, error: result.error });
        toast.error(`Sync error: ${result.error}`);
      } else {
        setSyncResult({ imported: result.imported });
        toast.success(`Imported ${result.imported} transaction${result.imported !== 1 ? "s" : ""} from ${broker.label}`);
        queryClient.invalidateQueries({ queryKey: ["transactions"] });
        queryClient.invalidateQueries({ queryKey: ["portfolio"] });
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
      const syncResp = await api.post(`/sync/accounts/${existingAccount.id}/trigger`);
      const result = syncResp.data;
      if (result.error) {
        setSyncResult({ imported: 0, error: result.error });
        toast.error(`Sync error: ${result.error}`);
      } else {
        setSyncResult({ imported: result.imported });
        toast.success(`Imported ${result.imported} new transaction${result.imported !== 1 ? "s" : ""}`);
        queryClient.invalidateQueries({ queryKey: ["transactions"] });
        queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      }
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? "Sync failed");
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Instructions */}
      <div className="bg-gray-800/40 rounded-lg border border-gray-700/50 px-4 py-3">
        <div className="flex items-center gap-2 mb-2">
          <Key className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-medium text-gray-200">
            How to get your {broker.label} API Key
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
          <span>Only grant read-only permissions. Never enable trading or withdrawal access for third-party apps.</span>
        </div>
      </div>

      {/* Existing account info */}
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
              {isSyncing ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
              {isSyncing ? "Syncing..." : "Re-sync"}
            </button>
          )}
        </div>
      )}

      {/* API Key inputs */}
      {!isConnected && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">API Key</label>
            <input
              type="text"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter your API Key"
              className="w-full px-3 py-2.5 bg-gray-800/60 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Private Key (Secret)</label>
            <div className="relative">
              <input
                type={showSecret ? "text" : "password"}
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                placeholder="Enter your Private Key"
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
                {isSyncing ? "Syncing trades..." : "Connecting..."}
              </>
            ) : (
              <>
                <Key className="w-4 h-4" />
                Connect & Sync
              </>
            )}
          </button>
        </div>
      )}

      {/* Sync result */}
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
}: {
  account: any;
  transactions: any[];
  onToggle: (id: string, active: boolean) => void;
  onRemove: (id: string, name: string) => void;
}) {
  const [expanded, setExpanded] = useState(account.is_active);
  const isActive = account.is_active;
  const txCount = transactions.length;
  const isInflow = (t: string) =>
    ["BUY", "TRANSFER_IN", "DEPOSIT", "STAKE_REWARD", "DIVIDEND", "DISTRIBUTION", "INTEREST"].includes(t);

  const totalInvested = transactions
    .filter((t) => t.transaction_type === "BUY")
    .reduce((sum: number, t: any) => sum + Math.abs(t.net_amount ?? 0), 0);

  return (
    <div className={clsx(
      "card-glass overflow-hidden transition-all",
      !isActive && "opacity-60"
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
          <div className="w-9 h-9 rounded-lg bg-gray-800 border border-gray-700 flex items-center justify-center text-xs font-bold text-gray-300 flex-shrink-0">
            {(account.institution_name || account.name).slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="font-medium text-gray-100 text-sm truncate">
              {account.name}
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
          <button
            onClick={() => onRemove(account.id, account.name)}
            className="text-gray-600 hover:text-red-400 transition-colors p-1 rounded hover:bg-red-400/10"
            title="Permanently delete account and all transactions"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

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
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {expanded && txCount === 0 && (
        <div className="p-6 text-center text-gray-500 text-sm">
          No transactions yet. Import a CSV file to populate this account.
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
  const queryClient = useQueryClient();

  // Fetch ALL accounts (including inactive) for this page
  const { data: allAccounts = [], isLoading: accountsLoading } = useQuery<any[]>({
    queryKey: ["portfolio", "accounts", "all"],
    queryFn: () => api.get("/portfolio/accounts/all").then((r) => r.data),
  });

  const { data: transactions = [], isLoading: txLoading } = useQuery({
    queryKey: ["transactions"],
    queryFn: () => api.get("/transactions/?limit=1000").then((r) => r.data),
  });

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
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: () => toast.error("Failed to update account"),
  });

  // Remove account (hard delete — permanently removes account + transactions)
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

  const activeCount = allAccounts.filter((a) => a.is_active).length;
  const totalTx = transactions.length;
  const isLoading = accountsLoading || txLoading;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Investments</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {activeCount} of {allAccounts.length} account{allAccounts.length !== 1 ? "s" : ""} active · {totalTx} transaction{totalTx !== 1 ? "s" : ""}
          </p>
        </div>
        <button
          onClick={() => { setShowImport(!showImport); setSelectedBroker(null); }}
          className="btn-primary flex items-center gap-2 text-sm"
        >
          <Plus className="w-4 h-4" />
          Add Investment
        </button>
      </div>

      {/* ── Add Investment Panel ── */}
      {showImport && (
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

              {/* Tabs for brokers with API sync */}
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
                  }}
                />
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Info Banner ── */}
      {allAccounts.length > 0 && (
        <div className="flex items-start gap-2 text-xs text-gray-400 bg-gray-800/30 rounded-lg px-4 py-3 border border-gray-800">
          <Eye className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-blue-400" />
          <span>
            Use the checkboxes to include or exclude accounts from your Dashboard and Analytics calculations.
            Transactions are displayed in their original currency. Currency conversion is applied in the Dashboard and Analytics tabs.
          </span>
        </div>
      )}

      {/* ── Account Cards ── */}
      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card-glass p-4">
              <div className="h-12 bg-gray-800/50 rounded animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {!isLoading && allAccounts.length === 0 && !showImport && (
        <div className="card-glass text-center py-16 space-y-3">
          <Upload className="w-10 h-10 text-gray-700 mx-auto" />
          <p className="text-gray-500 text-sm">No investment accounts yet</p>
          <p className="text-gray-600 text-xs">
            Click <strong className="text-gray-400">Add Investment</strong> above to import your trade history.
          </p>
        </div>
      )}

      {!isLoading && allAccounts.map((account: any) => (
        <AccountCard
          key={account.id}
          account={account}
          transactions={txByAccount[account.id] || []}
          onToggle={handleToggle}
          onRemove={handleRemove}
        />
      ))}
    </div>
  );
}

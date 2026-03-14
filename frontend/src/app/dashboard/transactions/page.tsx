"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { formatCurrency, formatDate } from "@/lib/utils/formatters";
import {
  Plus, Upload, X, ChevronDown, ChevronRight, Trash2,
  ExternalLink, FileText, Loader2, CheckCircle, AlertTriangle,
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
      "Login to your Moomoo app or desktop client",
      "Go to Trade > History or Order History",
      "Select the date range for your trades",
      "Export or download as CSV",
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
  },
  {
    id: "coinbase",
    label: "Coinbase",
    country: "INTL",
    currency: "USD",
    instructions: [
      "Login to your Coinbase account",
      "Go to Taxes / Reports in Settings",
      "Click 'Generate report' for Transaction history",
      "Select your date range and download CSV",
      "Upload your file below",
    ],
    fileTypes: "CSV",
  },
  {
    id: "schwab",
    label: "Charles Schwab",
    country: "US",
    currency: "USD",
    instructions: [
      "Login to your Schwab account",
      "Go to Accounts > History",
      "Set your date range and filter by Trades",
      "Click Export to download as CSV",
      "Upload your file below",
    ],
    fileTypes: "CSV",
  },
];

// ─── Account Types ────────────────────────────────────────────────────────

const ACCOUNT_TYPES = [
  { value: "BROKERAGE", label: "Brokerage" },
  { value: "CRYPTO_EXCHANGE", label: "Crypto Exchange" },
  { value: "WALLET", label: "Crypto Wallet" },
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

// ─── Create Account Form ──────────────────────────────────────────────────

function CreateAccountForm({ broker, onCreated }: { broker?: BrokerInfo; onCreated: () => void }) {
  const [name, setName] = useState(broker ? `${broker.label}` : "");
  const [type, setType] = useState(
    broker?.currency === "USD" && broker?.id !== "kraken" ? "BROKERAGE" :
    broker?.id === "kraken" || broker?.id === "coinbase" ? "CRYPTO_EXCHANGE" : "BROKERAGE"
  );
  const [currency, setCurrency] = useState(broker?.currency || "AUD");
  const queryClient = useQueryClient();

  const { mutate, isPending } = useMutation({
    mutationFn: () =>
      api.post("/portfolio/accounts", {
        name,
        institution_name: broker?.label || undefined,
        account_type: type,
        currency,
      }).then((r) => r.data),
    onSuccess: (data) => {
      toast.success("Account created");
      queryClient.invalidateQueries({ queryKey: ["portfolio", "accounts"] });
      onCreated();
    },
    onError: () => toast.error("Failed to create account"),
  });

  return (
    <div className="bg-gray-800/40 rounded-lg p-4 border border-gray-700/50 space-y-3">
      <p className="text-sm font-medium text-gray-300">Quick-create account</p>
      <div className="grid grid-cols-3 gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Account name"
          className="bg-gray-900 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="bg-gray-900 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          {ACCOUNT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className="bg-gray-900 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="AUD">AUD</option>
          <option value="USD">USD</option>
          <option value="GBP">GBP</option>
          <option value="EUR">EUR</option>
        </select>
      </div>
      <button
        onClick={() => mutate()}
        disabled={!name || isPending}
        className="btn-primary text-sm px-4 py-1.5 disabled:opacity-40"
      >
        {isPending ? "Creating…" : "Create Account"}
      </button>
    </div>
  );
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
  const [accountId, setAccountId] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showInstructions, setShowInstructions] = useState(true);
  const queryClient = useQueryClient();

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: {
      "text/csv": [".csv"],
      "text/plain": [".csv", ".txt"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
    },
    disabled: !accountId,
    onDrop: async (files) => {
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

      {/* Account selector */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs text-gray-400">Import into account</label>
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            + New account
          </button>
        </div>
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:outline-none focus:border-blue-500"
        >
          <option value="">— Select account —</option>
          {accounts.map((a: any) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.currency})
            </option>
          ))}
        </select>
      </div>

      {showCreate && (
        <CreateAccountForm
          broker={broker}
          onCreated={() => setShowCreate(false)}
        />
      )}

      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={clsx(
          "border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all",
          !accountId && "opacity-40 pointer-events-none",
          isDragActive ? "border-blue-500 bg-blue-500/10" : "border-gray-700 hover:border-gray-600"
        )}
      >
        <input {...getInputProps()} />
        <Upload className="w-6 h-6 text-gray-500 mx-auto mb-2" />
        <p className="text-gray-300 text-sm">
          {isDragActive ? "Drop your file here" : `Drop your ${broker.label} ${broker.fileTypes} file here`}
        </p>
        <p className="text-gray-600 text-xs mt-1">
          or click to browse · Trades in {broker.currency} will be auto-detected
        </p>
        {!accountId && (
          <p className="text-amber-500 text-xs mt-2">Select or create an account first</p>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────

export default function TransactionsPage() {
  const [showImport, setShowImport] = useState(false);
  const [selectedBroker, setSelectedBroker] = useState<BrokerInfo | null>(null);
  const [displayCurrency, setDisplayCurrency] = useState<"original" | "AUD">("AUD");
  const queryClient = useQueryClient();

  const { data: transactions = [], isLoading, refetch } = useQuery({
    queryKey: ["transactions"],
    queryFn: () => api.get("/transactions/?limit=500").then((r) => r.data),
  });

  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ["portfolio", "accounts"],
    queryFn: () => api.get("/portfolio/accounts").then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/transactions/${id}`),
    onSuccess: () => {
      toast.success("Transaction deleted");
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: () => toast.error("Failed to delete"),
  });

  const handleDelete = (id: string, symbol: string) => {
    if (confirm(`Delete ${symbol} transaction? This cannot be undone.`)) {
      deleteMutation.mutate(id);
    }
  };

  // Group transactions by source/account for display
  const txCount = transactions.length;
  const isInflow = (t: string) => ["BUY", "TRANSFER_IN", "DEPOSIT", "STAKE_REWARD", "DIVIDEND", "DISTRIBUTION", "INTEREST"].includes(t);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Investments</h1>
          <p className="text-sm text-gray-500 mt-0.5">{txCount} transaction{txCount !== 1 ? "s" : ""} across {accounts.length} account{accounts.length !== 1 ? "s" : ""}</p>
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
            /* ── Broker Grid ── */
            <div>
              <p className="text-sm text-gray-400 mb-4">
                Select your broker or exchange to get specific export instructions.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {BROKERS.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => setSelectedBroker(b)}
                    className="flex flex-col items-center gap-2 p-4 rounded-xl border border-gray-700/50 bg-gray-800/30 hover:bg-gray-800/60 hover:border-gray-600 transition-all text-center group"
                  >
                    <div className="w-10 h-10 rounded-lg bg-gray-700/50 flex items-center justify-center text-lg font-bold text-gray-300 group-hover:text-blue-400 transition-colors">
                      {b.label.slice(0, 2).toUpperCase()}
                    </div>
                    <span className="text-sm font-medium text-gray-200">{b.label}</span>
                    <span className="text-xs text-gray-500">{b.currency} · {b.country}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* ── Selected Broker Upload ── */
            <div>
              <button
                onClick={() => setSelectedBroker(null)}
                className="text-xs text-blue-400 hover:text-blue-300 mb-3 flex items-center gap-1"
              >
                <ChevronRight className="w-3 h-3 rotate-180" /> Back to all brokers
              </button>
              <BrokerUploadPanel
                broker={selectedBroker}
                accounts={accounts}
                onImportDone={() => {
                  setShowImport(false);
                  setSelectedBroker(null);
                  refetch();
                }}
              />
            </div>
          )}
        </div>
      )}

      {/* ── Transactions Table ── */}
      <div className="card-glass">
        <div className="p-4 border-b border-gray-800 flex items-center justify-between">
          <span className="text-sm text-gray-400">{txCount} transactions</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Display:</span>
            <select
              value={displayCurrency}
              onChange={(e) => setDisplayCurrency(e.target.value as "original" | "AUD")}
              className="bg-gray-800 border border-gray-700 text-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-500"
            >
              <option value="AUD">AUD (converted)</option>
              <option value="original">Original currency</option>
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
                <th className="text-left p-3 pl-4">Date</th>
                <th className="text-left p-3">Type</th>
                <th className="text-left p-3">Asset</th>
                <th className="text-right p-3">Qty</th>
                <th className="text-right p-3">Price</th>
                <th className="text-right p-3">Fees</th>
                <th className="text-right p-3">Amount</th>
                <th className="text-center p-3">CCY</th>
                <th className="text-left p-3">Source</th>
                <th className="text-center p-3 pr-4 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {isLoading &&
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 10 }).map((_, j) => (
                      <td key={j} className="p-3">
                        <div className="h-4 bg-gray-800 rounded animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))}
              {!isLoading &&
                transactions.map((txn: any) => {
                  const typeStyle = TYPE_STYLES[txn.transaction_type] || "text-gray-400 bg-gray-400/10";
                  const inflow = isInflow(txn.transaction_type);
                  const wantAud = displayCurrency === "AUD";
                  const hasAudData = txn.net_amount_aud != null || txn.price_per_unit_aud != null;
                  const showAud = wantAud && txn.currency !== "AUD" && hasAudData;

                  const price = showAud ? txn.price_per_unit_aud : txn.price_per_unit;
                  const fees = showAud && txn.fx_rate_to_aud ? txn.fees * txn.fx_rate_to_aud : txn.fees;
                  const amount = showAud ? txn.net_amount_aud : txn.net_amount;
                  const ccy = showAud ? "AUD" : (txn.currency || "USD");

                  return (
                    <tr key={txn.id} className="hover:bg-gray-800/30 transition-colors group">
                      <td className="p-3 pl-4 text-gray-400 whitespace-nowrap text-xs">
                        {formatDate(txn.transacted_at)}
                      </td>
                      <td className="p-3">
                        <span className={clsx("text-xs font-medium px-2 py-0.5 rounded-full", typeStyle)}>
                          {TYPE_LABELS[txn.transaction_type] || txn.transaction_type}
                        </span>
                      </td>
                      <td className="p-3 font-medium text-gray-100 text-xs">
                        {txn.symbol || "—"}
                      </td>
                      <td className="p-3 text-right font-mono text-xs">
                        {txn.quantity != null ? (
                          <span className={inflow ? "text-green-400" : "text-red-400"}>
                            {inflow ? "+" : "-"}{Math.abs(txn.quantity).toLocaleString(undefined, { maximumFractionDigits: 6 })}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="p-3 text-right font-mono text-gray-400 text-xs">
                        {price ? formatInCurrency(price, ccy) : "—"}
                      </td>
                      <td className="p-3 text-right font-mono text-gray-500 text-xs">
                        {fees && fees > 0 ? formatInCurrency(fees, ccy) : "—"}
                      </td>
                      <td className="p-3 text-right font-mono text-xs font-medium">
                        {amount != null ? (
                          <span className={amount >= 0 ? "text-green-400" : "text-red-400"}>
                            {formatInCurrency(amount, ccy)}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="p-3 text-center">
                        <span className={clsx(
                          "text-xs px-1.5 py-0.5 rounded font-medium",
                          ccy === "AUD" ? "text-blue-400 bg-blue-400/10" :
                          ccy === "USD" ? "text-green-400 bg-green-400/10" :
                          "text-gray-400 bg-gray-400/10"
                        )}>
                          {ccy}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className="text-xs text-gray-600 truncate max-w-[80px] block">
                          {txn.source?.replace("_IMPORT", "").replace("_", " ") || "Manual"}
                        </span>
                      </td>
                      <td className="p-3 pr-4 text-center">
                        <button
                          onClick={() => handleDelete(txn.id, txn.symbol || txn.transaction_type)}
                          className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all p-1 rounded hover:bg-red-400/10"
                          title="Delete transaction"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
          {!isLoading && txCount === 0 && (
            <div className="text-center py-16 space-y-3">
              <Upload className="w-10 h-10 text-gray-700 mx-auto" />
              <p className="text-gray-500 text-sm">No investments yet</p>
              <button
                onClick={() => setShowImport(true)}
                className="btn-primary text-sm px-5 py-2"
              >
                <Plus className="w-4 h-4 inline mr-1.5 -mt-0.5" />
                Add Investment
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

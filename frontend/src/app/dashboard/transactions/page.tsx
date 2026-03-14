"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { formatCurrency, formatDate } from "@/lib/utils/formatters";
import { Plus, Upload, X, ChevronDown } from "lucide-react";
import clsx from "clsx";
import { useDropzone } from "react-dropzone";
import toast from "react-hot-toast";

const TYPE_STYLES: Record<string, string> = {
  BUY: "text-green-400 bg-green-400/10",
  SELL: "text-red-400 bg-red-400/10",
  DIVIDEND: "text-blue-400 bg-blue-400/10",
  STAKE_REWARD: "text-purple-400 bg-purple-400/10",
  TRANSFER_IN: "text-teal-400 bg-teal-400/10",
  TRANSFER_OUT: "text-orange-400 bg-orange-400/10",
  FEE: "text-gray-400 bg-gray-400/10",
  DEPOSIT: "text-green-400 bg-green-400/10",
  WITHDRAWAL: "text-red-400 bg-red-400/10",
};

const BROKERS = [
  { id: "", label: "— Auto-detect broker —" },
  // Australian
  { id: "commsec", label: "CommSec" },
  { id: "cmc", label: "CMC Invest" },
  { id: "moomoo", label: "Moomoo" },
  { id: "stake", label: "Stake" },
  // International
  { id: "ibkr", label: "Interactive Brokers (IBKR)" },
  { id: "robinhood", label: "Robinhood" },
  { id: "schwab", label: "Charles Schwab" },
  { id: "fidelity", label: "Fidelity" },
  // Crypto
  { id: "kraken", label: "Kraken" },
  { id: "coinbase", label: "Coinbase" },
  { id: "binance", label: "Binance" },
];

const ACCOUNT_TYPES = [
  { value: "BROKERAGE", label: "Brokerage" },
  { value: "CRYPTO_EXCHANGE", label: "Crypto Exchange" },
  { value: "WALLET", label: "Crypto Wallet" },
  { value: "IRA", label: "IRA" },
  { value: "ROTH_IRA", label: "Roth IRA" },
];

function CreateAccountForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState("");
  const [type, setType] = useState("BROKERAGE");
  const [currency, setCurrency] = useState("AUD");
  const queryClient = useQueryClient();

  const { mutate, isPending } = useMutation({
    mutationFn: () =>
      api.post("/portfolio/accounts", {
        name,
        institution_name: institution || undefined,
        account_type: type,
        currency,
      }).then((r) => r.data),
    onSuccess: () => {
      toast.success("Account created");
      queryClient.invalidateQueries({ queryKey: ["portfolio", "accounts"] });
      onCreated();
    },
    onError: () => toast.error("Failed to create account"),
  });

  return (
    <div className="bg-gray-800/60 rounded-xl p-4 border border-gray-700 space-y-3">
      <p className="text-sm font-medium text-gray-200">Create an account to import into</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Account Name *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. CommSec — ASX"
            className="bg-gray-900 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Institution</label>
          <input
            value={institution}
            onChange={(e) => setInstitution(e.target.value)}
            placeholder="e.g. CommSec"
            className="bg-gray-900 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:outline-none focus:border-blue-500"
          >
            {ACCOUNT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Base Currency</label>
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:outline-none focus:border-blue-500"
          >
            <option value="AUD">AUD — Australian Dollar</option>
            <option value="USD">USD — US Dollar</option>
            <option value="GBP">GBP — British Pound</option>
            <option value="EUR">EUR — Euro</option>
          </select>
        </div>
      </div>
      <button
        onClick={() => mutate()}
        disabled={!name || isPending}
        className="btn-primary text-sm px-4 py-2 disabled:opacity-40"
      >
        {isPending ? "Creating…" : "Create Account"}
      </button>
    </div>
  );
}

export default function TransactionsPage() {
  const [showImport, setShowImport] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [broker, setBroker] = useState("");
  const [showCreateAccount, setShowCreateAccount] = useState(false);
  const queryClient = useQueryClient();

  const { data: transactions, isLoading, refetch } = useQuery({
    queryKey: ["transactions"],
    queryFn: () => api.get("/transactions/?limit=200").then((r) => r.data),
  });

  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ["portfolio", "accounts"],
    queryFn: () => api.get("/portfolio/accounts").then((r) => r.data),
  });

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: {
      "text/csv": [".csv"],
      "text/plain": [".csv", ".txt"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/json": [".json"],
    },
    onDrop: async (files) => {
      if (!accountId) {
        toast.error("Please select an account first");
        return;
      }
      const file = files[0];
      const formData = new FormData();
      formData.append("file", file);
      formData.append("account_id", accountId);
      if (broker) formData.append("source", broker.toUpperCase() + "_IMPORT");

      const toastId = toast.loading(`Importing ${file.name}…`);
      try {
        const resp = await api.post("/transactions/import", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        const result = resp.data;
        const brokerLabel = result.broker_detected && result.broker_detected !== "Unknown"
          ? ` (${result.broker_detected})`
          : "";
        toast.success(
          `Imported ${result.imported} transaction${result.imported !== 1 ? "s" : ""}${brokerLabel}` +
          (result.duplicates ? ` · ${result.duplicates} duplicates skipped` : "") +
          (result.errors ? ` · ${result.errors} errors` : ""),
          { id: toastId, duration: 5000 }
        );
        if (result.error_details?.length) {
          console.warn("Import errors:", result.error_details);
        }
        refetch();
        setShowImport(false);
      } catch (e: any) {
        const detail = e?.response?.data?.detail ?? "Check file format and try again.";
        toast.error(`Import failed: ${detail}`, { id: toastId });
      }
    },
  });

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Transactions</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setShowImport(!showImport); setShowCreateAccount(false); }}
            className="btn-secondary flex items-center gap-2 text-sm"
          >
            <Upload className="w-4 h-4" />
            Import
          </button>
          <button className="btn-primary flex items-center gap-2 text-sm">
            <Plus className="w-4 h-4" />
            Add
          </button>
        </div>
      </div>

      {/* Import Panel */}
      {showImport && (
        <div className="card-glass p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-gray-100">Import Transactions</h3>
            <button onClick={() => setShowImport(false)} className="text-gray-500 hover:text-gray-300">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Create account inline if none exist */}
          {accounts.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-amber-400 bg-amber-400/10 rounded-lg px-4 py-2">
                You need at least one account before importing. Create one below.
              </p>
              <CreateAccountForm onCreated={() => setShowCreateAccount(false)} />
            </div>
          ) : (
            <>
              {/* Account + broker selectors */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-gray-400">Account *</label>
                    <button
                      onClick={() => setShowCreateAccount((v) => !v)}
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
                        {a.name}{a.institution_name ? ` (${a.institution_name})` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Broker / Exchange (optional)</label>
                  <select
                    value={broker}
                    onChange={(e) => setBroker(e.target.value)}
                    className="bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:outline-none focus:border-blue-500"
                  >
                    {BROKERS.map((b) => (
                      <option key={b.id} value={b.id}>{b.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Inline create account form */}
              {showCreateAccount && (
                <CreateAccountForm onCreated={() => setShowCreateAccount(false)} />
              )}

              {/* Drop zone */}
              <div
                {...getRootProps()}
                className={clsx(
                  "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
                  !accountId && "opacity-50 pointer-events-none",
                  isDragActive ? "border-blue-500 bg-blue-500/10" : "border-gray-700 hover:border-gray-600"
                )}
              >
                <input {...getInputProps()} />
                <Upload className="w-8 h-8 text-gray-500 mx-auto mb-2" />
                <p className="text-gray-300 text-sm">
                  {isDragActive ? "Drop your file here" : "Drag & drop or click to select"}
                </p>
                <p className="text-gray-500 text-xs mt-1">CSV · Excel (.xlsx) · JSON</p>
                <p className="text-gray-600 text-xs mt-2">
                  Supports CommSec · CMC Invest · Moomoo · Stake · IBKR · Robinhood · Schwab · Fidelity · Kraken · Coinbase · Binance
                </p>
                {!accountId && (
                  <p className="text-amber-500 text-xs mt-2">Select an account above first</p>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* Transactions Table */}
      <div className="card-glass">
        <div className="p-4 border-b border-gray-800">
          <span className="text-sm text-gray-400">{(transactions ?? []).length} transactions</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
                <th className="text-left p-4">Date</th>
                <th className="text-left p-4">Type</th>
                <th className="text-left p-4">Asset</th>
                <th className="text-right p-4">Quantity</th>
                <th className="text-right p-4">Price</th>
                <th className="text-right p-4">Fees</th>
                <th className="text-right p-4">Net Amount</th>
                <th className="text-left p-4">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {isLoading &&
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="p-4">
                        <div className="h-4 bg-gray-800 rounded animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))}
              {!isLoading &&
                (transactions ?? []).map((txn: any) => {
                  const typeStyle = TYPE_STYLES[txn.transaction_type] || "text-gray-400 bg-gray-400/10";
                  const isBuy = ["BUY", "TRANSFER_IN", "DEPOSIT", "STAKE_REWARD", "DIVIDEND"].includes(txn.transaction_type);

                  return (
                    <tr key={txn.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="p-4 text-gray-400 whitespace-nowrap">
                        {formatDate(txn.transacted_at)}
                      </td>
                      <td className="p-4">
                        <span className={clsx("text-xs font-medium px-2 py-1 rounded-full", typeStyle)}>
                          {txn.transaction_type}
                        </span>
                      </td>
                      <td className="p-4 font-medium text-gray-100">
                        {txn.symbol || "—"}
                      </td>
                      <td className="p-4 text-right font-mono text-gray-300">
                        <span className={isBuy ? "text-green-400" : "text-red-400"}>
                          {isBuy ? "+" : "-"}{Math.abs(txn.quantity ?? 0).toFixed(6)}
                        </span>
                      </td>
                      <td className="p-4 text-right font-mono text-gray-400">
                        {txn.price_per_unit ? formatCurrency(txn.price_per_unit) : "—"}
                      </td>
                      <td className="p-4 text-right font-mono text-gray-500">
                        {txn.fees ? formatCurrency(txn.fees) : "—"}
                      </td>
                      <td className="p-4 text-right font-mono font-medium">
                        <span className={txn.net_amount >= 0 ? "text-green-400" : "text-red-400"}>
                          {txn.net_amount ? formatCurrency(Math.abs(txn.net_amount)) : "—"}
                        </span>
                      </td>
                      <td className="p-4">
                        <span className="text-xs text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
                          {txn.source}
                        </span>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
          {!isLoading && !(transactions ?? []).length && (
            <div className="text-center py-12 text-gray-500 text-sm">
              No transactions yet.{" "}
              <button
                onClick={() => setShowImport(true)}
                className="text-blue-400 hover:text-blue-300 underline"
              >
                Import a file
              </button>{" "}
              to get started.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

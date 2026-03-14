"use client";

import { useState, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { formatAUD, formatDate } from "@/lib/utils/formatters";
import {
  Upload,
  CheckCircle,
  XCircle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Loader2,
} from "lucide-react";
import clsx from "clsx";

const INSTITUTIONS = [
  { id: "", label: "Auto-detect", flag: "🔍" },
  { id: "cba", label: "Commonwealth Bank", flag: "🇦🇺" },
  { id: "anz", label: "ANZ", flag: "🇦🇺" },
  { id: "westpac", label: "Westpac", flag: "🇦🇺" },
  { id: "nab", label: "NAB", flag: "🇦🇺" },
  { id: "bendigo", label: "Bendigo Bank", flag: "🇦🇺" },
  { id: "paypal", label: "PayPal", flag: "🌐" },
  { id: "wise", label: "Wise (TransferWise)", flag: "🌐" },
  { id: "airtm", label: "AirTM", flag: "🌐" },
];

interface PreviewRow {
  date: string;
  description: string;
  amount: number;
  currency: string;
  amount_aud: number | null;
  fx_rate_to_aud: number | null;
  balance: number | null;
  reference: string | null;
  raw_type: string | null;
  import_hash: string;
}

interface ImportPreview {
  institution: string;
  total_rows: number;
  imported: number;
  duplicates: number;
  errors: number;
  transactions: PreviewRow[];
  error_details: string[];
}

export default function ImportPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [institution, setInstitution] = useState("");
  const [accountId, setAccountId] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showErrors, setShowErrors] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  // Upload & preview
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      if (institution) form.append("institution", institution);
      if (accountId) form.append("account_id", accountId);
      const { data } = await api.post("/api/bank-import/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data as ImportPreview;
    },
    onSuccess: (data) => {
      setPreview(data);
      setSelected(new Set(data.transactions.map((t) => t.import_hash)));
      setConfirmed(false);
    },
  });

  // Confirm save
  const confirmMutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post("/api/bank-import/confirm", {
        account_id: accountId,
        institution: preview?.institution ?? institution,
        import_hashes: [...selected],
        transactions: preview?.transactions ?? [],
      });
      return data;
    },
    onSuccess: () => setConfirmed(true),
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadMutation.mutate(file);
  };

  const toggleRow = (hash: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(hash)) next.delete(hash);
      else next.add(hash);
      return next;
    });
  };

  const toggleAll = () => {
    if (preview === null) return;
    if (selected.size === preview.transactions.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(preview.transactions.map((t) => t.import_hash)));
    }
  };

  return (
    <div className="space-y-6 animate-fade-in max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Import Transactions</h1>
        <p className="text-gray-400 text-sm mt-1">
          Upload bank statements, PayPal, Wise or AirTM exports. Amounts are
          automatically converted to AUD using RBA exchange rates.
        </p>
      </div>

      {/* Upload config */}
      <div className="card-glass p-6 space-y-4">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          1. Configure
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Institution (optional — auto-detected from file)
            </label>
            <select
              value={institution}
              onChange={(e) => setInstitution(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm"
            >
              {INSTITUTIONS.map((inst) => (
                <option key={inst.id} value={inst.id}>
                  {inst.flag} {inst.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Destination account ID (optional)
            </label>
            <input
              type="text"
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              placeholder="e.g. UUID of your CBA account"
              className="w-full bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm placeholder-gray-600"
            />
          </div>
        </div>

        {/* Drop zone */}
        <div
          onClick={() => fileRef.current?.click()}
          className={clsx(
            "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
            uploadMutation.isPending
              ? "border-blue-500/40 bg-blue-500/5"
              : "border-gray-700 hover:border-gray-500 hover:bg-gray-800/50",
          )}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={handleFileChange}
          />
          {uploadMutation.isPending ? (
            <div className="flex flex-col items-center gap-2 text-blue-400">
              <Loader2 className="w-8 h-8 animate-spin" />
              <p className="text-sm">Parsing & fetching FX rates…</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2 text-gray-400">
              <Upload className="w-8 h-8" />
              <p className="text-sm">
                Drop a CSV or Excel file here, or{" "}
                <span className="text-blue-400 underline">browse</span>
              </p>
              <p className="text-xs text-gray-600">
                Supported: CBA · ANZ · Westpac · NAB · Bendigo · PayPal · Wise · AirTM
              </p>
            </div>
          )}
        </div>

        {uploadMutation.isError && (
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <XCircle className="w-4 h-4" />
            Failed to parse file. Check the format and try again.
          </div>
        )}
      </div>

      {/* Preview */}
      {preview && !confirmed && (
        <>
          {/* Stats bar */}
          <div className="card-glass p-4 flex flex-wrap gap-6 items-center">
            <div className="text-sm text-gray-400">
              Detected:{" "}
              <span className="text-gray-200 font-medium capitalize">
                {preview.institution}
              </span>
            </div>
            <div className="flex gap-4 text-sm">
              <span>
                <span className="text-green-400 font-medium">{preview.imported}</span>
                {" "}new
              </span>
              <span>
                <span className="text-gray-500 font-medium">{preview.duplicates}</span>
                {" "}duplicate
              </span>
              {preview.errors > 0 && (
                <span>
                  <span className="text-red-400 font-medium">{preview.errors}</span>
                  {" "}error
                </span>
              )}
            </div>

            {preview.error_details.length > 0 && (
              <button
                onClick={() => setShowErrors((s) => !s)}
                className="text-xs text-yellow-400 flex items-center gap-1"
              >
                <AlertCircle className="w-3.5 h-3.5" />
                {showErrors ? "Hide" : "Show"} errors
                {showErrors ? (
                  <ChevronUp className="w-3 h-3" />
                ) : (
                  <ChevronDown className="w-3 h-3" />
                )}
              </button>
            )}
          </div>

          {showErrors && (
            <div className="card-glass p-4 border border-yellow-500/20 bg-yellow-500/5 space-y-1">
              {preview.error_details.map((e, i) => (
                <p key={i} className="text-xs text-yellow-300 font-mono">
                  {e}
                </p>
              ))}
            </div>
          )}

          {/* Transaction table */}
          <div className="card-glass overflow-hidden">
            <div className="p-4 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                2. Review & select
              </h2>
              <button
                onClick={toggleAll}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                {selected.size === preview.transactions.length
                  ? "Deselect all"
                  : "Select all"}
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-900/50">
                  <tr>
                    <th className="px-4 py-2 text-left w-8"></th>
                    <th className="px-4 py-2 text-left text-xs text-gray-500 font-medium">Date</th>
                    <th className="px-4 py-2 text-left text-xs text-gray-500 font-medium">Description</th>
                    <th className="px-4 py-2 text-right text-xs text-gray-500 font-medium">Amount</th>
                    <th className="px-4 py-2 text-right text-xs text-gray-500 font-medium">Amount (AUD)</th>
                    <th className="px-4 py-2 text-right text-xs text-gray-500 font-medium">FX Rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/50">
                  {preview.transactions.map((tx) => (
                    <tr
                      key={tx.import_hash}
                      onClick={() => toggleRow(tx.import_hash)}
                      className={clsx(
                        "cursor-pointer transition-colors",
                        selected.has(tx.import_hash)
                          ? "bg-blue-500/5 hover:bg-blue-500/10"
                          : "opacity-50 hover:opacity-70",
                      )}
                    >
                      <td className="px-4 py-2">
                        <input
                          type="checkbox"
                          checked={selected.has(tx.import_hash)}
                          onChange={() => toggleRow(tx.import_hash)}
                          onClick={(e) => e.stopPropagation()}
                          className="accent-blue-500"
                        />
                      </td>
                      <td className="px-4 py-2 text-gray-400 whitespace-nowrap text-xs">
                        {formatDate(tx.date)}
                      </td>
                      <td className="px-4 py-2 text-gray-200 max-w-xs truncate">
                        {tx.description}
                      </td>
                      <td className="px-4 py-2 text-right font-mono whitespace-nowrap">
                        <span className={tx.amount >= 0 ? "text-green-400" : "text-red-400"}>
                          {tx.currency !== "AUD" && (
                            <span className="text-xs text-gray-500 mr-1">{tx.currency}</span>
                          )}
                          {tx.amount >= 0 ? "+" : ""}
                          {tx.amount.toFixed(2)}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right font-mono whitespace-nowrap">
                        {tx.amount_aud !== null ? (
                          <span className={tx.amount_aud >= 0 ? "text-green-400" : "text-red-400"}>
                            {formatAUD(tx.amount_aud)}
                          </span>
                        ) : (
                          <span className="text-gray-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right text-xs text-gray-500 font-mono">
                        {tx.fx_rate_to_aud !== null && tx.currency !== "AUD"
                          ? tx.fx_rate_to_aud.toFixed(4)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Confirm bar */}
            <div className="p-4 border-t border-gray-800 flex items-center justify-between">
              <p className="text-sm text-gray-400">
                <span className="text-gray-200 font-medium">{selected.size}</span> of{" "}
                {preview.transactions.length} transactions selected
              </p>
              <button
                onClick={() => confirmMutation.mutate()}
                disabled={selected.size === 0 || confirmMutation.isPending || !accountId}
                className="btn-primary flex items-center gap-2 disabled:opacity-40"
              >
                {confirmMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <CheckCircle className="w-4 h-4" />
                )}
                Import {selected.size} transactions
              </button>
            </div>
            {!accountId && (
              <p className="px-4 pb-3 text-xs text-yellow-400">
                Enter a destination account ID above to enable import.
              </p>
            )}
          </div>
        </>
      )}

      {/* Success state */}
      {confirmed && confirmMutation.data && (
        <div className="card-glass p-8 text-center space-y-3 border border-green-500/20 bg-green-500/5">
          <CheckCircle className="w-12 h-12 text-green-400 mx-auto" />
          <h2 className="text-xl font-semibold text-gray-100">Import complete</h2>
          <p className="text-gray-400 text-sm">
            <span className="text-green-400 font-medium">
              {confirmMutation.data.saved}
            </span>{" "}
            transactions saved
            {confirmMutation.data.skipped_duplicates > 0 && (
              <>
                {" "}·{" "}
                <span className="text-gray-500">
                  {confirmMutation.data.skipped_duplicates} duplicates skipped
                </span>
              </>
            )}
          </p>
          <button
            onClick={() => {
              setPreview(null);
              setConfirmed(false);
              if (fileRef.current) fileRef.current.value = "";
            }}
            className="btn-secondary text-sm"
          >
            Import another file
          </button>
        </div>
      )}
    </div>
  );
}

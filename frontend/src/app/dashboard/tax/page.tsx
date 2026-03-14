"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { MetricCard } from "@/components/ui/MetricCard";
import {
  formatAUD,
  formatPercent,
  formatFinancialYear,
  currentAUFinancialYear,
} from "@/lib/utils/formatters";
import {
  FileText,
  Download,
  TrendingDown,
  AlertCircle,
  DollarSign,
  Info,
} from "lucide-react";
import clsx from "clsx";

// Australian financial year options
const CURRENT_FY = currentAUFinancialYear();
const FY_OPTIONS = [CURRENT_FY, CURRENT_FY - 1, CURRENT_FY - 2];

export default function TaxPage() {
  const [fyYear, setFyYear] = useState(CURRENT_FY);
  const [method, setMethod] = useState("FIFO");

  const fyLabel = formatFinancialYear(fyYear);

  const { data: summary, isLoading } = useQuery({
    queryKey: ["tax", "ato", "summary", fyYear, method],
    queryFn: () =>
      api
        .get(`/tax/ato/summary?fy=${fyYear}&method=${method}`)
        .then((r) => r.data),
    staleTime: 60_000,
  });

  const { data: tlhOpportunities } = useQuery({
    queryKey: ["tax", "tlh"],
    queryFn: () => api.get("/tax/tlh-opportunities").then((r) => r.data),
  });

  const exportCsv = () => {
    window.open(
      `${process.env.NEXT_PUBLIC_API_URL}/api/v1/tax/ato/export/csv?fy=${fyYear}&method=${method}`,
      "_blank",
    );
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Tax Centre</h1>
          <p className="text-gray-400 text-sm mt-1">
            Australian Tax Office (ATO) — Capital Gains & Income Report
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* FY selector */}
          <select
            value={fyYear}
            onChange={(e) => setFyYear(Number(e.target.value))}
            className="bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm"
          >
            {FY_OPTIONS.map((fy) => (
              <option key={fy} value={fy}>
                FY{formatFinancialYear(fy)}
              </option>
            ))}
          </select>
          {/* Cost method */}
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm"
          >
            {["FIFO", "LIFO", "HIFO"].map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button
            onClick={exportCsv}
            className="btn-secondary flex items-center gap-2 text-sm"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Top Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Gross Capital Gains"
          value={formatAUD(summary?.gross_capital_gains_aud ?? 0)}
          subtitle="ATO Item 18A (before discount)"
          icon={<DollarSign className="w-4 h-4" />}
          loading={isLoading}
        />
        <MetricCard
          title="Net Capital Gain"
          value={formatAUD(summary?.net_capital_gain_aud ?? 0)}
          subtitle="ATO Item 18H (after discount & losses)"
          icon={<FileText className="w-4 h-4" />}
          positive={(summary?.net_capital_gain_aud ?? 0) <= 0}
          loading={isLoading}
        />
        <MetricCard
          title="Investment Income"
          value={formatAUD(
            (summary?.dividend_income_aud ?? 0) +
              (summary?.staking_income_aud ?? 0) +
              (summary?.interest_income_aud ?? 0),
          )}
          subtitle={`Div + Staking + Interest`}
          icon={<DollarSign className="w-4 h-4" />}
          loading={isLoading}
        />
        <MetricCard
          title="Est. Tax on Investments"
          value={formatAUD(summary?.estimated_tax_on_income ?? 0)}
          subtitle={`Effective rate: ${formatPercent(summary?.effective_tax_rate ?? 0, 1)}`}
          icon={<FileText className="w-4 h-4" />}
          loading={isLoading}
        />
      </div>

      {/* ATO CGT Discount Waterfall */}
      <div className="card-glass p-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-1">
          CGT Calculation — FY{fyLabel}
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          ITAA 1997 Division 115 • 50% discount for assets held ≥ 12 months •
          All amounts in AUD
        </p>

        <div className="space-y-0 divide-y divide-gray-800">
          {[
            {
              label: "18A — Gross capital gains (before discount)",
              value: summary?.gross_capital_gains_aud ?? 0,
              note: "Total gains from all disposal events",
              bold: false,
            },
            {
              label: "Capital losses applied (current year)",
              value: -(summary?.capital_losses_current_aud ?? 0),
              note: "Losses must first offset non-discount gains (s102-5)",
              bold: false,
              negative: true,
            },
            {
              label: "Discount-eligible gains (before 50% reduction)",
              value: summary?.discount_gains_before_discount ?? 0,
              note: "Assets held ≥ 365 days",
              bold: false,
            },
            {
              label: "50% CGT discount applied",
              value: -(summary?.cgt_discount_applied ?? 0),
              note: "Div 115 — individual taxpayer rate",
              bold: false,
              negative: true,
              highlight: "green",
            },
            {
              label: "18H — Net capital gain",
              value: summary?.net_capital_gain_aud ?? 0,
              note: "Assessable income from CGT events",
              bold: true,
              highlight: (summary?.net_capital_gain_aud ?? 0) > 0 ? "yellow" : "green",
            },
            {
              label: "18V — Capital losses carried forward",
              value: summary?.capital_losses_carried_forward ?? 0,
              note: "Offset against future years' gains",
              bold: false,
              highlight: (summary?.capital_losses_carried_forward ?? 0) > 0 ? "blue" : undefined,
            },
          ].map((row) => (
            <div
              key={row.label}
              className="flex items-center justify-between py-3"
            >
              <div>
                <span
                  className={clsx(
                    "text-sm",
                    row.bold ? "text-gray-100 font-semibold" : "text-gray-300",
                  )}
                >
                  {row.label}
                </span>
                {row.note && (
                  <p className="text-xs text-gray-500 mt-0.5">{row.note}</p>
                )}
              </div>
              <span
                className={clsx(
                  "font-mono text-sm font-medium",
                  row.highlight === "green" && "text-green-400",
                  row.highlight === "yellow" && "text-yellow-400",
                  row.highlight === "blue" && "text-blue-400",
                  !row.highlight && "text-gray-200",
                )}
              >
                {row.negative && row.value !== 0 ? "-" : ""}
                {formatAUD(Math.abs(row.value))}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Income summary */}
      <div className="card-glass p-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-4">
          Investment Income — FY{fyLabel}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-0 divide-y divide-gray-800">
            {[
              {
                label: "Dividend income",
                value: summary?.dividend_income_aud ?? 0,
              },
              {
                label: "Franking credits",
                value: summary?.franking_credits_aud ?? 0,
                note: "Reduce tax payable dollar-for-dollar",
                highlight: "blue",
              },
              {
                label: "Staking / crypto rewards",
                value: summary?.staking_income_aud ?? 0,
              },
              {
                label: "Interest income",
                value: summary?.interest_income_aud ?? 0,
              },
            ].map((row) => (
              <div
                key={row.label}
                className="flex items-center justify-between py-3"
              >
                <div>
                  <span className="text-sm text-gray-300">{row.label}</span>
                  {row.note && (
                    <p className="text-xs text-gray-500 mt-0.5">{row.note}</p>
                  )}
                </div>
                <span
                  className={clsx(
                    "font-mono text-sm",
                    row.highlight === "blue"
                      ? "text-blue-400"
                      : "text-gray-200",
                  )}
                >
                  {formatAUD(row.value)}
                </span>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-4">
            <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
              <p className="text-xs text-gray-500 mb-1">Estimated tax on investment income</p>
              <div className="text-2xl font-bold text-yellow-400 font-mono">
                {formatAUD(summary?.estimated_tax_on_income ?? 0)}
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Effective rate:{" "}
                <span className="text-gray-300">
                  {formatPercent(summary?.effective_tax_rate ?? 0, 1)}
                </span>
              </p>
            </div>
            <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg flex items-start gap-2">
              <Info className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-blue-300">
                Tax estimates use 2024-25 ATO marginal rates including LITO and
                Medicare Levy. Franking credits reduce your tax payable further.
                This is not tax advice — consult a registered tax agent.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* TLH Opportunities */}
      {(summary?.tlh_opportunity_count ?? 0) > 0 && (
        <div className="card-glass p-6 border border-yellow-500/20 bg-yellow-500/5">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-lg bg-yellow-500/20 flex items-center justify-center">
              <TrendingDown className="w-5 h-5 text-yellow-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-100">
                Tax-Loss Harvesting Opportunities
              </h2>
              <p className="text-sm text-gray-400">
                {summary?.tlh_opportunity_count} positions with unrealized
                losses •{" "}
                <span className="text-green-400 font-medium">
                  {formatAUD(summary?.potential_tlh_savings_aud ?? 0)} potential
                  tax saving
                </span>
              </p>
            </div>
          </div>

          <div className="space-y-3">
            {(tlhOpportunities ?? []).slice(0, 5).map((opp: any) => (
              <div
                key={opp.symbol}
                className="flex items-center gap-4 p-3 bg-gray-900/50 rounded-lg border border-gray-800"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-medium text-gray-200">
                      {opp.symbol}
                    </span>
                    <span className="text-xs text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
                      {opp.asset_class}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">{opp.name}</p>
                </div>
                <div className="text-right">
                  <div className="text-red-400 font-medium text-sm">
                    {formatAUD(opp.unrealized_loss)}
                  </div>
                  <div className="text-xs text-gray-400">unrealized loss</div>
                </div>
                <div className="text-right">
                  <div className="text-green-400 font-medium text-sm">
                    {formatAUD(opp.tax_savings)}
                  </div>
                  <div className="text-xs text-gray-400">est. saving</div>
                </div>
                <div className="text-right text-xs text-gray-500">
                  {opp.holding_period_days}d
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-yellow-400 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-yellow-300">
              The ATO does not have a formal wash sale rule, but the General
              Anti-Avoidance Provisions (Part IVA) may apply if disposal and
              repurchase are structured purely to obtain a tax benefit. Consult
              a registered tax agent before acting.
            </p>
          </div>
        </div>
      )}

      {/* ATO myTax reference */}
      <div className="card-glass p-4 flex items-start gap-3 border border-gray-800">
        <FileText className="w-5 h-5 text-gray-500 mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-sm text-gray-300 font-medium">
            Reporting in myTax / Tax Return
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Enter the <span className="text-gray-300">Net capital gain (18H)</span> at{" "}
            <strong className="text-gray-300">Item 18</strong> of your tax return.
            Carried-forward losses go to <strong className="text-gray-300">18V</strong>.
            Dividend income and franking credits are reported at{" "}
            <strong className="text-gray-300">Item 11</strong>.
            Download the CSV above and give it to your tax agent.
          </p>
        </div>
      </div>
    </div>
  );
}

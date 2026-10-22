"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiSlow } from "@/lib/api/client";
import { formatAUD, formatFinancialYear, currentAUFinancialYear } from "@/lib/utils/formatters";
import {
  AlertTriangle,
  Calculator,
  CheckCircle2,
  ChevronDown,
  Download,
  FileText,
  Lightbulb,
  Loader2,
  Save,
  Settings2,
} from "lucide-react";
import clsx from "clsx";

type TaxSettings = {
  other_income_aud: number;
  other_deductions_aud: number;
  investment_deductions_aud: number;
  prior_year_capital_losses_aud: number;
  tax_withheld_aud: number;
  other_tax_offsets_aud: number;
  other_foreign_tax_offsets_aud: number;
  medicare_levy_exemption_pct: number;
  resident_full_year: boolean;
  franking_credits_eligible: boolean;
  other_franked_dividends_aud: number;
  other_unfranked_dividends_aud: number;
  other_foreign_dividends_aud: number;
  other_franking_credits_aud: number;
  foreign_tax_paid_aud: number;
  other_interest_income_aud: number;
  other_staking_income_aud: number;
  other_non_discount_capital_gains_aud: number;
  other_discount_capital_gains_aud: number;
  other_capital_losses_aud: number;
  notes: string | null;
};

type CGTEvent = {
  symbol: string;
  account_name: string;
  acquired: string;
  disposed: string;
  holding_days: number;
  discount_eligible: boolean;
  quantity: number;
  cost_base_aud: number;
  proceeds_aud: number;
  gross_gain_aud: number;
};

type TaxSummary = Record<string, any> & {
  financial_year: string;
  cost_method: string;
  gross_capital_gains_aud: number;
  capital_losses_current_aud: number;
  capital_losses_prior_aud: number;
  capital_losses_applied_aud: number;
  discount_gains_before_discount: number;
  cgt_discount_applied: number;
  net_capital_gain_aud: number;
  capital_losses_carried_forward: number;
  dividend_income_aud: number;
  franked_dividends_aud: number;
  unfranked_dividends_aud: number;
  foreign_dividends_aud: number;
  assessable_dividend_income_aud: number;
  franking_credits_aud: number;
  foreign_tax_paid_aud: number;
  staking_income_aud: number;
  interest_income_aud: number;
  investment_deductions_aud: number;
  total_taxable_income_aud: number;
  basic_income_tax_aud: number;
  lito_aud: number;
  medicare_levy_aud: number;
  franking_tax_offset_aud: number;
  foreign_tax_offsets_aud: number;
  other_tax_offsets_aud: number;
  tax_withheld_aud: number;
  net_tax_before_withholding_aud: number;
  estimated_tax_payable_aud: number;
  estimated_refund_aud: number;
  estimated_tax_on_investments_aud: number;
  effective_tax_rate: number;
  events: CGTEvent[];
  warnings: string[];
  optimization: {
    selected_cost_method: string;
    tax_optimal_net_capital_gain_aud?: number;
    potential_taxable_gain_reduction_aud?: number;
    estimated_tax_saving_aud?: number;
    recommendations: string[];
  };
};

const CURRENT_FY = currentAUFinancialYear();
const FY_OPTIONS = Array.from({ length: 7 }, (_, index) => CURRENT_FY - index);
const METHODS = ["FIFO", "LIFO", "HIFO", "TAX_OPTIMAL"];

const inputGroups: Array<{ title: string; description: string; fields: Array<[keyof TaxSettings, string]> }> = [
  {
    title: "Personal tax estimate",
    description: "These fields turn the investment workpaper into a whole-of-return estimate.",
    fields: [
      ["other_income_aud", "Salary and other assessable income"],
      ["other_deductions_aud", "Other deductions"],
      ["investment_deductions_aud", "Investment deductions"],
      ["tax_withheld_aud", "PAYG and other tax withheld"],
      ["other_tax_offsets_aud", "Other tax offsets"],
      ["other_foreign_tax_offsets_aud", "Other foreign income tax offsets"],
      ["medicare_levy_exemption_pct", "Medicare levy exemption (%)"],
    ],
  },
  {
    title: "Capital gains reconciliation",
    description: "Add items missing from broker feeds and the loss balance on your last assessment.",
    fields: [
      ["prior_year_capital_losses_aud", "Prior-year net capital losses"],
      ["other_non_discount_capital_gains_aud", "Other non-discount capital gains"],
      ["other_discount_capital_gains_aud", "Other discount capital gains (before discount)"],
      ["other_capital_losses_aud", "Other current-year capital losses"],
    ],
  },
  {
    title: "Income reconciliation",
    description: "Use annual dividend and managed-fund tax statements to fill gaps.",
    fields: [
      ["other_franked_dividends_aud", "Other franked dividends"],
      ["other_unfranked_dividends_aud", "Other unfranked dividends"],
      ["other_franking_credits_aud", "Other franking credits"],
      ["other_foreign_dividends_aud", "Other foreign dividends"],
      ["foreign_tax_paid_aud", "Foreign tax paid"],
      ["other_interest_income_aud", "Other interest income"],
      ["other_staking_income_aud", "Other staking / rewards income"],
    ],
  },
];

function MoneyInput({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return (
    <div className="relative">
      <span className="absolute left-3 top-2 text-sm text-gray-500">$</span>
      <input
        type="number"
        min={0}
        step="0.01"
        value={Number.isFinite(value) ? value : 0}
        onChange={(event) => onChange(Math.max(0, Number(event.target.value) || 0))}
        className="w-full rounded-lg border border-gray-700 bg-gray-900 py-2 pl-7 pr-3 text-right text-sm text-gray-200 outline-none focus:border-blue-500"
      />
    </div>
  );
}

function Stat({ label, value, note, tone = "default" }: { label: string; value: string; note?: string; tone?: "default" | "good" | "warn" }) {
  return (
    <div className="card-glass p-4">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className={clsx("mt-2 font-mono text-2xl font-semibold", tone === "good" ? "text-green-400" : tone === "warn" ? "text-yellow-400" : "text-gray-100")}>{value}</p>
      {note && <p className="mt-1 text-xs text-gray-500">{note}</p>}
    </div>
  );
}

function Row({ label, value, note, strong, subtract }: { label: string; value: number; note?: string; strong?: boolean; subtract?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-gray-800 py-3 last:border-0">
      <div>
        <p className={strong ? "font-medium text-gray-100" : "text-sm text-gray-300"}>{label}</p>
        {note && <p className="mt-0.5 text-xs text-gray-500">{note}</p>}
      </div>
      <p className={clsx("whitespace-nowrap font-mono text-sm", strong ? "font-semibold text-gray-100" : subtract ? "text-green-400" : "text-gray-200")}>
        {subtract && value > 0 ? "−" : ""}{formatAUD(Math.abs(value))}
      </p>
    </div>
  );
}

export default function TaxPage() {
  const queryClient = useQueryClient();
  // Tax returns normally concern the latest completed FY. Keep the current,
  // in-progress FY available for planning without opening on an expected zero.
  const [fyYear, setFyYear] = useState(CURRENT_FY - 1);
  const [method, setMethod] = useState("FIFO");
  const [inputsOpen, setInputsOpen] = useState(true);
  const [draft, setDraft] = useState<TaxSettings | null>(null);
  const [exporting, setExporting] = useState(false);

  const settingsQuery = useQuery({
    queryKey: ["tax", "ato", "settings", fyYear],
    queryFn: () => api.get(`/tax/ato/settings?fy=${fyYear}`).then((response) => response.data),
  });
  useEffect(() => {
    if (settingsQuery.data) {
      const { fy_end_year: _fy, saved: _saved, ...settings } = settingsQuery.data;
      setDraft(settings as TaxSettings);
    }
  }, [settingsQuery.data]);

  const summaryQuery = useQuery<TaxSummary>({
    queryKey: ["tax", "ato", "summary", fyYear, method],
    queryFn: () => apiSlow.get(`/tax/ato/summary?fy=${fyYear}&method=${method}`).then((response) => response.data),
  });

  const saveMutation = useMutation({
    mutationFn: () => api.put(`/tax/ato/settings?fy=${fyYear}`, draft),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tax", "ato", "settings", fyYear] });
      await queryClient.invalidateQueries({ queryKey: ["tax", "ato", "summary", fyYear] });
    },
  });

  const summary = summaryQuery.data;
  const dirty = useMemo(() => {
    if (!draft || !settingsQuery.data) return false;
    return Object.keys(draft).some((key) => draft[key as keyof TaxSettings] !== settingsQuery.data[key]);
  }, [draft, settingsQuery.data]);

  const setField = <K extends keyof TaxSettings>(field: K, value: TaxSettings[K]) => {
    setDraft((current) => current ? { ...current, [field]: value } : current);
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      const response = await apiSlow.get(`/tax/ato/export/csv?fy=${fyYear}&method=${method}`, { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `ato-investment-tax-pack-fy${fyYear - 1}-${String(fyYear).slice(-2)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Tax Centre</h1>
          <p className="mt-1 text-sm text-gray-400">Australian investment tax workpaper and planning estimate</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select value={fyYear} onChange={(event) => setFyYear(Number(event.target.value))} className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200">
            {FY_OPTIONS.map((fy) => <option key={fy} value={fy}>FY{formatFinancialYear(fy)}</option>)}
          </select>
          <select value={method} onChange={(event) => setMethod(event.target.value)} className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200">
            {METHODS.map((item) => <option key={item} value={item}>{item === "TAX_OPTIMAL" ? "Tax optimal (review)" : item}</option>)}
          </select>
          <button onClick={exportCsv} disabled={!summary || exporting} className="btn-secondary flex items-center gap-2 text-sm disabled:opacity-50">
            {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Tax pack CSV
          </button>
        </div>
      </div>

      {(summaryQuery.isError || settingsQuery.isError) && (
        <div className="flex gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          <AlertTriangle className="h-5 w-5 shrink-0" /> Tax data could not be calculated. Check that the API is running and retry.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="18H Total capital gains" value={formatAUD(summary?.gross_capital_gains_aud ?? 0)} note="Before losses and discount" />
        <Stat label="18A Net capital gain" value={formatAUD(summary?.net_capital_gain_aud ?? 0)} note="Included in assessable income" tone={(summary?.net_capital_gain_aud ?? 0) === 0 ? "good" : "warn"} />
        <Stat label="Investment tax impact" value={formatAUD(summary?.estimated_tax_on_investments_aud ?? 0)} note="Incremental estimate after offsets" />
        <Stat
          label={(summary?.estimated_refund_aud ?? 0) > 0 ? "Estimated refund" : "Estimated amount due"}
          value={formatAUD((summary?.estimated_refund_aud ?? 0) > 0 ? (summary?.estimated_refund_aud ?? 0) : (summary?.estimated_tax_payable_aud ?? 0))}
          note="Needs complete personal FY inputs"
          tone={(summary?.estimated_refund_aud ?? 0) > 0 ? "good" : "warn"}
        />
      </div>

      {(summary?.warnings?.length ?? 0) > 0 && (
        <section className="rounded-xl border border-yellow-500/25 bg-yellow-500/5 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-yellow-300"><AlertTriangle className="h-4 w-4" /> Reconcile before lodging</div>
          <ul className="space-y-1 text-xs text-yellow-200/80">
            {summary?.warnings.map((warning) => <li key={warning}>• {warning}</li>)}
          </ul>
        </section>
      )}

      <section className="card-glass overflow-hidden">
        <button onClick={() => setInputsOpen((value) => !value)} className="flex w-full items-center justify-between p-5 text-left">
          <div className="flex items-center gap-3">
            <Settings2 className="h-5 w-5 text-blue-400" />
            <div><h2 className="font-semibold text-gray-100">FY inputs and annual-statement adjustments</h2><p className="mt-0.5 text-xs text-gray-500">Saved separately for FY{formatFinancialYear(fyYear)}</p></div>
          </div>
          <ChevronDown className={clsx("h-5 w-5 text-gray-500 transition-transform", inputsOpen && "rotate-180")} />
        </button>
        {inputsOpen && draft && (
          <div className="border-t border-gray-800 p-5">
            <div className="grid gap-6 xl:grid-cols-3">
              {inputGroups.map((group) => (
                <div key={group.title}>
                  <h3 className="text-sm font-medium text-gray-200">{group.title}</h3>
                  <p className="mb-4 mt-1 min-h-8 text-xs text-gray-500">{group.description}</p>
                  <div className="space-y-3">
                    {group.fields.map(([field, label]) => (
                      <label key={field} className="block">
                        <span className="mb-1 block text-xs text-gray-400">{label}</span>
                        {field === "medicare_levy_exemption_pct" ? (
                          <input type="number" min={0} max={100} value={Number(draft[field])} onChange={(event) => setField(field, Math.min(100, Math.max(0, Number(event.target.value) || 0)))} className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-right text-sm text-gray-200" />
                        ) : <MoneyInput value={Number(draft[field])} onChange={(value) => setField(field, value as never)} />}
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-gray-800 pt-5">
              <div className="flex flex-wrap gap-5 text-xs text-gray-400">
                <label className="flex items-center gap-2"><input type="checkbox" checked={draft.resident_full_year} onChange={(event) => setField("resident_full_year", event.target.checked)} /> Australian resident for the full FY</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={draft.franking_credits_eligible} onChange={(event) => setField("franking_credits_eligible", event.target.checked)} /> Eligible to claim franking credits</label>
              </div>
              <button disabled={!dirty || saveMutation.isPending} onClick={() => saveMutation.mutate()} className="btn-primary flex items-center gap-2 text-sm disabled:cursor-not-allowed disabled:opacity-50">
                {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : saveMutation.isSuccess && !dirty ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}
                {saveMutation.isPending ? "Recalculating…" : "Save and recalculate"}
              </button>
            </div>
          </div>
        )}
      </section>

      {summaryQuery.isLoading ? (
        <div className="flex h-48 items-center justify-center text-gray-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Calculating parcels and tax…</div>
      ) : summary && (
        <>
          <div className="grid gap-6 xl:grid-cols-2">
            <section className="card-glass p-5">
              <div className="mb-3 flex items-center gap-2"><Calculator className="h-5 w-5 text-blue-400" /><h2 className="font-semibold text-gray-100">Capital gains calculation</h2></div>
              <Row label="18H — Total current year capital gains" value={summary.gross_capital_gains_aud} note="All positive gains before losses and CGT discount" />
              <Row label="Current-year capital losses" value={summary.capital_losses_current_aud} subtract />
              <Row label="Prior-year capital losses" value={summary.capital_losses_prior_aud} subtract />
              <Row label="Total losses applied" value={summary.capital_losses_applied_aud} subtract note="Applied to non-discount gains first" />
              <Row label="Discount gains remaining" value={summary.discount_gains_before_discount} />
              <Row label="50% CGT discount" value={summary.cgt_discount_applied} subtract />
              <Row label="18A — Net capital gain" value={summary.net_capital_gain_aud} strong />
              <Row label="18V — Losses carried forward" value={summary.capital_losses_carried_forward} strong />
            </section>

            <section className="card-glass p-5">
              <div className="mb-3 flex items-center gap-2"><FileText className="h-5 w-5 text-purple-400" /><h2 className="font-semibold text-gray-100">Investment income</h2></div>
              <Row label="11T — Franked dividends" value={summary.franked_dividends_aud} />
              <Row label="11S — Unfranked dividends" value={summary.unfranked_dividends_aud} />
              <Row label="Foreign dividends" value={summary.foreign_dividends_aud} />
              <Row label="11U — Franking credits" value={summary.franking_credits_aud} note="Grossed up into assessable income and claimed as an offset" />
              <Row label="Assessable dividend income" value={summary.assessable_dividend_income_aud} strong />
              <Row label="Interest income" value={summary.interest_income_aud} />
              <Row label="Staking / rewards income" value={summary.staking_income_aud} />
              <Row label="Investment deductions" value={summary.investment_deductions_aud} subtract />
            </section>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <section className="card-glass p-5">
              <h2 className="mb-3 font-semibold text-gray-100">Estimated assessment</h2>
              <Row label="Taxable income" value={summary.total_taxable_income_aud} strong />
              <Row label="Basic income tax" value={summary.basic_income_tax_aud} />
              <Row label="Low income tax offset" value={summary.lito_aud} subtract />
              <Row label="Medicare levy" value={summary.medicare_levy_aud} />
              <Row label="Franking tax offset" value={summary.franking_tax_offset_aud} subtract />
              <Row label="Foreign income tax offsets" value={summary.foreign_tax_offsets_aud} subtract />
              <Row label="Other tax offsets" value={summary.other_tax_offsets_aud} subtract />
              <Row label="Net tax before withholding" value={summary.net_tax_before_withholding_aud} strong />
              <Row label="Tax withheld / PAYG credits" value={summary.tax_withheld_aud} subtract />
              <div className="mt-4 rounded-lg bg-gray-900 p-4 text-xs text-gray-500">
                Uses the legislated resident-individual rates selected for FY{formatFinancialYear(fyYear)}. HELP repayments, Medicare levy surcharge, family thresholds, SAPTO, private health insurance and unusual offsets are not calculated.
              </div>
            </section>

            <section className="card-glass p-5">
              <div className="mb-3 flex items-center gap-2"><Lightbulb className="h-5 w-5 text-yellow-400" /><h2 className="font-semibold text-gray-100">Tax optimisation review</h2></div>
              {(summary.optimization.potential_taxable_gain_reduction_aud ?? 0) > 0 ? (
                <div className="mb-4 rounded-xl border border-green-500/25 bg-green-500/10 p-4">
                  <p className="text-sm text-green-300">Potential estimated saving</p>
                  <p className="mt-1 font-mono text-2xl font-semibold text-green-400">{formatAUD(summary.optimization.estimated_tax_saving_aud ?? 0)}</p>
                  <p className="mt-1 text-xs text-green-200/70">Taxable gain reduction of {formatAUD(summary.optimization.potential_taxable_gain_reduction_aud ?? 0)} versus {method}</p>
                  <button onClick={() => setMethod("TAX_OPTIMAL")} className="mt-3 text-xs font-medium text-green-300 underline">Review tax-optimal parcels</button>
                </div>
              ) : <p className="mb-4 text-sm text-gray-400">The selected parcels already produce the lowest calculated net gain among available parcels.</p>}
              <ul className="space-y-3 text-sm text-gray-400">
                {summary.optimization.recommendations.map((item) => <li key={item} className="flex gap-2"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-yellow-500" />{item}</li>)}
              </ul>
              <p className="mt-4 text-xs text-gray-600">Parcel optimisation is a planning aid. Your election must match records that identify the actual shares or units disposed of.</p>
            </section>
          </div>

          <section className="card-glass overflow-hidden">
            <div className="flex items-center justify-between border-b border-gray-800 p-5">
              <div><h2 className="font-semibold text-gray-100">CGT event workpaper</h2><p className="mt-1 text-xs text-gray-500">{summary.events.length} matched disposal parcels • {summary.cost_method}</p></div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead className="bg-gray-900/70 text-left text-xs uppercase text-gray-500"><tr><th className="px-5 py-3">Asset</th><th className="px-4 py-3">Account</th><th className="px-4 py-3">Acquired</th><th className="px-4 py-3">Disposed</th><th className="px-4 py-3 text-right">Quantity</th><th className="px-4 py-3 text-right">Cost base</th><th className="px-4 py-3 text-right">Proceeds</th><th className="px-5 py-3 text-right">Gain / loss</th></tr></thead>
                <tbody className="divide-y divide-gray-800">
                  {summary.events.map((event, index) => (
                    <tr key={`${event.symbol}-${event.acquired}-${event.disposed}-${index}`} className="text-gray-300">
                      <td className="px-5 py-3 font-mono text-gray-100">{event.symbol}{event.discount_eligible && <span className="ml-2 rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-300">50%</span>}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">{event.account_name}</td><td className="px-4 py-3">{event.acquired}</td><td className="px-4 py-3">{event.disposed}</td><td className="px-4 py-3 text-right font-mono">{event.quantity.toLocaleString()}</td><td className="px-4 py-3 text-right font-mono">{formatAUD(event.cost_base_aud)}</td><td className="px-4 py-3 text-right font-mono">{formatAUD(event.proceeds_aud)}</td><td className={clsx("px-5 py-3 text-right font-mono", event.gross_gain_aud >= 0 ? "text-green-400" : "text-red-400")}>{formatAUD(event.gross_gain_aud)}</td>
                    </tr>
                  ))}
                  {summary.events.length === 0 && <tr><td colSpan={8} className="px-5 py-12 text-center text-gray-500">No matched disposals in this financial year.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <div className="flex gap-3 rounded-xl border border-blue-500/20 bg-blue-500/5 p-4 text-xs text-blue-200/70">
        <AlertTriangle className="h-4 w-4 shrink-0 text-blue-400" />
        This workpaper is not a lodged return or personal tax advice. Reconcile it to contract notes, dividend statements and managed-fund annual tax statements, then have a registered tax agent review residency, parcel identification and any Part IVA concerns.
      </div>
    </div>
  );
}

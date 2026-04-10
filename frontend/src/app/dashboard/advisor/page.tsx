"use client";

import { useState, useRef, useEffect } from "react";
import { useAdvisorChat } from "@/lib/hooks/useAdvisorChat";
import { useOllamaStatus, useLMStudioStatus, type Provider } from "@/lib/hooks/useTrading";
import { Send, Bot, User, Loader2, Sparkles, RefreshCw } from "lucide-react";
import clsx from "clsx";

interface Message {
  role: "user" | "assistant";
  content: string;
  provider?: Provider;
  timestamp: Date;
}

const SUGGESTED_PROMPTS = [
  "Analyse my portfolio's risk and suggest improvements",
  "What's my biggest concentration risk?",
  "Which positions have the best and worst unrealised P&L?",
  "What's my exposure to crypto vs equities?",
  "Find tax-loss harvesting opportunities (ATO rules)",
  "How diversified is my portfolio across sectors?",
  "Which positions should I consider trimming?",
  "Summarise my overall portfolio health",
];

const PROVIDER_CONFIG: Record<Provider, { label: string; color: string; dot: string }> = {
  gemini:   { label: "Gemini",    color: "bg-blue-600",   dot: "bg-blue-400" },
  claude:   { label: "Claude",    color: "bg-amber-600",  dot: "bg-amber-400" },
  openai:   { label: "GPT-4o",    color: "bg-green-600",  dot: "bg-green-400" },
  ollama:   { label: "Ollama",    color: "bg-violet-600", dot: "bg-violet-400" },
  lmstudio: { label: "LM Studio", color: "bg-teal-600",   dot: "bg-teal-400" },
};

export default function AdvisorPage() {
  const [messages, setMessages]   = useState<Message[]>([]);
  const [input, setInput]         = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [provider, setProvider]   = useState<Provider>("gemini");
  const [error, setError]         = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { chat, isLoading }           = useAdvisorChat();
  const { data: ollamaStatus }        = useOllamaStatus();
  const { data: lmStudioStatus }      = useLMStudioStatus();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || isLoading) return;
    setError(null);

    const userMsg: Message = { role: "user", content: text, timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    try {
      const response = await chat({ message: text, session_id: sessionId, provider });
      setSessionId(response.session_id);
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: response.content,
        provider,
        timestamp: new Date(),
      }]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? "Unknown error";
      setError(detail);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
  };

  const reset = () => { setMessages([]); setSessionId(undefined); setError(null); };

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-100">AI Portfolio Advisor</h1>
            <p className="text-xs text-gray-400">Analyses your live holdings · multi-provider</p>
          </div>
        </div>
        {messages.length > 0 && (
          <button onClick={reset} className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-600 px-3 py-1.5 rounded-lg transition-colors">
            <RefreshCw className="w-3.5 h-3.5" /> New Chat
          </button>
        )}
      </div>

      {/* Provider selector */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="text-xs text-gray-500 uppercase tracking-wider">AI Provider:</span>
        {(Object.entries(PROVIDER_CONFIG) as [Provider, typeof PROVIDER_CONFIG[Provider]][]).map(([p, cfg]) => {
          const isLocal = p === "ollama" || p === "lmstudio";
          const localAvailable = p === "ollama" ? ollamaStatus?.available : lmStudioStatus?.available;
          const disabled = isLocal && !localAvailable;
          const activeModel = p === "lmstudio" ? lmStudioStatus?.active_model : null;
          const title = p === "ollama"
            ? (ollamaStatus?.available ? `Ollama · ${ollamaStatus.models.join(", ")}` : "Ollama not running — start with: ollama serve")
            : p === "lmstudio"
            ? (lmStudioStatus?.available ? `LM Studio · ${activeModel ?? lmStudioStatus?.models[0]}` : "LM Studio server not running — enable in Local Server tab")
            : cfg.label;

          return (
            <button
              key={p}
              onClick={() => !disabled && setProvider(p)}
              disabled={disabled}
              title={title}
              className={clsx(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
                provider === p
                  ? `${cfg.color} text-white border-transparent`
                  : disabled
                  ? "text-gray-700 border-gray-800 cursor-not-allowed"
                  : "text-gray-400 border-gray-700 hover:border-gray-600 hover:text-gray-200"
              )}>
              <span className={clsx("w-1.5 h-1.5 rounded-full", isLocal ? (localAvailable ? cfg.dot : "bg-gray-700") : cfg.dot)} />
              {cfg.label}
              {p === "lmstudio" && lmStudioStatus?.available && activeModel && (
                <span className="text-[10px] opacity-70 ml-0.5">{activeModel.split("/").pop()?.split("-").slice(0,2).join("-")}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-3 text-sm text-red-400 bg-red-400/5 border border-red-400/20 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Chat Area */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 min-h-0">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-6">
            <div className="text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/30 flex items-center justify-center mx-auto mb-4">
                <Bot className="w-8 h-8 text-blue-400" />
              </div>
              <h2 className="text-lg font-semibold text-gray-200 mb-2">Ask about your portfolio</h2>
              <p className="text-sm text-gray-400 max-w-md">
                Your holdings are automatically loaded. Ask anything about positions, risk, P&L, or tax.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button key={prompt} onClick={() => sendMessage(prompt)}
                  className="text-left text-sm text-gray-300 bg-gray-800/60 hover:bg-gray-800 border border-gray-700 hover:border-gray-600 rounded-lg p-3 transition-all">
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => <MessageBubble key={i} message={msg} />)}
            {isLoading && (
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-4 h-4 text-white" />
                </div>
                <div className="bg-gray-900 border border-gray-800 p-4 rounded-2xl rounded-tl-sm">
                  <div className="flex items-center gap-2 text-gray-400">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm">Analysing your portfolio…</span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div className="flex items-end gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your portfolio…"
            rows={1}
            className="flex-1 bg-transparent text-gray-100 placeholder-gray-500 resize-none outline-none text-sm leading-relaxed"
            style={{ maxHeight: "120px" }}
            onInput={(e) => {
              const t = e.target as HTMLTextAreaElement;
              t.style.height = "auto";
              t.style.height = Math.min(t.scrollHeight, 120) + "px";
            }}
          />
          <button onClick={() => sendMessage(input)} disabled={isLoading || !input.trim()}
            className={clsx(
              "w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 transition-all",
              input.trim() && !isLoading ? "bg-blue-600 hover:bg-blue-700 text-white" : "bg-gray-800 text-gray-600 cursor-not-allowed"
            )}>
            <Send className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          ⚠️ Not financial advice. Consult a licensed advisor for investment decisions.
        </p>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const providerCfg = message.provider ? PROVIDER_CONFIG[message.provider] : null;

  return (
    <div className={clsx("flex items-start gap-3", isUser && "flex-row-reverse")}>
      <div className={clsx(
        "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
        isUser ? "bg-gray-700" : "bg-gradient-to-br from-blue-500 to-purple-600"
      )}>
        {isUser ? <User className="w-4 h-4 text-gray-300" /> : <Bot className="w-4 h-4 text-white" />}
      </div>
      <div className={clsx("max-w-[80%]", isUser && "items-end flex flex-col")}>
        <div className={clsx(
          "rounded-2xl p-4 text-sm leading-relaxed",
          isUser ? "bg-blue-600 text-white rounded-tr-sm" : "bg-gray-900 border border-gray-800 text-gray-200 rounded-tl-sm"
        )}>
          <FormattedContent content={message.content} />
        </div>
        <div className="flex items-center gap-2 mt-1 px-1">
          <span className="text-xs text-gray-600">
            {message.timestamp.toLocaleTimeString("en-AU", { timeStyle: "short" })}
          </span>
          {!isUser && providerCfg && (
            <span className="text-[10px] text-gray-600">{providerCfg.label}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function FormattedContent({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        if (line.startsWith("### ")) return <h4 key={i} className="font-semibold text-sm mt-2 text-gray-100">{line.slice(4)}</h4>;
        if (line.startsWith("## "))  return <h3 key={i} className="font-semibold text-base mt-3 text-gray-100">{line.slice(3)}</h3>;
        if (line.startsWith("# "))   return <h2 key={i} className="font-bold text-lg mt-3 text-gray-100">{line.slice(2)}</h2>;
        if (line.startsWith("- ") || line.startsWith("• ")) return <p key={i} className="pl-3">• {line.slice(2)}</p>;
        if (line.startsWith("⚠️") || line.startsWith("_This analysis"))
          return <p key={i} className="text-xs text-yellow-600/80 mt-3 italic">{line.replace(/^_|_$/g, "")}</p>;
        if (line.startsWith("**") && line.endsWith("**"))
          return <p key={i} className="font-semibold text-gray-100">{line.slice(2, -2)}</p>;
        if (!line.trim()) return <div key={i} className="h-1" />;
        // Inline bold
        const parts = line.split(/(\*\*[^*]+\*\*)/g);
        return (
          <p key={i}>
            {parts.map((part, j) =>
              part.startsWith("**") && part.endsWith("**")
                ? <strong key={j} className="text-gray-100 font-semibold">{part.slice(2, -2)}</strong>
                : part
            )}
          </p>
        );
      })}
    </div>
  );
}

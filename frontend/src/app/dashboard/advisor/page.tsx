"use client";

import { useState, useRef, useEffect } from "react";
import { useAdvisorChat } from "@/lib/hooks/useAdvisorChat";
import { Send, Bot, User, Loader2, Sparkles, RefreshCw } from "lucide-react";
import { formatCurrency } from "@/lib/utils/formatters";
import clsx from "clsx";

interface Message {
  role: "user" | "assistant";
  content: string;
  toolCalls?: string[];
  timestamp: Date;
}

const SUGGESTED_PROMPTS = [
  "Analyze my portfolio's risk and suggest improvements",
  "What's my exposure to tech stocks?",
  "Find tax-loss harvesting opportunities",
  "How does my portfolio compare to the S&P 500?",
  "What's my biggest concentration risk?",
  "Calculate my estimated tax liability this year",
];

export default function AdvisorPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { chat, isLoading } = useAdvisorChat();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || isLoading) return;

    const userMsg: Message = {
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    try {
      const response = await chat({ message: text, session_id: sessionId });
      setSessionId(response.session_id);

      const assistantMsg: Message = {
        role: "assistant",
        content: response.content,
        toolCalls: response.tool_calls,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errMsg: Message = {
        role: "assistant",
        content: "I encountered an error. Please try again.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errMsg]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const reset = () => {
    setMessages([]);
    setSessionId(undefined);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-100">AI Portfolio Advisor</h1>
            <p className="text-xs text-gray-400">Powered by Claude · Real portfolio data</p>
          </div>
        </div>
        {messages.length > 0 && (
          <button onClick={reset} className="btn-secondary flex items-center gap-2 text-sm">
            <RefreshCw className="w-4 h-4" />
            New Chat
          </button>
        )}
      </div>

      {/* Chat Area */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-6">
            <div className="text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-blue-500/30 flex items-center justify-center mx-auto mb-4">
                <Bot className="w-8 h-8 text-blue-400" />
              </div>
              <h2 className="text-lg font-semibold text-gray-200 mb-2">Ask about your portfolio</h2>
              <p className="text-sm text-gray-400 max-w-md">
                I can analyze your holdings, identify risks, find tax opportunities,
                and benchmark your performance — using your live portfolio data.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => sendMessage(prompt)}
                  className="text-left text-sm text-gray-300 bg-gray-800/60 hover:bg-gray-800 border border-gray-700 hover:border-gray-600 rounded-lg p-3 transition-all"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => (
              <MessageBubble key={i} message={msg} />
            ))}
            {isLoading && (
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-4 h-4 text-white" />
                </div>
                <div className="card-glass p-4 rounded-2xl rounded-tl-sm">
                  <div className="flex items-center gap-2 text-gray-400">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm">Analyzing your portfolio...</span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      <div className="card-glass p-4">
        <div className="flex items-end gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your portfolio..."
            rows={1}
            className="flex-1 bg-transparent text-gray-100 placeholder-gray-500 resize-none outline-none text-sm leading-relaxed"
            style={{ maxHeight: "120px" }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "auto";
              target.style.height = Math.min(target.scrollHeight, 120) + "px";
            }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={isLoading || !input.trim()}
            className={clsx(
              "w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 transition-all",
              input.trim() && !isLoading
                ? "bg-blue-600 hover:bg-blue-700 text-white"
                : "bg-gray-800 text-gray-600 cursor-not-allowed"
            )}
          >
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

  return (
    <div className={clsx("flex items-start gap-3", isUser && "flex-row-reverse")}>
      <div
        className={clsx(
          "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
          isUser
            ? "bg-gray-700"
            : "bg-gradient-to-br from-blue-500 to-purple-600"
        )}
      >
        {isUser ? (
          <User className="w-4 h-4 text-gray-300" />
        ) : (
          <Bot className="w-4 h-4 text-white" />
        )}
      </div>
      <div className={clsx("max-w-[80%]", isUser && "items-end flex flex-col")}>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {message.toolCalls.map((tool) => (
              <span
                key={tool}
                className="text-xs text-blue-400 bg-blue-400/10 border border-blue-400/20 px-2 py-0.5 rounded-full"
              >
                {tool.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        )}
        <div
          className={clsx(
            "rounded-2xl p-4 text-sm leading-relaxed",
            isUser
              ? "bg-blue-600 text-white rounded-tr-sm"
              : "card-glass text-gray-200 rounded-tl-sm"
          )}
        >
          <FormattedContent content={message.content} />
        </div>
        <span className="text-xs text-gray-600 mt-1 px-1">
          {message.timestamp.toLocaleTimeString("en-US", { timeStyle: "short" })}
        </span>
      </div>
    </div>
  );
}

function FormattedContent({ content }: { content: string }) {
  // Simple markdown-ish rendering
  const lines = content.split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        if (line.startsWith("## ")) {
          return <h3 key={i} className="font-semibold text-base mt-2">{line.slice(3)}</h3>;
        }
        if (line.startsWith("- ") || line.startsWith("• ")) {
          return <p key={i} className="pl-2">• {line.slice(2)}</p>;
        }
        if (line.startsWith("⚠️")) {
          return <p key={i} className="text-xs text-yellow-400 mt-2">{line}</p>;
        }
        return <p key={i}>{line}</p>;
      })}
    </div>
  );
}

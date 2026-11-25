import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Bot,
  History,
  MessageSquarePlus,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  chatWithOrchestrator,
  deleteConversation,
  fetchConversationMessages,
  fetchConversations,
  streamAgentChat,
} from "../api/client";
import { useAuth } from "../context/AuthContext";

const PROMPTS_BY_ROLE = {
  student: [
    "Quick veg food under ₹60",
    "Which outlet has the shortest wait right now?",
    "Check my latest order status",
    "Suggest an alternative for Veg Fried Rice",
  ],
  outlet_manager: [
    "Summarize my outlet stockouts and low stock",
    "What customer complaints or bottlenecks need attention?",
    "How can I speed up kitchen prep during rush hours?",
  ],
  admin: [
    "Compare outlet performance and bottlenecks across campus",
    "Which outlets have stockouts or recurring negative feedback?",
    "Summarize system analytics and recommended improvements",
  ],
};

export default function AiAssistantPanel({
  outletId = null,
  onAddToCart = null,
  onDataChanged = null,
}) {
  const { user, authConfig } = useAuth();
  const role = user?.role || "student";
  const quickPrompts = PROMPTS_BY_ROLE[role] || PROMPTS_BY_ROLE.student;

  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef(null);

  const loadConversations = useCallback(async () => {
    try {
      const res = await fetchConversations();
      setConversations(res.conversations || []);
    } catch {
      // Ignore sidebar load error
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const handleSelectConversation = async (convId) => {
    setError("");
    try {
      const res = await fetchConversationMessages(convId);
      setActiveConvId(convId);
      setMessages(
        (res.messages || []).map((m) => ({
          id: m.id,
          sender: m.sender,
          content: m.content,
          ai_mode: m.ai_mode,
          agents_invoked: m.agents_invoked || [],
          fallback_reason: m.metadata?.fallback_reason,
          suggested_items: m.metadata?.suggested_items || [],
          substitutes: m.metadata?.substitutes || [],
          fastest_outlet: m.metadata?.fastest_outlet || null,
          lifecycle: m.metadata?.agentic_lifecycle || null,
        }))
      );
      setShowHistory(false);
    } catch (err) {
      setError(err.message || "Could not load conversation history.");
    }
  };

  const handleNewChat = () => {
    setActiveConvId(null);
    setMessages([]);
    setError("");
    setShowHistory(false);
  };

  const handleDeleteConversation = async (convId, e) => {
    e.stopPropagation();
    try {
      await deleteConversation(convId);
      if (activeConvId === convId) {
        handleNewChat();
      }
      await loadConversations();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSend = async (promptText) => {
    const text = (promptText ?? input).trim();
    if (!text || streaming) return;

    setInput("");
    setError("");
    setStreaming(true);

    const tempUserId = `u-${Date.now()}`;
    const tempAsstId = `a-${Date.now() + 1}`;
    setMessages((prev) => [
      ...prev,
      { id: tempUserId, sender: "user", content: text },
      {
        id: tempAsstId,
        sender: "assistant",
        content: "",
        streaming: true,
        agents_invoked: [],
      },
    ]);

    try {
      let currentConvId = activeConvId;
      await streamAgentChat(
        {
          message: text,
          outlet_id: outletId,
          conversation_id: activeConvId,
        },
        {
          onMeta: (evt) => {
            if (evt.conversation_id) {
              currentConvId = evt.conversation_id;
              setActiveConvId(evt.conversation_id);
            }
          },
          onToken: (delta) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempAsstId
                  ? { ...m, content: `${m.content}${delta}` }
                  : m
              )
            );
          },
          onDone: (evt) => {
            if (evt.conversation_id) {
              currentConvId = evt.conversation_id;
              setActiveConvId(evt.conversation_id);
            }
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempAsstId
                  ? {
                      ...m,
                      id: evt.message_id || tempAsstId,
                      streaming: false,
                      ai_mode: evt.ai_mode,
                      fallback_reason: evt.fallback_reason,
                      agents_invoked: evt.agents_invoked || [],
                      suggested_items: evt.suggested_items || [],
                      substitutes: evt.substitutes || [],
                      fastest_outlet: evt.fastest_outlet || null,
                      lifecycle: evt.agentic_lifecycle || null,
                    }
                  : m
              )
            );
            if (onDataChanged) onDataChanged();
          },
        }
      );
      if (currentConvId) {
        await loadConversations();
      }
    } catch (streamErr) {
      // Fallback to non-streaming /api/agents/chat before surfacing error
      try {
        const res = await chatWithOrchestrator({
          message: text,
          outlet_id: outletId,
          conversation_id: activeConvId,
        });
        if (res.conversation_id) {
          setActiveConvId(res.conversation_id);
        }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tempAsstId
              ? {
                  ...m,
                  id: res.message_id || tempAsstId,
                  content: res.reply,
                  streaming: false,
                  ai_mode: res.ai_mode,
                  fallback_reason: res.fallback_reason,
                  agents_invoked: res.agents_invoked || [],
                  suggested_items: res.suggested_items || [],
                  substitutes: res.substitutes || [],
                  fastest_outlet: res.fastest_outlet || null,
                  lifecycle: res.agentic_lifecycle || null,
                }
              : m
          )
        );
        await loadConversations();
        if (onDataChanged) onDataChanged();
      } catch (err) {
        setMessages((prev) => prev.filter((m) => m.id !== tempAsstId));
        setError(err.message || streamErr.message || "AI assistant request failed.");
      }
    } finally {
      setStreaming(false);
    }
  };

  return (
    <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4">
      {/* Header with Title & Action Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-2xl bg-indigo-50 dark:bg-indigo-950 flex items-center justify-center text-indigo-600 dark:text-indigo-400">
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-extrabold text-slate-900 dark:text-white tracking-tight">
              Galley AI Copilot (Orchestrator Agent)
            </h3>
            <p className="text-[11px] text-slate-500">
              {authConfig?.ai_live_configured
                ? `Powered by Google Gemini (${authConfig.ai_provider}) with role-isolated database tools`
                : "Deterministic verification mode (real DB tools active)"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() => setShowHistory((s) => !s)}
            className="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-100 inline-flex items-center gap-1.5 transition"
          >
            <History className="w-3.5 h-3.5 text-indigo-500" />
            <span>Threads ({conversations.length})</span>
          </button>
          <button
            type="button"
            onClick={handleNewChat}
            className="px-3 py-1.5 rounded-xl bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 font-bold inline-flex items-center gap-1.5 transition"
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            <span>New Chat</span>
          </button>
        </div>
      </div>

      {/* History Drawer */}
      {showHistory && (
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 p-3.5 space-y-2 max-h-48 overflow-y-auto text-xs animate-in fade-in duration-200">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 px-1">
            Archived Discussions
          </div>
          {conversations.length === 0 ? (
            <div className="text-slate-400 py-2 text-center">No previous conversations yet.</div>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                onClick={() => handleSelectConversation(c.id)}
                className={`flex items-center justify-between gap-2 px-3 py-2 rounded-xl cursor-pointer transition ${
                  activeConvId === c.id
                    ? "bg-indigo-600 text-white font-semibold"
                    : "hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300"
                }`}
              >
                <span className="truncate">{c.title}</span>
                <button
                  type="button"
                  onClick={(e) => handleDeleteConversation(c.id, e)}
                  className="opacity-70 hover:opacity-100 p-1 shrink-0"
                  title="Delete conversation"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {/* Suggested Quick Prompt Pills */}
      <div className="flex flex-wrap gap-2">
        {quickPrompts.map((qp) => (
          <button
            key={qp}
            type="button"
            disabled={streaming}
            onClick={() => handleSend(qp)}
            className="text-[11px] font-medium px-3 py-1.5 rounded-xl bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:border-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition disabled:opacity-50"
          >
            {qp}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-2xl border border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 px-4 py-3 text-xs text-rose-800 dark:text-rose-200 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Multi-turn Chat Thread */}
      {messages.length > 0 && (
        <div className="space-y-4 max-h-[380px] overflow-y-auto pr-2 rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-950/60 p-4">
          {messages.map((m) => (
            <div
              key={m.id}
              className={`rounded-2xl p-4 text-xs space-y-2 shadow-xs transition ${
                m.sender === "user"
                  ? "bg-indigo-600 text-white ml-8 sm:ml-16 shadow-indigo-600/20"
                  : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-100 mr-4 sm:mr-12"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
                <span className={`font-bold uppercase tracking-wider ${m.sender === "user" ? "text-indigo-100" : "text-indigo-600 dark:text-indigo-400"}`}>
                  {m.sender === "user" ? user?.full_name || "You" : "Central Orchestrator"}
                </span>
                {m.sender === "assistant" && !m.streaming && m.ai_mode && (
                  <span
                    className={`px-2 py-0.5 rounded-full font-bold ${
                      m.ai_mode === "live_llm"
                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                        : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                    }`}
                  >
                    {m.ai_mode === "live_llm" ? "Live Gemini AI" : "Verified DB Mode"}
                  </span>
                )}
              </div>

              <div className="leading-relaxed whitespace-pre-wrap">
                {m.content || (m.streaming ? "Thinking and coordinating across database tools..." : "")}
              </div>

              {m.fallback_reason && (
                <div className="rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 px-3 py-2 text-[11px] text-amber-900 dark:text-amber-200">
                  <strong>Notice:</strong> {m.fallback_reason}
                </div>
              )}

              {onAddToCart && m.suggested_items?.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {m.suggested_items.map((it) => (
                    <button
                      key={it.id}
                      type="button"
                      onClick={() => onAddToCart(it)}
                      className="px-3 py-1.5 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-800 text-indigo-700 dark:text-indigo-300 font-bold hover:bg-indigo-100 inline-flex items-center gap-1.5 transition"
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>+ {it.name} (₹{it.price})</span>
                    </button>
                  ))}
                </div>
              )}

              {m.agents_invoked?.length > 0 && (
                <div className="pt-2 border-t border-slate-100 dark:border-slate-800 text-[10px] text-slate-400">
                  Agents invoked: <span className="font-semibold text-slate-700 dark:text-slate-300">{m.agents_invoked.join(" → ")}</span>
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Input Box */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
        className="flex gap-2"
      >
        <input
          type="text"
          placeholder="Ask for food recommendations, outlet prep time, stockouts, or analytics..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="flex-1 rounded-2xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-4 py-3 text-xs text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="px-5 py-3 rounded-2xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs transition shadow-md shadow-indigo-600/30 disabled:opacity-40 flex items-center gap-2 shrink-0"
        >
          <Send className="w-3.5 h-3.5" />
          <span>{streaming ? "Replying..." : "Ask Copilot"}</span>
        </button>
      </form>
    </section>
  );
}

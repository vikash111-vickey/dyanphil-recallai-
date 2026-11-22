import React, { useState, useEffect } from "react";
import { Key, X, Eye, EyeOff, Sparkles, Check, ExternalLink, ShieldCheck } from "lucide-react";
import { getStoredApiKey, saveApiKey } from "@/lib/webSearch";

interface ApiKeyModalProps {
  open: boolean;
  onClose: () => void;
  onSaved?: (key: string) => void;
}

export function ApiKeyModal({ open, onClose, onSaved }: ApiKeyModalProps) {
  const [keyInput, setKeyInput] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  useEffect(() => {
    if (open) {
      setKeyInput(getStoredApiKey());
      setSavedSuccess(false);
    }
  }, [open]);

  if (!open) return null;

  const handleSave = () => {
    saveApiKey(keyInput.trim());
    setSavedSuccess(true);
    if (onSaved) onSaved(keyInput.trim());
    setTimeout(() => {
      onClose();
    }, 1000);
  };

  const handleClear = () => {
    saveApiKey("");
    setKeyInput("");
    if (onSaved) onSaved("");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-950 p-6 shadow-2xl">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900 transition-colors"
          title="Close"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-indigo-500/30 text-indigo-400">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-zinc-100 text-base">Google Gemini AI Key</h3>
            <p className="text-xs text-zinc-400">For smart research paper analysis & answers</p>
          </div>
        </div>

        {/* Explanatory text */}
        <div className="space-y-2 mb-5 text-xs text-zinc-300 leading-relaxed bg-zinc-900/50 p-3.5 rounded-xl border border-zinc-800/60">
          <p>
            Add your Google Gemini API key to enable <strong>AI-synthesized research summaries</strong> and deep academic answers.
          </p>
          <p className="text-zinc-400">
            <em>Without a key, Dyanphil will still search real arXiv papers and Wikipedia encyclopedia articles completely free!</em>
          </p>
        </div>

        {/* Input */}
        <div className="mb-4">
          <label className="block text-xs font-medium text-zinc-300 mb-1.5">
            Gemini API Key
          </label>
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="AIzaSy..."
              className="w-full rounded-xl border border-zinc-800 bg-zinc-900/90 px-3.5 py-2.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-indigo-500/80 pr-10 font-mono"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
              title={showKey ? "Hide key" : "Show key"}
            >
              {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* Free key link */}
        <div className="mb-6 flex items-center justify-between text-[11px] text-zinc-400">
          <a
            href="https://aistudio.google.com/app/apikey"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-indigo-400 hover:underline"
          >
            <span>Get a free Gemini API key</span>
            <ExternalLink className="w-3 h-3" />
          </a>

          <div className="flex items-center gap-1 text-emerald-400/90">
            <ShieldCheck className="w-3 h-3" />
            <span>Saved in browser only</span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between gap-3">
          {keyInput ? (
            <button
              type="button"
              onClick={handleClear}
              className="text-xs text-rose-400 hover:text-rose-300 px-2 py-1.5 transition-colors"
            >
              Remove key
            </button>
          ) : (
            <div />
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs font-medium text-zinc-300 hover:bg-zinc-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white px-4 py-2 text-xs font-semibold shadow-md transition-all active:scale-95"
            >
              {savedSuccess ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-300" />
                  <span>Saved!</span>
                </>
              ) : (
                <>
                  <Key className="w-3.5 h-3.5" />
                  <span>Save API Key</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

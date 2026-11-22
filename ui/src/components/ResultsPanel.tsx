import React, { useState } from "react";
import {
  FileText,
  FolderOpen,
  Copy,
  Check,
  AlertCircle,
  Clock,
  ExternalLink,
  Shield,
  Download,
  Globe,
} from "lucide-react";
import { maskSensitiveData } from "@/lib/masking";

export interface FactItem {
  kind: string;
  label: string;
  value: string;
  value_date?: string | null;
}

export interface SearchResultItem {
  filename: string;
  path: string;
  breadcrumb: string[];
  source: string;
  modified: string;
  snippet: string;
  match_type: string;
  exists: boolean;
  doc_type?: string;
  facts?: FactItem[];
  url?: string;
  pdf_url?: string;
}

export interface AskResponse {
  tone: string;
  urgency: string;
  message: string;
  results: SearchResultItem[];
  session_id?: string;
}

interface ResultsPanelProps {
  data: AskResponse;
  onPinToVault?: (item: SearchResultItem) => void;
}

async function copyToClipboard(text: string): Promise<boolean> {
  // 1. Modern navigator.clipboard in secure contexts
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to textarea fallback
    }
  }

  // 2. Cross-browser fallback using temporary textarea
  try {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-999999px";
    textArea.style.top = "-999999px";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand("copy");
    document.body.removeChild(textArea);
    return successful;
  } catch (err) {
    console.error("Fallback clipboard copy failed:", err);
    return false;
  }
}

function renderSnippet(snippet: string) {
  if (!snippet) return null;
  const safeSnippet = maskSensitiveData(snippet);
  if (!safeSnippet.includes(">>>") || !safeSnippet.includes("<<<")) {
    return <span>{safeSnippet}</span>;
  }
  const parts = safeSnippet.split(/(>>>.*?<<<)/g);
  return (
    <span>
      {parts.map((part, idx) => {
        if (part.startsWith(">>>") && part.endsWith("<<<")) {
          const matchText = part.slice(3, -3);
          return (
            <mark
              key={idx}
              className="bg-emerald-500/25 text-emerald-300 px-1 py-0.5 rounded font-medium"
            >
              {matchText}
            </mark>
          );
        }
        return <span key={idx}>{part}</span>;
      })}
    </span>
  );
}

function formatFactChip(fact: FactItem): string {
  const lbl = (fact.label || "").trim();
  const val = maskSensitiveData((fact.value || "").trim());
  const lowerLbl = lbl.toLowerCase();
  const lowerKind = (fact.kind || "").toLowerCase();

  // e.g. "Expires 14 Aug 2026"
  if (lowerKind === "expiry" || lowerLbl.includes("expir") || lowerLbl.includes("valid")) {
    if (val.toLowerCase().startsWith("expir")) {
      return val;
    }
    return `Expires ${val}`;
  }
  if (lowerKind === "due_date" || lowerLbl.includes("due")) {
    return `Due ${val}`;
  }
  if (lowerLbl.includes("birth") || lowerLbl.includes("dob")) {
    return `DOB ${val}`;
  }
  if (lowerLbl.includes("issue")) {
    return `Issued ${val}`;
  }
  if (lbl) {
    return `${lbl}: ${val}`;
  }
  return val;
}

function ResultCard({
  item,
  onShowToast,
  onPinToVault,
}: {
  item: SearchResultItem;
  onShowToast: (msg: string) => void;
  onPinToVault?: (item: SearchResultItem) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [openingFile, setOpeningFile] = useState(false);
  const [openingFolder, setOpeningFolder] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const isWebMode =
    typeof window !== "undefined" &&
    window.location.hostname !== "127.0.0.1" &&
    window.location.hostname !== "localhost";

  const handleOpenFile = async () => {
    if (isWebMode) {
      onShowToast("To open files on your laptop desktop, switch to your local app at http://127.0.0.1:8000 (see button at top)!");
      return;
    }

    if (!item.exists) {
      onShowToast(`File no longer exists on disk: ${item.filename}`);
      return;
    }
    setOpeningFile(true);
    setActionError(null);
    try {
      const res = await fetch("/open", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: item.path, folder: false }),
      });
      const data = await res.json().catch(() => ({}));
      if (!data.ok) {
        const msg = data.message || data.error || `Failed to open (${res.status})`;
        setActionError(msg);
        onShowToast(msg);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setActionError(msg);
      onShowToast(msg);
    } finally {
      setOpeningFile(false);
    }
  };

  const handleOpenFolder = async () => {
    if (isWebMode) {
      onShowToast("To open Windows File Explorer on your laptop, switch to your local app at http://127.0.0.1:8000 (see button at top)!");
      return;
    }

    if (!item.exists) {
      onShowToast(`File no longer exists on disk: ${item.filename}`);
      return;
    }
    setOpeningFolder(true);
    setActionError(null);
    try {
      const res = await fetch("/open", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: item.path, folder: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (!data.ok) {
        const msg = data.message || data.error || `Failed to open folder (${res.status})`;
        setActionError(msg);
        onShowToast(msg);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setActionError(msg);
      onShowToast(msg);
    } finally {
      setOpeningFolder(false);
    }
  };

  const handleCopyPath = async () => {
    if (!item.exists) return;
    const ok = await copyToClipboard(item.path);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } else {
      const msg = "Failed to copy path to clipboard.";
      setActionError(msg);
      onShowToast(msg);
      setTimeout(() => setActionError(null), 4000);
    }
  };

  const getBadgeStyle = (matchType: string) => {
    switch (matchType?.toLowerCase()) {
      case "both":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
      case "meaning":
      case "vector":
        return "bg-indigo-500/10 text-indigo-400 border-indigo-500/30";
      case "exact":
      case "fts":
        return "bg-cyan-500/10 text-cyan-400 border-cyan-500/30";
      case "expiring":
        return "bg-amber-500/10 text-amber-400 border-amber-500/30";
      case "expired":
        return "bg-rose-500/10 text-rose-400 border-rose-500/30";
      case "research":
        return "bg-blue-500/15 text-blue-300 border-blue-500/40";
      case "ieee":
        return "bg-sky-500/20 text-sky-300 border-sky-500/50 font-semibold";
      case "knowledge":
        return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
      default:
        return "bg-zinc-800 text-zinc-300 border-zinc-700";
    }
  };

  const breadcrumbText = item.breadcrumb?.length
    ? item.breadcrumb.join(" > ")
    : item.path;

  return (
    <div className="group relative rounded-xl border border-white/10 bg-zinc-900/70 p-5 backdrop-blur-md transition-all duration-200 hover:border-emerald-500/30 hover:bg-zinc-900/90 hover:shadow-[0_8px_30px_rgba(0,0,0,0.5)]">
      {/* Top row: Filename, match type badge, exists warning */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/5 border border-white/10 text-emerald-400">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="break-words font-medium text-zinc-100 text-base" title={item.filename}>
              {item.filename}
            </h3>
            {/* Breadcrumb path */}
            <p className="mt-0.5 text-xs text-zinc-400 font-mono tracking-tight break-all">
              {breadcrumbText}
            </p>
          </div>
        </div>

        {/* Badges */}
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {item.doc_type && (
            <span className="rounded-full border border-purple-500/30 bg-purple-500/10 px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-wider text-purple-300">
              {item.doc_type.replace(/_/g, " ")}
            </span>
          )}
          {item.exists ? (
            <span
              className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-wider ${getBadgeStyle(
                item.match_type
              )}`}
            >
              {item.match_type}
            </span>
          ) : (
            <span className="flex items-center gap-1 rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-0.5 text-[11px] font-medium text-rose-400">
              <AlertCircle className="h-3 w-3" />
              File moved or deleted
            </span>
          )}
        </div>
      </div>

      {/* Snippet */}
      {item.snippet && (
        <div className="mt-3.5 rounded-lg border border-white/5 bg-black/40 p-3 text-xs leading-relaxed text-zinc-300">
          {renderSnippet(item.snippet)}
        </div>
      )}

      {/* Key Facts (up to 3) */}
      {item.facts && item.facts.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.facts.slice(0, 3).map((fact, idx) => (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span>{formatFactChip(fact)}</span>
            </span>
          ))}
        </div>
      )}

      {/* Footer: Modified date & action buttons */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-3">
        <div className="flex items-center gap-1.5 text-xs text-zinc-500">
          <Clock className="h-3.5 w-3.5" />
          <span>Modified: {item.modified}</span>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {item.url || item.pdf_url ? (
            <>
              {item.url && (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                    item.source === "IEEE Xplore" || item.match_type === "ieee"
                      ? "border-sky-500/50 bg-sky-500/15 text-sky-200 hover:bg-sky-500/30 hover:text-white"
                      : "border-blue-500/40 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 hover:text-white"
                  }`}
                  title="Open paper or publication in web browser"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  <span>
                    {item.source === "IEEE Xplore" || item.match_type === "ieee"
                      ? "Open in IEEE Xplore"
                      : "Read online"}
                  </span>
                </a>
              )}
              {item.pdf_url && (
                <a
                  href={item.pdf_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 hover:text-white"
                  title="Directly download and view PDF research paper"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Download PDF</span>
                </a>
              )}
              <button
                type="button"
                onClick={async () => {
                  const link = item.pdf_url || item.url || item.path;
                  const ok = await copyToClipboard(link);
                  if (ok) {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }
                }}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-white"
                title="Copy link"
              >
                {copied ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="text-emerald-400">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    <span>Copy link</span>
                  </>
                )}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={handleOpenFile}
                disabled={!item.exists || openingFile}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                title="Open file with default program"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                <span>{openingFile ? "Opening..." : "Open file"}</span>
              </button>

              <button
                type="button"
                onClick={handleOpenFolder}
                disabled={!item.exists || openingFolder}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                title="Reveal file in File Explorer"
              >
                <FolderOpen className="h-3.5 w-3.5" />
                <span>{openingFolder ? "Opening..." : "Open folder"}</span>
              </button>

              <button
                type="button"
                onClick={handleCopyPath}
                disabled={!item.exists}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                title="Copy path to clipboard"
              >
                {copied ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="text-emerald-400">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    <span>Copy path</span>
                  </>
                )}
              </button>

              {onPinToVault && (
                <button
                  type="button"
                  onClick={() => onPinToVault(item)}
                  disabled={!item.exists}
                  className="flex items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs font-medium text-purple-300 transition-colors hover:border-purple-500/50 hover:bg-purple-500/20 hover:text-purple-200 disabled:cursor-not-allowed disabled:opacity-40"
                  title="Pin document to Emergency Vault"
                >
                  <Shield className="h-3.5 w-3.5" />
                  <span>Pin to Vault</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {actionError && (
        <div className="mt-2.5 flex items-center gap-1.5 rounded-md border border-rose-500/20 bg-rose-500/10 px-2.5 py-1 text-xs text-rose-400">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span>{actionError}</span>
        </div>
      )}
    </div>
  );
}

export function ResultsPanel({ data, onPinToVault }: ResultsPanelProps) {
  const [toast, setToast] = useState<{ id: number; message: string } | null>(null);

  const showToast = (message: string) => {
    const id = Date.now();
    setToast({ id, message });
    setTimeout(() => {
      setToast((curr) => (curr?.id === id ? null : curr));
    }, 4500);
  };

  if (!data.results || data.results.length === 0) {
    return (
      <div className="w-full rounded-2xl border border-white/10 bg-zinc-900/50 p-8 text-center backdrop-blur-md">
        <p className="text-sm text-zinc-400">
          {data.message || "No matching documents found on your machine."}
        </p>
      </div>
    );
  }

  const hasIeeeOrResearch = data.results.some(
    (it) => it.source === "IEEE Xplore" || it.match_type === "ieee" || it.doc_type === "ieee_paper" || it.doc_type === "research_paper"
  );

  return (
    <div className="w-full space-y-3.5 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* IEEE Xplore & Research Library Bar */}
      {hasIeeeOrResearch && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-xl border border-sky-500/30 bg-gradient-to-r from-sky-950/50 via-zinc-950 to-zinc-950 text-xs text-sky-200 shadow-md">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-sky-400 shrink-0" />
            <span>
              Scholarly publications retrieved from <strong>IEEE Xplore</strong>, <strong>arXiv</strong>, and academic journals.
            </span>
          </div>
          <a
            href="https://ieeexplore.ieee.org/Xplore/home.jsp"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white px-3 py-1.5 text-xs font-semibold shadow-sm transition-all active:scale-95 shrink-0"
            title="Open IEEE Xplore Digital Library home"
          >
            <span>IEEE Xplore Home</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      )}

      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Results ({data.results.length})
        </span>
        <span className="text-xs text-zinc-500 font-mono">
          Tone: {data.tone} • Urgency: {data.urgency}
        </span>
      </div>

      <div className="grid gap-3.5">
        {data.results.map((item, idx) => (
          <ResultCard
            key={item.path || idx}
            item={item}
            onShowToast={showToast}
            onPinToVault={onPinToVault}
          />
        ))}
      </div>

      {/* Floating Toast Notification */}
      {toast && (
        <div
          role="alert"
          className="fixed bottom-6 right-6 z-50 flex max-w-md items-center gap-2.5 rounded-xl border border-rose-500/40 bg-zinc-950/95 px-4 py-3 text-xs text-rose-200 shadow-2xl backdrop-blur-md transition-all duration-300 animate-in fade-in slide-in-from-bottom-2"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
          <span className="flex-1 font-medium">{toast.message}</span>
          <button
            type="button"
            onClick={() => setToast(null)}
            className="ml-2 text-zinc-400 hover:text-white"
            aria-label="Dismiss toast"
          >
            &times;
          </button>
        </div>
      )}
    </div>
  );
}

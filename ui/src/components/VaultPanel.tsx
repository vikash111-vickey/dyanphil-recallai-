import React, { useState, useEffect } from "react";
import {
  Shield,
  FileText,
  FolderOpen,
  Copy,
  Check,
  AlertCircle,
  ExternalLink,
  Trash2,
  Lock,
  X,
  Sparkles,
  Pin,
  Clock,
} from "lucide-react";
import { FactItem } from "./ResultsPanel";

export interface VaultItem {
  id: number;
  file_id: number;
  label: string;
  filename: string;
  path: string;
  breadcrumb: string[];
  doc_type: string;
  exists: boolean;
  created_at: number;
  modified: string;
  facts: FactItem[];
}

export interface SuggestionItem {
  file_id: number;
  filename: string;
  path: string;
  breadcrumb: string[];
  doc_type: string;
  doc_type_score: number;
  modified: string;
  exists: boolean;
  facts: FactItem[];
}

interface VaultPanelProps {
  token: string;
  onClose: () => void;
  onLock: () => void;
  onShowToast: (msg: string) => void;
}

async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fallback below
    }
  }
  try {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-999999px";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand("copy");
    document.body.removeChild(textArea);
    return successful;
  } catch {
    return false;
  }
}

function formatFactChip(fact: FactItem): string {
  const lbl = (fact.label || "").trim();
  const val = (fact.value || "").trim();
  const lowerLbl = lbl.toLowerCase();
  const lowerKind = (fact.kind || "").toLowerCase();

  if (lowerKind === "expiry" || lowerLbl.includes("expir") || lowerLbl.includes("valid")) {
    if (val.toLowerCase().startsWith("expir")) return val;
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

export function VaultPanel({ token, onClose, onLock, onShowToast }: VaultPanelProps) {
  const [vaultItems, setVaultItems] = useState<VaultItem[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [openingId, setOpeningId] = useState<number | null>(null);
  const [openingFolderId, setOpeningFolderId] = useState<number | null>(null);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const [unpinningId, setUnpinningId] = useState<number | null>(null);
  const [pinningPath, setPinningPath] = useState<string | null>(null);

  const fetchVaultData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [vaultRes, suggRes] = await Promise.all([
        fetch("/vault", {
          credentials: "same-origin",
          headers: { "X-Vault-Token": token },
        }),
        fetch("/vault/suggestions", {
          credentials: "same-origin",
          headers: { "X-Vault-Token": token },
        }),
      ]);

      if (vaultRes.status === 401 || suggRes.status === 401) {
        onShowToast("Vault session expired. Please unlock again.");
        onLock();
        return;
      }

      if (!vaultRes.ok) {
        throw new Error(`Failed to load vault items (${vaultRes.status})`);
      }

      const vaultData: VaultItem[] = await vaultRes.json();
      const suggData: SuggestionItem[] = suggRes.ok ? await suggRes.json() : [];

      setVaultItems(vaultData);
      setSuggestions(suggData);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVaultData();
  }, [token]);

  const handleOpenFile = async (item: VaultItem) => {
    if (!item.exists) {
      onShowToast(`File moved or deleted: ${item.filename}`);
      return;
    }
    setOpeningId(item.id);
    try {
      const res = await fetch("/open", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: item.path, folder: false }),
      });
      const data = await res.json().catch(() => ({}));
      if (!data.ok) {
        onShowToast(data.message || "Failed to open file.");
      }
    } catch (err: unknown) {
      onShowToast(err instanceof Error ? err.message : "Failed to open file.");
    } finally {
      setOpeningId(null);
    }
  };

  const handleOpenFolder = async (item: VaultItem) => {
    if (!item.exists) {
      onShowToast(`File moved or deleted: ${item.filename}`);
      return;
    }
    setOpeningFolderId(item.id);
    try {
      const res = await fetch("/open", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: item.path, folder: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (!data.ok) {
        onShowToast(data.message || "Failed to open folder.");
      }
    } catch (err: unknown) {
      onShowToast(err instanceof Error ? err.message : "Failed to open folder.");
    } finally {
      setOpeningFolderId(null);
    }
  };

  const handleCopyPath = async (path: string) => {
    const ok = await copyToClipboard(path);
    if (ok) {
      setCopiedPath(path);
      setTimeout(() => setCopiedPath(null), 2000);
    } else {
      onShowToast("Failed to copy path.");
    }
  };

  const handleUnpin = async (vaultId: number, filename: string) => {
    setUnpinningId(vaultId);
    try {
      const res = await fetch(`/vault/${vaultId}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-Vault-Token": token },
      });
      if (res.status === 401) {
        onShowToast("Vault session expired.");
        onLock();
        return;
      }
      if (!res.ok) {
        throw new Error("Failed to unpin document.");
      }
      onShowToast(`Unpinned ${filename} from Vault.`);
      await fetchVaultData();
    } catch (err: unknown) {
      onShowToast(err instanceof Error ? err.message : "Error unpinning file.");
    } finally {
      setUnpinningId(null);
    }
  };

  const handlePinSuggestion = async (sugg: SuggestionItem) => {
    setPinningPath(sugg.path);
    try {
      const res = await fetch("/vault/pin", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-Vault-Token": token,
        },
        body: JSON.stringify({ path: sugg.path, label: sugg.filename }),
      });
      if (res.status === 401) {
        onShowToast("Vault session expired.");
        onLock();
        return;
      }
      if (!res.ok) {
        throw new Error("Failed to pin document.");
      }
      onShowToast(`Pinned ${sugg.filename} to Emergency Vault!`);
      await fetchVaultData();
    } catch (err: unknown) {
      onShowToast(err instanceof Error ? err.message : "Error pinning file.");
    } finally {
      setPinningPath(null);
    }
  };

  return (
    <div className="w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-zinc-950/90 p-5 shadow-xl backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-purple-500/40 bg-purple-500/10 text-purple-400 shadow-[0_0_20px_rgba(168,85,247,0.2)]">
            <Shield className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-zinc-100">Emergency Vault</h2>
              <span className="flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Unlocked
              </span>
            </div>
            <p className="mt-0.5 text-xs text-zinc-400">
              Quick access offline repository for your essential identification, medical, insurance, and warranty documents.
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onLock}
            className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-amber-500/40 hover:bg-amber-500/10 hover:text-amber-300"
            title="Lock Vault now"
          >
            <Lock className="h-3.5 w-3.5" />
            <span>Lock Vault</span>
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-white/10 bg-white/5 p-1.5 text-zinc-400 transition-colors hover:bg-white/10 hover:text-white"
            title="Close Vault panel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-300">
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Pinned Documents Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
              Pinned Documents ({vaultItems.length})
            </h3>
          </div>
          <span className="text-xs text-zinc-500">
            Prioritized first during emergency queries
          </span>
        </div>

        {loading ? (
          <div className="rounded-xl border border-white/10 bg-zinc-900/40 p-8 text-center text-xs text-zinc-400 backdrop-blur-md">
            Loading vault documents...
          </div>
        ) : vaultItems.length === 0 ? (
          <div className="rounded-xl border border-white/10 bg-zinc-900/40 p-8 text-center text-xs text-zinc-400 backdrop-blur-md">
            Your Emergency Vault is currently empty. Pin your critical documents below from Suggestions or search results.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3.5">
            {vaultItems.map((item) => {
              const breadcrumbText = item.breadcrumb?.length
                ? item.breadcrumb.join(" > ")
                : item.path;

              return (
                <div
                  key={item.id}
                  className="group relative rounded-xl border border-purple-500/20 bg-zinc-900/70 p-5 backdrop-blur-md transition-all duration-200 hover:border-purple-500/40 hover:bg-zinc-900/90 hover:shadow-[0_8px_30px_rgba(0,0,0,0.5)]"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-purple-500/30 bg-purple-500/10 text-purple-400">
                        <FileText className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <h4 className="truncate font-medium text-zinc-100 text-base" title={item.filename}>
                          {item.label || item.filename}
                        </h4>
                        <p className="mt-0.5 text-xs text-zinc-400 font-mono tracking-tight break-all">
                          {breadcrumbText}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {item.doc_type && (
                        <span className="rounded-full border border-purple-500/30 bg-purple-500/10 px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-wider text-purple-300">
                          {item.doc_type.replace(/_/g, " ")}
                        </span>
                      )}
                      {!item.exists && (
                        <span className="flex items-center gap-1 rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-0.5 text-[11px] font-medium text-rose-400">
                          <AlertCircle className="h-3 w-3" />
                          File moved or deleted
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Facts Chips */}
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

                  {/* Actions Footer */}
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-3">
                    <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                      <Clock className="h-3.5 w-3.5" />
                      <span>Modified: {item.modified || "Unknown"}</span>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleOpenFile(item)}
                        disabled={!item.exists || openingId === item.id}
                        className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                        title="Open file"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        <span>{openingId === item.id ? "Opening..." : "Open file"}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleOpenFolder(item)}
                        disabled={!item.exists || openingFolderId === item.id}
                        className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                        title="Reveal in folder"
                      >
                        <FolderOpen className="h-3.5 w-3.5" />
                        <span>{openingFolderId === item.id ? "Opening..." : "Open folder"}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleCopyPath(item.path)}
                        disabled={!item.exists}
                        className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                        title="Copy path"
                      >
                        {copiedPath === item.path ? (
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

                      <button
                        type="button"
                        onClick={() => handleUnpin(item.id, item.filename)}
                        disabled={unpinningId === item.id}
                        className="flex items-center gap-1.5 rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:border-rose-500/40 hover:bg-rose-500/20 hover:text-rose-200 disabled:cursor-not-allowed disabled:opacity-40"
                        title="Unpin from vault"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        <span>{unpinningId === item.id ? "Unpinning..." : "Unpin"}</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Suggested Documents Section */}
      {suggestions.length > 0 && (
        <div className="space-y-3 border-t border-white/10 pt-6">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-purple-400" />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
                Suggested for Vault ({suggestions.length})
              </h3>
            </div>
            <span className="text-xs text-zinc-500">
              Identified IDs, insurance, medical records & warranties
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            {suggestions.map((sugg) => {
              const breadcrumbText = sugg.breadcrumb?.length
                ? sugg.breadcrumb.join(" > ")
                : sugg.path;

              return (
                <div
                  key={sugg.file_id}
                  className="group relative flex flex-col justify-between rounded-xl border border-white/10 bg-zinc-900/50 p-4 backdrop-blur-md transition-all duration-200 hover:border-white/20 hover:bg-zinc-900/80"
                >
                  <div>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h4 className="truncate font-medium text-zinc-100 text-sm" title={sugg.filename}>
                          {sugg.filename}
                        </h4>
                        <p className="mt-0.5 text-[11px] text-zinc-400 font-mono tracking-tight truncate">
                          {breadcrumbText}
                        </p>
                      </div>
                      <span className="shrink-0 rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-purple-300">
                        {sugg.doc_type.replace(/_/g, " ")}
                      </span>
                    </div>

                    {sugg.facts && sugg.facts.length > 0 && (
                      <div className="mt-2.5 flex flex-wrap gap-1.5">
                        {sugg.facts.slice(0, 2).map((fact, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center gap-1 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300"
                          >
                            <span className="h-1 w-1 rounded-full bg-emerald-400" />
                            <span>{formatFactChip(fact)}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="mt-3.5 flex items-center justify-between border-t border-white/5 pt-2.5">
                    {!sugg.exists ? (
                      <span className="text-[11px] text-rose-400">File moved or deleted</span>
                    ) : (
                      <span className="text-[11px] text-zinc-500 font-mono">
                        {sugg.modified ? `Modified: ${sugg.modified.split(" ")[0]}` : ""}
                      </span>
                    )}

                    <button
                      type="button"
                      onClick={() => handlePinSuggestion(sugg)}
                      disabled={pinningPath === sugg.path || !sugg.exists}
                      className="flex items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 px-2.5 py-1 text-xs font-medium text-purple-300 transition-colors hover:border-purple-500/50 hover:bg-purple-500/20 hover:text-purple-200 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <Pin className="h-3 w-3" />
                      <span>{pinningPath === sugg.path ? "Pinning..." : "Pin"}</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

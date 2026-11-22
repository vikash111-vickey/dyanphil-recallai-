import React, { useState, useRef, useEffect } from "react";
import { Clock, Shield, AlertCircle, X, Settings, ShieldCheck, Lock, ExternalLink, HardDrive, Globe, Key, Sparkles } from "lucide-react";
import MorphOrb from "@/components/ui/ai-thiking-orb-and-input";
import { ResultsPanel, AskResponse, SearchResultItem } from "@/components/ResultsPanel";
import { VaultPinModal } from "@/components/VaultPinModal";
import { VaultPanel } from "@/components/VaultPanel";
import { SettingsPanel } from "@/components/SettingsPanel";
import { PermissionModal } from "@/components/PermissionModal";
import { ApiKeyModal } from "@/components/ApiKeyModal";
import { performClientSearch, SAMPLE_DOCUMENTS } from "@/lib/webFallback";
import { performInternetSearch, getStoredApiKey } from "@/lib/webSearch";
import { getLocalFolderState, LocalFolderState } from "@/lib/localFileScanner";

interface ExpiringItem {
  fact_id: number;
  file_id: number;
  kind: string;
  label: string;
  value: string;
  value_date: string;
  snippet?: string;
  filename: string;
  path: string;
  doc_type?: string;
  days_remaining: number;
  is_expired: boolean;
}

export default function App() {
  // Session ID generated ONCE per page load to enable follow-up commands ("open it", "kholo", etc.)
  const [sessionId] = useState<string>(() => {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return "sess_" + Math.random().toString(36).substring(2, 12) + "_" + Date.now();
  });

  // Vault token kept IN MEMORY ONLY (React state), never in localStorage
  const [vaultToken, setVaultToken] = useState<string | null>(null);
  const [showVaultPanel, setShowVaultPanel] = useState(false);
  const [showSettingsPanel, setShowSettingsPanel] = useState(false);
  const [showPinModal, setShowPinModal] = useState(false);
  const [openVaultAfterUnlock, setOpenVaultAfterUnlock] = useState(false);
  const [pendingPinItem, setPendingPinItem] = useState<SearchResultItem | null>(null);

  // Local laptop folder permission state (for privacy & safety)
  const [showPermissionModal, setShowPermissionModal] = useState(false);
  const [localFolderState, setLocalFolderState] = useState<LocalFolderState>(getLocalFolderState);

  // Search mode: "internet" (search arXiv papers & web info) vs "laptop" (search local computer files)
  const isWebMode =
    typeof window !== "undefined" &&
    window.location.hostname !== "127.0.0.1" &&
    window.location.hostname !== "localhost";
  const [searchMode, setSearchMode] = useState<"internet" | "laptop">(() => (isWebMode ? "internet" : "laptop"));
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);
  const [hasApiKey, setHasApiKey] = useState<boolean>(() => Boolean(getStoredApiKey()));

  const [askData, setAskData] = useState<AskResponse | null>(null);
  const [showResults, setShowResults] = useState(false);
  const [currentPhase, setCurrentPhase] = useState<string>("idle");
  const [loadingExpiring, setLoadingExpiring] = useState(false);
  const [toast, setToast] = useState<{ id: number; message: string } | null>(null);

  const orbContainerRef = useRef<HTMLDivElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const vaultRef = useRef<HTMLDivElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);

  const showToast = (message: string) => {
    const id = Date.now();
    setToast({ id, message });
    setTimeout(() => {
      setToast((curr) => (curr?.id === id ? null : curr));
    }, 4500);
  };

  const handleAsk = async (text: string): Promise<string> => {
    setShowVaultPanel(false);
    setShowSettingsPanel(false);

    // MODE 1: Internet Browser & Research Papers Mode
    if (searchMode === "internet") {
      try {
        const internetData = await performInternetSearch(text, sessionId);
        setAskData(internetData);
        setShowResults(true);
        setTimeout(() => {
          resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 1400);
        return internetData.message;
      } catch (err) {
        console.warn("Internet research search error:", err);
      }
    }

    // MODE 2: Laptop Files Mode (only if laptop mode is chosen)
    // 1. Detect if connected to local Python backend (127.0.0.1 or localhost)
    const isLocalBackend =
      (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost") &&
      (window.location.port === "8000" || window.location.port === "5173");

    if (isLocalBackend) {
      try {
        const res = await fetch("/ask", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ message: text, session_id: sessionId }),
        });

        const contentType = res.headers.get("content-type") || "";
        if (res.ok && contentType.includes("application/json")) {
          const data: AskResponse = await res.json();
          setAskData(data);
          setShowResults(true);
          setTimeout(() => {
            resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 1400);
          return data.message || "Found matching documents.";
        }
      } catch (err) {
        console.warn("Local backend fetch failed, using client search:", err);
      }
    }

    // 2. On Web / PWA (Firebase): On-device local search of user's laptop folder
    const fallbackData = performClientSearch(text, sessionId);
    setAskData(fallbackData);
    setShowResults(true);
    setTimeout(() => {
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 1400);
    return fallbackData.message;
  };

  const handleFetchExpiring = async () => {
    setShowVaultPanel(false);
    setShowSettingsPanel(false);
    setLoadingExpiring(true);
    try {
      const res = await fetch("/expiring?days=60", {
        credentials: "same-origin",
      });
      const contentType = res.headers.get("content-type") || "";
      if (res.ok && contentType.includes("application/json")) {
        const data: ExpiringItem[] = await res.json();

        // Group facts by file path so cards show up to 3 fact chips per document
        const mapByPath = new Map<string, SearchResultItem>();
        for (const it of data) {
          const filePath = it.path || it.filename;
          if (!mapByPath.has(filePath)) {
            const parts = filePath.split(/[/\\]/).filter(Boolean);
            mapByPath.set(filePath, {
              filename: it.filename,
              path: it.path,
              breadcrumb: parts.length > 0 ? parts : [it.filename],
              source: "local file",
              modified: it.value_date || "",
              snippet: it.snippet || "",
              match_type: it.is_expired ? "expired" : "expiring",
              exists: true,
              doc_type: it.doc_type || "other",
              facts: [],
            });
          }
          const entry = mapByPath.get(filePath)!;
          if (entry.facts && entry.facts.length < 3) {
            entry.facts.push({
              kind: it.kind,
              label: it.label,
              value: it.value,
              value_date: it.value_date,
            });
          }
          if (it.is_expired) {
            entry.match_type = "expired";
          }
        }

        const results = Array.from(mapByPath.values());
        const hasExpired = results.some((r) => r.match_type === "expired");
        const askResponse: AskResponse = {
          tone: "neutral",
          urgency: hasExpired ? "high" : "medium",
          message:
            results.length > 0
              ? `Found ${results.length} document${results.length === 1 ? "" : "s"} expiring soon or expired.`
              : "No documents expiring within the next 60 days.",
          results,
        };

        setAskData(askResponse);
        setShowResults(true);
      } else {
        // Fallback for static web mode
        const fallbackResults: SearchResultItem[] = [
          SAMPLE_DOCUMENTS[3], // BSES Electricity Bill due Nov 30
          SAMPLE_DOCUMENTS[2], // IndiGo Flight Ticket Dec 15
        ];
        const askResponse: AskResponse = {
          tone: "neutral",
          urgency: "medium",
          message: "Found 2 upcoming deadlines/events: BSES Electricity Bill due on Nov 30, and IndiGo Flight DEL → BOM on Dec 15.",
          session_id: sessionId,
          results: fallbackResults,
        };
        setAskData(askResponse);
        setShowResults(true);
      }

      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (err) {
      console.warn("Using expiring documents fallback:", err);
      const fallbackResults: SearchResultItem[] = [
        SAMPLE_DOCUMENTS[3],
        SAMPLE_DOCUMENTS[2],
      ];
      const askResponse: AskResponse = {
        tone: "neutral",
        urgency: "medium",
        message: "Found 2 upcoming deadlines/events: BSES Electricity Bill due on Nov 30, and IndiGo Flight DEL → BOM on Dec 15.",
        session_id: sessionId,
        results: fallbackResults,
      };
      setAskData(askResponse);
      setShowResults(true);
    } finally {
      setLoadingExpiring(false);
    }
  };

  const handleOpenVaultClick = () => {
    setShowSettingsPanel(false);
    if (vaultToken) {
      setShowVaultPanel(true);
      setShowResults(false);
      setTimeout(() => {
        vaultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } else {
      setOpenVaultAfterUnlock(true);
      setShowPinModal(true);
    }
  };

  const handleOpenSettingsClick = () => {
    setShowVaultPanel(false);
    setShowResults(false);
    setShowSettingsPanel((prev) => !prev);
    setTimeout(() => {
      settingsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  };

  const executePinFile = async (token: string, path: string, label: string) => {
    try {
      const res = await fetch("/vault/pin", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-Vault-Token": token,
        },
        body: JSON.stringify({ path, label }),
      });

      if (res.status === 401) {
        setVaultToken(null);
        showToast("Vault session expired. Please enter your PIN.");
        setPendingPinItem({ path, filename: label } as SearchResultItem);
        setShowPinModal(true);
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        showToast(data.detail || "Failed to pin file to Vault.");
        return;
      }

      showToast(`Pinned "${label}" to Emergency Vault!`);
    } catch (err) {
      showToast("Network error pinning file to Vault.");
    }
  };

  const handlePinFromResults = async (item: SearchResultItem) => {
    if (!vaultToken) {
      setPendingPinItem(item);
      setShowPinModal(true);
      return;
    }
    await executePinFile(vaultToken, item.path, item.filename);
  };

  const handleUnlockSuccess = async (token: string) => {
    setVaultToken(token);
    setShowPinModal(false);

    if (pendingPinItem) {
      const item = pendingPinItem;
      setPendingPinItem(null);
      await executePinFile(token, item.path, item.filename);
    } else if (openVaultAfterUnlock) {
      setOpenVaultAfterUnlock(false);
      setShowVaultPanel(true);
      setShowResults(false);
      setTimeout(() => {
        vaultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    }
  };

  const handleLockVault = () => {
    setVaultToken(null);
    setShowVaultPanel(false);
    showToast("Vault has been locked.");
  };

  // Observe the data-phase attribute on .mo-root
  useEffect(() => {
    const rootEl = orbContainerRef.current?.querySelector(".mo-root");
    if (!rootEl) return;

    const updatePhase = () => {
      const phase = rootEl.getAttribute("data-phase") || "idle";
      setCurrentPhase(phase);
      if (phase === "answered") {
        setShowResults(true);
        setShowVaultPanel(false);
      } else if (phase === "reset" || phase === "idle" || phase === "launch") {
        setShowResults(false);
      }
    };

    updatePhase();

    const observer = new MutationObserver(() => {
      updatePhase();
    });

    observer.observe(rootEl, {
      attributes: true,
      attributeFilter: ["data-phase"],
    });

    return () => observer.disconnect();
  }, []);

  // When user clicks "New question", hide results and scroll back to top
  const handleContainerClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest(".mo-reset") || target.closest(".mo-close")) {
      setAskData(null);
      setShowResults(false);
      setShowVaultPanel(false);
      setShowSettingsPanel(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  // Smoothly scroll to results when they appear
  useEffect(() => {
    if (showResults && resultsRef.current) {
      const timer = setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 350);
      return () => clearTimeout(timer);
    }
  }, [showResults]);

  const isOrbPillVisible =
    !currentPhase ||
    currentPhase === "idle" ||
    currentPhase === "reset" ||
    currentPhase === "answered";

  return (
    <div
      className="relative min-h-screen w-full bg-[#050508] text-[#f4f4f5] flex flex-col items-center selection:bg-emerald-500/30"
      onClick={handleContainerClick}
    >
      {/* Top Banner: Mode Selector & Laptop / API Key Actions */}
      <div className="w-full bg-gradient-to-r from-zinc-950 via-zinc-900 to-zinc-950 border-b border-zinc-800/80 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-200 z-50">
        {/* Left: Search Mode Toggle */}
        <div className="flex items-center gap-2">
          <div className="flex items-center p-0.5 rounded-xl border border-zinc-800 bg-zinc-950 shadow-inner">
            <button
              type="button"
              onClick={() => {
                setSearchMode("internet");
                showToast("Switched to Internet & Research Papers search mode.");
              }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                searchMode === "internet"
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900"
              }`}
              title="Search online research papers from arXiv, Wikipedia, and internet articles"
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Internet & Research</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setSearchMode("laptop");
                if (!localFolderState.granted && isWebMode) {
                  setShowPermissionModal(true);
                } else {
                  showToast("Switched to Laptop Files search mode.");
                }
              }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                searchMode === "laptop"
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900"
              }`}
              title="Search personal documents and files stored on your laptop"
            >
              <HardDrive className="w-3.5 h-3.5" />
              <span>My Laptop Files</span>
              {localFolderState.granted && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              )}
            </button>
          </div>

          <span className="hidden md:inline text-[11px] text-zinc-400">
            {searchMode === "internet"
              ? "🌐 Searching IEEE Xplore, arXiv & internet"
              : "💻 Searching files on your laptop"}
          </span>
        </div>

        {/* Right: API Key & Open on Laptop */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowApiKeyModal(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 px-3 py-1.5 font-medium text-xs transition-colors"
            title="Configure Google Gemini API Key for deep AI synthesis"
          >
            <Key className="w-3.5 h-3.5 text-indigo-400" />
            <span>{hasApiKey ? "AI Key Active ✓" : "Add Gemini API Key"}</span>
          </button>

          {isWebMode && (
            <a
              href="http://127.0.0.1:8000"
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-zinc-950 px-3 py-1.5 font-semibold text-xs shadow-md transition-all active:scale-95 shrink-0"
              title="Open native laptop app on http://127.0.0.1:8000"
            >
              <span>Open on Laptop</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          )}
        </div>
      </div>

      {/* Top Status Bar: In normal document flow so it never collides with top bar buttons */}
      <div className="w-full flex justify-center py-2 px-4 z-20">
        {searchMode === "laptop" ? (
          <button
            type="button"
            onClick={() => setShowPermissionModal(true)}
            className="flex items-center gap-2 rounded-full border border-zinc-800/80 bg-zinc-950/80 px-3.5 py-1.5 text-[11px] font-medium text-zinc-300 shadow-lg backdrop-blur-md transition-all hover:border-emerald-500/40 hover:bg-zinc-900 hover:text-emerald-300 active:scale-95"
            title="Manage local laptop folder permission"
          >
            {localFolderState.granted ? (
              <>
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>
                  Laptop Folder: <strong className="text-emerald-300 font-semibold">{localFolderState.folderName}</strong> ({localFolderState.fileCount} files) • 100% On-Device
                </span>
              </>
            ) : (
              <>
                <Lock className="w-3.5 h-3.5 text-amber-400" />
                <span>
                  Laptop File Access: <strong className="text-amber-300 underline underline-offset-2">Click to select laptop folder</strong> • 0% Cloud Upload
                </span>
              </>
            )}
          </button>
        ) : (
          <div className="flex items-center gap-2 rounded-full border border-blue-500/30 bg-zinc-950/80 px-3.5 py-1.5 text-[11px] font-medium text-zinc-300 shadow-lg backdrop-blur-md">
            <Globe className="w-3.5 h-3.5 text-blue-400" />
            <span>
              Internet Search Active • <strong className="text-blue-300">IEEE Xplore, arXiv & Online Knowledge</strong>
            </span>
          </div>
        )}
      </div>

      {/* MorphOrb Section */}
      <div ref={orbContainerRef} className="w-full relative">
        <MorphOrb onSubmit={handleAsk} minThinkMs={1200} />

        {/* Buttons positioned directly under the orb */}
        {isOrbPillVisible && (
          <div
            className={`pointer-events-none absolute left-1/2 -translate-x-1/2 z-30 flex items-center gap-2.5 transition-all duration-300 ${
              currentPhase === "answered"
                ? "top-[calc(46%+76px)]"
                : "top-[calc(46%-12px)]"
            }`}
          >
            {/* Expiring Soon Button */}
            <button
              type="button"
              onClick={handleFetchExpiring}
              disabled={loadingExpiring}
              className="pointer-events-auto group flex items-center gap-2 rounded-full border border-amber-500/25 bg-zinc-950/80 px-4 py-2 text-xs font-medium text-zinc-300 shadow-[0_4px_20px_rgba(0,0,0,0.5)] backdrop-blur-md transition-all duration-200 hover:border-amber-500/60 hover:bg-zinc-900 hover:text-amber-300 hover:shadow-[0_0_20px_rgba(245,158,11,0.25)] active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
              title="Check documents expiring within the next 60 days"
            >
              <Clock
                className={`h-3.5 w-3.5 text-amber-400 ${
                  loadingExpiring
                    ? "animate-spin"
                    : "transition-transform group-hover:scale-110"
                }`}
              />
              <span>
                {loadingExpiring ? "Checking expiring..." : "Expiring soon"}
              </span>
            </button>

            {/* Emergency Vault Button */}
            <button
              type="button"
              onClick={handleOpenVaultClick}
              className="pointer-events-auto group flex items-center gap-2 rounded-full border border-purple-500/25 bg-zinc-950/80 px-4 py-2 text-xs font-medium text-zinc-300 shadow-[0_4px_20px_rgba(0,0,0,0.5)] backdrop-blur-md transition-all duration-200 hover:border-purple-500/60 hover:bg-zinc-900 hover:text-purple-300 hover:shadow-[0_0_20px_rgba(168,85,247,0.25)] active:scale-95"
              title="Open Emergency Vault"
            >
              <Shield className="h-3.5 w-3.5 text-purple-400 transition-transform group-hover:scale-110" />
              <span>Vault</span>
              {vaultToken && (
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              )}
            </button>

            {/* Settings Button */}
            <button
              type="button"
              onClick={handleOpenSettingsClick}
              className={`pointer-events-auto group flex items-center gap-2 rounded-full border px-4 py-2 text-xs font-medium shadow-[0_4px_20px_rgba(0,0,0,0.5)] backdrop-blur-md transition-all duration-200 active:scale-95 ${
                showSettingsPanel
                  ? "border-sky-500/60 bg-zinc-900 text-sky-300 shadow-[0_0_20px_rgba(14,165,233,0.25)]"
                  : "border-sky-500/25 bg-zinc-950/80 text-zinc-300 hover:border-sky-500/60 hover:bg-zinc-900 hover:text-sky-300 hover:shadow-[0_0_20px_rgba(14,165,233,0.25)]"
              }`}
              title="Open Settings & Indexer"
            >
              <Settings className="h-3.5 w-3.5 text-sky-400 transition-transform group-hover:rotate-45" />
              <span>Settings</span>
            </button>
          </div>
        )}
      </div>

      {/* Settings Panel */}
      {showSettingsPanel && (
        <div ref={settingsRef} className="w-full max-w-3xl px-4 pb-24 z-20 pt-4">
          <SettingsPanel
            onClose={() => setShowSettingsPanel(false)}
            onShowToast={showToast}
          />
        </div>
      )}

      {/* Unlocked Vault Panel */}
      {showVaultPanel && vaultToken && (
        <div ref={vaultRef} className="w-full max-w-3xl px-4 pb-24 z-20 pt-4">
          <VaultPanel
            token={vaultToken}
            onClose={() => setShowVaultPanel(false)}
            onLock={handleLockVault}
            onShowToast={showToast}
          />
        </div>
      )}

      {/* ResultsPanel below the orb */}
      {askData && !showVaultPanel && !showSettingsPanel && (
        <div
          ref={resultsRef}
          className="w-full max-w-3xl px-4 pb-24 z-20 pt-4 animate-in fade-in duration-300"
        >
          <ResultsPanel
            data={askData}
            onPinToVault={handlePinFromResults}
          />
        </div>
      )}

      {/* PIN Setup / Unlock Modal */}
      <VaultPinModal
        isOpen={showPinModal}
        onClose={() => {
          setShowPinModal(false);
          setPendingPinItem(null);
          setOpenVaultAfterUnlock(false);
        }}
        onSuccess={handleUnlockSuccess}
        customMessage={
          pendingPinItem
            ? `Enter your PIN to securely pin "${pendingPinItem.filename}" to your Emergency Vault.`
            : undefined
        }
      />

      {/* Permission Modal for Local Laptop Files */}
      <PermissionModal
        isOpen={showPermissionModal}
        onClose={() => setShowPermissionModal(false)}
        onPermissionGranted={(folderName, count) => {
          const newState = getLocalFolderState();
          setLocalFolderState(newState);
          showToast(`Permission granted! Indexed ${count} file(s) from "${folderName}" locally on this laptop.`);
        }}
      />

      {/* Google Gemini API Key Modal */}
      <ApiKeyModal
        open={showApiKeyModal}
        onClose={() => setShowApiKeyModal(false)}
        onSaved={(key) => {
          setHasApiKey(Boolean(key));
          showToast(key ? "Google Gemini API key saved!" : "API key removed.");
        }}
      />

      {/* Floating Global Toast Notification */}
      {toast && (
        <div
          role="alert"
          className="fixed bottom-6 right-6 z-50 flex max-w-md items-center gap-2.5 rounded-xl border border-purple-500/30 bg-zinc-950/95 px-4 py-3 text-xs text-zinc-200 shadow-2xl backdrop-blur-md transition-all duration-300 animate-in fade-in slide-in-from-bottom-2"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-purple-400" />
          <span className="flex-1 font-medium">{toast.message}</span>
          <button
            type="button"
            onClick={() => setToast(null)}
            className="ml-2 text-zinc-400 hover:text-white"
            aria-label="Dismiss toast"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

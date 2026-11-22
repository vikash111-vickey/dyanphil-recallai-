import React, { useState, useEffect, useRef } from "react";
import {
  Settings,
  Folder,
  FolderPlus,
  Trash2,
  RefreshCw,
  FileScan,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  X,
  Loader2,
  Database,
  Clock,
  Shield,
  ShieldAlert,
  ShieldCheck,
  HardDrive,
  KeyRound,
  Lock,
  Image,
  FolderX,
} from "lucide-react";
import {
  getLocalFolderState,
  revokeLocalPermission,
  requestFolderPermissionAndScan,
  LocalFolderState,
} from "@/lib/localFileScanner";

export interface IndexStatus {
  running: boolean;
  current_task: string | null;
  files_total: number;
  by_status: Record<string, number>;
  last_run_time: string | null;
  pending_ocr_count: number;
}

export interface PrivacyInfo {
  data_folder: string;
  database_size: number;
  database_size_formatted: string;
  files_indexed: number;
  folders_count: number;
  folders: string[];
  vault_pin_set: boolean;
  embedding_model: string;
}

export interface DeleteAllResponse {
  ok: boolean;
  message: string;
  deleted: Record<string, number>;
}

interface SettingsPanelProps {
  onClose: () => void;
  onShowToast: (msg: string) => void;
}

export function SettingsPanel({ onClose, onShowToast }: SettingsPanelProps) {
  const [folders, setFolders] = useState<string[]>([]);
  const [newFolderPath, setNewFolderPath] = useState("");
  const [loadingFolders, setLoadingFolders] = useState(true);
  const [addingFolder, setAddingFolder] = useState(false);
  const [removingFolder, setRemovingFolder] = useState<string | null>(null);

  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [triggeringIndex, setTriggeringIndex] = useState(false);
  const [triggeringOcr, setTriggeringOcr] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Excluded Folders state
  const [excludedFolders, setExcludedFolders] = useState<string[]>([]);
  const [newExcludedPath, setNewExcludedPath] = useState("");
  const [loadingExcluded, setLoadingExcluded] = useState(true);
  const [addingExcluded, setAddingExcluded] = useState(false);
  const [removingExcluded, setRemovingExcluded] = useState<string | null>(null);
  const [excludedError, setExcludedError] = useState<string | null>(null);

  // Image Folders state
  const [imageFolders, setImageFolders] = useState<string[]>([]);
  const [newImagePath, setNewImagePath] = useState("");
  const [loadingImageFolders, setLoadingImageFolders] = useState(true);
  const [addingImageFolder, setAddingImageFolder] = useState(false);
  const [removingImageFolder, setRemovingImageFolder] = useState<string | null>(null);
  const [imageFolderError, setImageFolderError] = useState<string | null>(null);

  // Privacy state
  const [privacy, setPrivacy] = useState<PrivacyInfo | null>(null);
  const [loadingPrivacy, setLoadingPrivacy] = useState(true);

  // Delete All Data modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteConfirmInput, setDeleteConfirmInput] = useState("");
  const [deletePinInput, setDeletePinInput] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteResult, setDeleteResult] = useState<DeleteAllResponse | null>(null);

  const isMountedRef = useRef(true);

  const [localFolder, setLocalFolder] = useState<LocalFolderState>(getLocalFolderState);
  const [requestingPerm, setRequestingPerm] = useState(false);

  // Fetch configured folders
  const fetchFolders = async () => {
    try {
      const res = await fetch("/settings/folders", {
        credentials: "same-origin",
      });
      const ct = res.headers.get("content-type") || "";
      if (res.ok && ct.includes("application/json")) {
        const data = await res.json();
        if (isMountedRef.current) {
          setFolders(data.folders || []);
        }
      } else {
        // Web / PWA mode
        const localState = getLocalFolderState();
        if (isMountedRef.current) {
          setLocalFolder(localState);
          if (localState.granted && localState.folderName) {
            setFolders([`Laptop: ${localState.folderName}`]);
          } else {
            setFolders([]);
          }
        }
      }
    } catch {
      const localState = getLocalFolderState();
      if (isMountedRef.current) {
        setLocalFolder(localState);
        if (localState.granted && localState.folderName) {
          setFolders([`Laptop: ${localState.folderName}`]);
        }
      }
    } finally {
      if (isMountedRef.current) {
        setLoadingFolders(false);
      }
    }
  };

  // Fetch index status from GET /index/status
  const fetchStatus = async () => {
    try {
      const res = await fetch("/index/status", {
        credentials: "same-origin",
      });
      const ct = res.headers.get("content-type") || "";
      if (res.ok && ct.includes("application/json")) {
        const data: IndexStatus = await res.json();
        if (isMountedRef.current) {
          setStatus(data);
        }
      } else {
        const localState = getLocalFolderState();
        if (isMountedRef.current) {
          setStatus({
            running: false,
            current_task: localState.granted ? "Active (Local Device)" : "Awaiting Folder Permission",
            files_total: localState.fileCount,
            by_status: { indexed: localState.fileCount },
            last_run_time: localState.granted ? "Local Storage" : null,
            pending_ocr_count: 0,
          });
        }
      }
    } catch {
      const localState = getLocalFolderState();
      if (isMountedRef.current) {
        setStatus({
          running: false,
          current_task: "Local Laptop Mode",
          files_total: localState.fileCount,
          by_status: { indexed: localState.fileCount },
          last_run_time: null,
          pending_ocr_count: 0,
        });
      }
    } finally {
      if (isMountedRef.current) {
        setLoadingStatus(false);
      }
    }
  };

  // Fetch privacy details from GET /privacy
  const fetchPrivacy = async () => {
    try {
      const res = await fetch("/privacy", {
        credentials: "same-origin",
      });
      const ct = res.headers.get("content-type") || "";
      if (res.ok && ct.includes("application/json")) {
        const data: PrivacyInfo = await res.json();
        if (isMountedRef.current) {
          setPrivacy(data);
        }
      } else {
        const localState = getLocalFolderState();
        if (isMountedRef.current) {
          setPrivacy({
            data_folder: "Local Device Sandbox (Private Cache)",
            database_size: localState.fileCount * 1024,
            database_size_formatted: localState.granted ? `${localState.fileCount} items cached` : "0 KB",
            files_indexed: localState.fileCount,
            folders_count: localState.granted ? 1 : 0,
            folders: localState.folderName ? [localState.folderName] : [],
            vault_pin_set: true,
            embedding_model: "On-Device Client Embeddings",
          });
        }
      }
    } catch {
      const localState = getLocalFolderState();
      if (isMountedRef.current) {
        setPrivacy({
          data_folder: "Local Laptop Sandbox",
          database_size: 0,
          database_size_formatted: "Local",
          files_indexed: localState.fileCount,
          folders_count: localState.granted ? 1 : 0,
          folders: localState.folderName ? [localState.folderName] : [],
          vault_pin_set: true,
          embedding_model: "Client FastEmbed",
        });
      }
    } finally {
      if (isMountedRef.current) {
        setLoadingPrivacy(false);
      }
    }
  };

  // Initial load and polling: poll every 3 seconds ONLY while panel is open
  useEffect(() => {
    isMountedRef.current = true;
    fetchFolders();
    fetchExcludedFolders();
    fetchImageFolders();
    fetchStatus();
    fetchPrivacy();

    const intervalId = setInterval(() => {
      fetchStatus();
      fetchPrivacy();
    }, 3000);

    return () => {
      isMountedRef.current = false;
      clearInterval(intervalId);
    };
  }, []);

  // Fetch excluded folders
  const fetchExcludedFolders = async () => {
    try {
      const res = await fetch("/settings/excluded-folders", { credentials: "same-origin" });
      const ct = res.headers.get("content-type") || "";
      if (res.ok && ct.includes("application/json")) {
        const data = await res.json();
        if (isMountedRef.current) {
          setExcludedFolders(data.folders || []);
        }
      }
    } catch {
      if (isMountedRef.current) {
        setExcludedFolders(["Pictures", "Photos", "Camera Roll", "Screenshots", "Saved Pictures"]);
      }
    } finally {
      if (isMountedRef.current) {
        setLoadingExcluded(false);
      }
    }
  };

  // Fetch image folders
  const fetchImageFolders = async () => {
    try {
      const res = await fetch("/settings/image-folders", { credentials: "same-origin" });
      const ct = res.headers.get("content-type") || "";
      if (res.ok && ct.includes("application/json")) {
        const data = await res.json();
        if (isMountedRef.current) {
          setImageFolders(data.folders || []);
        }
      }
    } catch {
      if (isMountedRef.current) {
        setImageFolders([]);
      }
    } finally {
      if (isMountedRef.current) {
        setLoadingImageFolders(false);
      }
    }
  };

  const handleAddExcluded = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanPath = newExcludedPath.trim();
    if (!cleanPath) return;
    setAddingExcluded(true);
    setExcludedError(null);
    try {
      const res = await fetch("/settings/excluded-folders", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: cleanPath }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setExcludedError(data.detail || "Failed to add excluded folder.");
      } else {
        setExcludedFolders(data.folders || []);
        setNewExcludedPath("");
        onShowToast(`Added "${cleanPath}" to excluded folders.`);
      }
    } catch (err: unknown) {
      setExcludedError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingExcluded(false);
    }
  };

  const handleRemoveExcluded = async (folderPath: string) => {
    setRemovingExcluded(folderPath);
    try {
      const res = await fetch("/settings/excluded-folders", {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: folderPath }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setExcludedFolders(data.folders || []);
        onShowToast(`Removed "${folderPath}" from excluded folders.`);
      } else {
        onShowToast(data.detail || "Failed to remove excluded folder.");
      }
    } catch (err: unknown) {
      onShowToast(err instanceof Error ? err.message : String(err));
    } finally {
      setRemovingExcluded(null);
    }
  };

  const handleAddImageFolder = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanPath = newImagePath.trim();
    if (!cleanPath) return;
    setAddingImageFolder(true);
    setImageFolderError(null);
    try {
      const res = await fetch("/settings/image-folders", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: cleanPath }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setImageFolderError(data.detail || "Failed to add image folder. Ensure folder exists.");
      } else {
        setImageFolders(data.folders || []);
        setNewImagePath("");
        onShowToast(`Added "${cleanPath}" to image folders.`);
      }
    } catch (err: unknown) {
      setImageFolderError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingImageFolder(false);
    }
  };

  const handleRemoveImageFolder = async (folderPath: string) => {
    setRemovingImageFolder(folderPath);
    try {
      const res = await fetch("/settings/image-folders", {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: folderPath }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setImageFolders(data.folders || []);
        onShowToast(`Removed "${folderPath}" from image folders.`);
      } else {
        onShowToast(data.detail || "Failed to remove image folder.");
      }
    } catch (err: unknown) {
      onShowToast(err instanceof Error ? err.message : String(err));
    } finally {
      setRemovingImageFolder(null);
    }
  };

  // Add folder handler
  const handleAddFolder = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanPath = newFolderPath.trim();
    if (!cleanPath) {
      setAddError("Please enter a valid folder path.");
      return;
    }

    setAddingFolder(true);
    setAddError(null);
    try {
      const res = await fetch("/settings/folders", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ path: cleanPath }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        const errorMsg = data.detail || data.message || "Failed to add folder.";
        setAddError(errorMsg);
        onShowToast(errorMsg);
        return;
      }

      setFolders(data.folders || []);
      setNewFolderPath("");
      onShowToast(`Folder added: "${cleanPath}"`);
      await Promise.all([fetchStatus(), fetchPrivacy()]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Network error adding folder.";
      setAddError(msg);
      onShowToast(msg);
    } finally {
      setAddingFolder(false);
    }
  };

  // Remove folder handler
  const handleRemoveFolder = async (folderPath: string) => {
    setRemovingFolder(folderPath);
    try {
      const res = await fetch("/settings/folders", {
        method: "DELETE",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ path: folderPath }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const errorMsg = data.detail || data.message || "Failed to remove folder.";
        onShowToast(errorMsg);
        return;
      }

      setFolders(data.folders || []);
      onShowToast(`Removed folder and cleaned up index: "${folderPath}"`);
      await Promise.all([fetchStatus(), fetchPrivacy()]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Network error removing folder.";
      onShowToast(msg);
    } finally {
      setRemovingFolder(null);
    }
  };

  // Trigger Index Now handler
  const handleTriggerIndex = async () => {
    setTriggeringIndex(true);
    try {
      const res = await fetch("/index/run", {
        method: "POST",
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));

      if (res.status === 409) {
        onShowToast("A background task is already running.");
      } else if (!res.ok) {
        onShowToast(data.detail || data.message || "Failed to start indexing.");
      } else {
        onShowToast("Full incremental indexing started in background.");
      }
      await fetchStatus();
    } catch (err: unknown) {
      onShowToast("Network error starting index.");
    } finally {
      setTriggeringIndex(false);
    }
  };

  // Trigger OCR handler
  const handleTriggerOcr = async () => {
    setTriggeringOcr(true);
    try {
      const res = await fetch("/ocr/run", {
        method: "POST",
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));

      if (res.status === 409) {
        onShowToast("A background task is already running.");
      } else if (!res.ok) {
        onShowToast(data.detail || data.message || "Failed to start OCR processing.");
      } else {
        onShowToast("OCR processing started for pending scanned files.");
      }
      await fetchStatus();
    } catch (err: unknown) {
      onShowToast("Network error starting OCR.");
    } finally {
      setTriggeringOcr(false);
    }
  };

  // Delete all data handler
  const handleDeleteAllSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (deleteConfirmInput.trim() !== "DELETE") {
      setDeleteError("You must type exactly DELETE to confirm.");
      return;
    }

    setDeleting(true);
    setDeleteError(null);

    try {
      let vaultToken: string | null = null;
      // If a PIN is configured, verify PIN first to get authorization token
      if (privacy?.vault_pin_set) {
        const pin = deletePinInput.trim();
        if (!pin) {
          setDeleteError("Vault PIN is required to authorize deletion.");
          setDeleting(false);
          return;
        }

        const unlockRes = await fetch("/vault/unlock", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin }),
        });

        const unlockData = await unlockRes.json().catch(() => ({}));
        if (!unlockRes.ok) {
          throw new Error(unlockData.detail || unlockData.message || "Invalid vault PIN.");
        }
        vaultToken = unlockData.token;
      }

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (vaultToken) {
        headers["X-Vault-Token"] = vaultToken;
      }

      const res = await fetch("/data/delete-all", {
        method: "POST",
        credentials: "same-origin",
        headers,
        body: JSON.stringify({ confirm: "DELETE" }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || `Deletion failed (${res.status})`);
      }

      setDeleteResult(data);
      onShowToast("All indexed data, vault entries, and settings were deleted.");

      // Refresh status and privacy info
      await Promise.all([fetchPrivacy(), fetchFolders(), fetchStatus()]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error deleting data.";
      setDeleteError(msg);
    } finally {
      setDeleting(false);
    }
  };

  const isBusy = status?.running || triggeringIndex || triggeringOcr;

  const getRunningTaskLabel = () => {
    if (!status) return "Loading...";
    if (status.running) {
      if (status.current_task === "indexing") return "Indexing files...";
      if (status.current_task === "ocr") return "Processing OCR...";
      return status.current_task || "Processing in background...";
    }
    return "Idle";
  };

  return (
    <div className="w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-zinc-950/90 p-5 shadow-xl backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-sky-500/40 bg-sky-500/10 text-sky-400 shadow-[0_0_20px_rgba(14,165,233,0.2)]">
            <Settings className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-zinc-100">Settings & Privacy</h2>
              {status?.running ? (
                <span className="flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
                  Running
                </span>
              ) : (
                <span className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  Ready
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-zinc-400">
              Manage indexed folders, local storage privacy, and document background processing.
            </p>
          </div>
        </div>

        {/* Close button */}
        <button
          type="button"
          onClick={onClose}
          className="rounded-xl border border-white/10 bg-white/5 p-2 text-zinc-400 transition-colors hover:bg-white/10 hover:text-white"
          title="Close Settings panel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Real-time Status Card (polling every 3 seconds) */}
      <div className="rounded-2xl border border-white/10 bg-zinc-950/90 p-5 shadow-xl backdrop-blur-md">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 pb-4">
          <div className="flex items-center gap-2.5 text-xs font-semibold uppercase tracking-wider text-zinc-300">
            <Database className="h-4 w-4 text-sky-400" />
            <span>Indexer Status</span>
          </div>

          {/* Quick Action Buttons */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={handleTriggerIndex}
              disabled={isBusy}
              className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3.5 py-2 text-xs font-medium text-emerald-300 transition-all hover:border-emerald-500/60 hover:bg-emerald-500/20 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
              title="Run incremental index across all configured folders"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${
                  status?.running && status?.current_task === "indexing"
                    ? "animate-spin"
                    : ""
                }`}
              />
              <span>Index now</span>
            </button>

            <button
              type="button"
              onClick={handleTriggerOcr}
              disabled={isBusy || (status?.pending_ocr_count ?? 0) === 0}
              className="flex items-center gap-2 rounded-xl border border-purple-500/30 bg-purple-500/10 px-3.5 py-2 text-xs font-medium text-purple-300 transition-all hover:border-purple-500/60 hover:bg-purple-500/20 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
              title="Process pending scanned image/PDF files"
            >
              <FileScan
                className={`h-3.5 w-3.5 ${
                  status?.running && status?.current_task === "ocr"
                    ? "animate-pulse"
                    : ""
                }`}
              />
              <span>Process scanned files (OCR)</span>
            </button>
          </div>
        </div>

        {/* Live Status Metrics */}
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-xl border border-white/5 bg-zinc-900/60 p-3 flex flex-col justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              Running Task
            </span>
            <div className="mt-1 flex items-center gap-2">
              {status?.running ? (
                <Loader2 className="h-4 w-4 animate-spin text-amber-400 shrink-0" />
              ) : (
                <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
              )}
              <span className="text-sm font-semibold text-zinc-100 truncate">
                {getRunningTaskLabel()}
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-white/5 bg-zinc-900/60 p-3 flex flex-col justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              Total Files
            </span>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-xl font-bold text-zinc-100">
                {status ? status.files_total : "..."}
              </span>
              <span className="text-xs text-zinc-400">
                {status && status.by_status.indexed
                  ? `(${status.by_status.indexed} indexed)`
                  : ""}
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-white/5 bg-zinc-900/60 p-3 flex flex-col justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              Pending OCR
            </span>
            <div className="mt-1 flex items-baseline gap-2">
              <span
                className={`text-xl font-bold ${
                  (status?.pending_ocr_count ?? 0) > 0
                    ? "text-purple-400"
                    : "text-zinc-100"
                }`}
              >
                {status ? status.pending_ocr_count : "..."}
              </span>
              <span className="text-xs text-zinc-400">scanned documents</span>
            </div>
          </div>
        </div>

        {status?.last_run_time && (
          <div className="mt-3 flex items-center gap-1.5 text-[11px] text-zinc-500">
            <Clock className="h-3 w-3" />
            <span>Last run: {new Date(status.last_run_time).toLocaleString()}</span>
          </div>
        )}
      </div>

      {/* Privacy Section (GET /privacy) */}
      <div className="rounded-2xl border border-white/10 bg-zinc-950/90 p-5 shadow-xl backdrop-blur-md space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">Privacy & Storage</h3>
              <p className="text-xs text-zinc-400">
                All data is stored locally on this machine. Never uploaded to any cloud.
              </p>
            </div>
          </div>

          {/* Delete all data button */}
          <button
            type="button"
            onClick={() => {
              setDeleteConfirmInput("");
              setDeletePinInput("");
              setDeleteError(null);
              setDeleteResult(null);
              setShowDeleteModal(true);
            }}
            className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-3.5 py-2 text-xs font-semibold text-red-400 transition-all hover:border-red-500/60 hover:bg-red-500/20 active:scale-95 shadow-[0_0_15px_rgba(239,68,68,0.1)]"
            title="Delete local index, vault, and database contents"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>Delete all my data</span>
          </button>
        </div>

        {/* Privacy Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-1">
          {/* Data Location */}
          <div className="rounded-xl border border-white/5 bg-zinc-900/60 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              <HardDrive className="h-3.5 w-3.5 text-zinc-400" />
              <span>Storage Location</span>
            </div>
            <div
              className="text-xs font-mono text-zinc-200 truncate"
              title={privacy ? privacy.data_folder : "Loading..."}
            >
              {privacy ? privacy.data_folder : "..."}
            </div>
          </div>

          {/* Database Size */}
          <div className="rounded-xl border border-white/5 bg-zinc-900/60 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              <Database className="h-3.5 w-3.5 text-zinc-400" />
              <span>Database Size</span>
            </div>
            <div className="text-sm font-semibold text-zinc-100">
              {privacy ? privacy.database_size_formatted : "..."}
            </div>
          </div>

          {/* Files Indexed */}
          <div className="rounded-xl border border-white/5 bg-zinc-900/60 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              <FileScan className="h-3.5 w-3.5 text-zinc-400" />
              <span>Files Indexed</span>
            </div>
            <div className="text-sm font-semibold text-zinc-100">
              {privacy ? `${privacy.files_indexed} documents` : "..."}
            </div>
          </div>

          {/* Vault PIN status */}
          <div className="rounded-xl border border-white/5 bg-zinc-900/60 p-3 space-y-1">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              <KeyRound className="h-3.5 w-3.5 text-zinc-400" />
              <span>Vault PIN Lock</span>
            </div>
            <div className="flex items-center gap-1.5">
              {privacy?.vault_pin_set ? (
                <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
                  <ShieldCheck className="h-3 w-3" />
                  <span>PIN Enabled</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-800/80 px-2 py-0.5 text-[11px] font-medium text-zinc-400">
                  <span>No PIN Set</span>
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Laptop Local Folder Permission & Safety Card */}
      <div className="rounded-2xl border border-emerald-500/20 bg-emerald-950/10 p-5 shadow-xl backdrop-blur-md space-y-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
                Laptop Folder Authorization
                <span className="text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase">
                  Local & Secure
                </span>
              </h3>
              <p className="text-[11px] text-zinc-400">
                Grants permission once to search files on this laptop. 0% uploaded to cloud.
              </p>
            </div>
          </div>

          {localFolder.granted && (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-950/80 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
              <CheckCircle2 className="h-3 w-3" />
              <span>Authorized</span>
            </span>
          )}
        </div>

        {/* Current Laptop Folder Info */}
        <div className="rounded-xl bg-zinc-900/60 border border-white/5 p-3.5 text-xs space-y-2">
          {localFolder.granted ? (
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium text-zinc-200">
                  Folder: <span className="text-emerald-300 font-mono">{localFolder.folderName}</span>
                </p>
                <p className="text-[11px] text-zinc-400 mt-0.5">
                  {localFolder.fileCount} local files indexed on this laptop.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  revokeLocalPermission();
                  const s = getLocalFolderState();
                  setLocalFolder(s);
                  onShowToast("Revoked laptop folder access and cleared local index.");
                  fetchFolders();
                  fetchPrivacy();
                  fetchStatus();
                }}
                className="flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-1.5 text-xs font-medium text-red-300 hover:bg-red-900/40 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span>Revoke</span>
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <p className="text-[11px] text-zinc-400">
                No laptop folder authorized yet. Click below to authorize a folder once.
              </p>
            </div>
          )}

          <div className="pt-1 border-t border-white/5 flex items-center justify-between text-[10px] text-zinc-500">
            <span>🛡️ System roots (C:\Windows, Program Files) automatically protected.</span>
            <span>🔒 Strict local sandbox</span>
          </div>
        </div>

        <button
          type="button"
          disabled={requestingPerm}
          onClick={async () => {
            setRequestingPerm(true);
            try {
              const res = await requestFolderPermissionAndScan();
              if (res.ok) {
                const s = getLocalFolderState();
                setLocalFolder(s);
                onShowToast(`Permission granted! Indexed ${res.count} files from "${res.folderName}".`);
                await Promise.all([fetchFolders(), fetchPrivacy(), fetchStatus()]);
              } else {
                onShowToast(res.message);
              }
            } catch (err: any) {
              onShowToast(err.message || "Failed to select folder.");
            } finally {
              setRequestingPerm(false);
            }
          }}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-300 px-4 py-2 text-xs font-medium transition-all active:scale-[0.99] disabled:opacity-50"
        >
          {requestingPerm ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Scanning Laptop Folder...</span>
            </>
          ) : (
            <>
              <FolderPlus className="h-3.5 w-3.5" />
              <span>{localFolder.granted ? "Change / Re-scan Laptop Folder" : "Select & Authorize Folder on this Laptop"}</span>
            </>
          )}
        </button>
      </div>

      {/* Folder Management Section */}
      <div className="rounded-2xl border border-white/10 bg-zinc-950/90 p-5 shadow-xl backdrop-blur-md space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Indexed Folders</h3>
          <p className="text-xs text-zinc-400 mt-0.5">
            The background watcher automatically monitors these directories for changes and debounces updates by 10 seconds.
          </p>
        </div>

        {/* Add Folder Form */}
        <form onSubmit={handleAddFolder} className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                value={newFolderPath}
                onChange={(e) => {
                  setNewFolderPath(e.target.value);
                  if (addError) setAddError(null);
                }}
                placeholder="Folder path (e.g. D:\Documents or C:\Users\name\Notes)..."
                className="w-full rounded-xl border border-white/10 bg-zinc-900/80 px-3.5 py-2.5 text-xs text-zinc-100 placeholder:text-zinc-500 transition-colors focus:border-sky-500/50 focus:outline-none focus:ring-1 focus:ring-sky-500/50"
              />
            </div>
            <button
              type="submit"
              disabled={addingFolder || !newFolderPath.trim()}
              className="flex items-center gap-1.5 rounded-xl border border-sky-500/30 bg-sky-500/10 px-4 py-2.5 text-xs font-medium text-sky-300 transition-all hover:border-sky-500/60 hover:bg-sky-500/20 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {addingFolder ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FolderPlus className="h-3.5 w-3.5" />
              )}
              <span>Add</span>
            </button>
          </div>

          {addError && (
            <div className="flex items-center gap-1.5 text-xs text-red-400 pt-1">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              <span>{addError}</span>
            </div>
          )}
        </form>

        {/* Folders List */}
        <div className="space-y-2 pt-2">
          {loadingFolders ? (
            <div className="flex items-center justify-center py-6 text-xs text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              <span>Loading configured folders...</span>
            </div>
          ) : folders.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
              <Folder className="mx-auto h-8 w-8 text-zinc-600 mb-2" />
              <p className="text-xs text-zinc-400">No folders configured for indexing yet.</p>
              <p className="text-[11px] text-zinc-500 mt-1">
                Add an absolute folder path above to start indexing files automatically.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {folders.map((folderPath) => (
                <div
                  key={folderPath}
                  className="group flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-zinc-900/50 p-3 transition-colors hover:border-white/10 hover:bg-zinc-900/80"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Folder className="h-4 w-4 shrink-0 text-sky-400" />
                    <span
                      className="font-mono text-xs text-zinc-200 truncate"
                      title={folderPath}
                    >
                      {folderPath}
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRemoveFolder(folderPath)}
                    disabled={removingFolder === folderPath}
                    className="flex shrink-0 items-center gap-1.5 rounded-lg border border-red-500/20 bg-red-500/10 px-2.5 py-1.5 text-xs font-medium text-red-400 transition-all hover:border-red-500/40 hover:bg-red-500/20 active:scale-95 disabled:opacity-50"
                    title="Remove folder and delete its files from the index"
                  >
                    {removingFolder === folderPath ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                    <span>Remove</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Excluded Folders Card */}
      <div className="rounded-2xl border border-white/5 bg-zinc-950/40 p-5 backdrop-blur-sm space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-400">
            <FolderX className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-zinc-200">Excluded Folders</h3>
            <p className="text-xs text-zinc-400">
              Nothing inside these folders will be indexed. Common photo and screenshot folders are excluded by default to keep document searches fast.
            </p>
          </div>
        </div>

        {/* Add Excluded Folder Form */}
        <form onSubmit={handleAddExcluded} className="space-y-2">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                value={newExcludedPath}
                onChange={(e) => setNewExcludedPath(e.target.value)}
                placeholder="Folder name or path (e.g. Pictures, Screenshots, D:\Private)"
                className="w-full rounded-xl border border-white/10 bg-zinc-900/60 px-3.5 py-2.5 text-xs text-zinc-200 placeholder-zinc-500 outline-none transition-colors focus:border-amber-500/50 focus:bg-zinc-900"
              />
            </div>
            <button
              type="submit"
              disabled={addingExcluded || !newExcludedPath.trim()}
              className="flex items-center gap-1.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs font-medium text-amber-300 transition-all hover:border-amber-500/60 hover:bg-amber-500/20 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {addingExcluded ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FolderPlus className="h-3.5 w-3.5" />
              )}
              <span>Add</span>
            </button>
          </div>

          {excludedError && (
            <div className="flex items-center gap-1.5 text-xs text-red-400 pt-1">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              <span>{excludedError}</span>
            </div>
          )}
        </form>

        {/* Excluded Folders List */}
        <div className="space-y-2 pt-1">
          {loadingExcluded ? (
            <div className="flex items-center justify-center py-4 text-xs text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              <span>Loading excluded folders...</span>
            </div>
          ) : excludedFolders.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 p-4 text-center">
              <p className="text-xs text-zinc-400">No folders excluded.</p>
            </div>
          ) : (
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {excludedFolders.map((ef) => (
                <div
                  key={ef}
                  className="group flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-zinc-900/40 p-2.5 transition-colors hover:border-white/10 hover:bg-zinc-900/70"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <FolderX className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                    <span className="font-mono text-xs text-zinc-300 truncate" title={ef}>
                      {ef}
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRemoveExcluded(ef)}
                    disabled={removingExcluded === ef}
                    className="flex shrink-0 items-center gap-1 rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-[11px] font-medium text-red-400 transition-all hover:border-red-500/40 hover:bg-red-500/20 active:scale-95 disabled:opacity-50"
                    title="Remove from excluded folders"
                  >
                    {removingExcluded === ef ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                    <span>Remove</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Image Folders Card */}
      <div className="rounded-2xl border border-white/5 bg-zinc-950/40 p-5 backdrop-blur-sm space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
            <Image className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-zinc-200">Image Folders (Photos & Screenshots)</h3>
            <p className="text-xs text-zinc-400">
              Configure specific folders for image indexing and OCR.
            </p>
          </div>
        </div>

        {/* Image indexing off note */}
        <div className="flex items-start gap-2.5 rounded-xl border border-emerald-500/20 bg-emerald-500/10 p-3 text-xs text-emerald-300">
          <Shield className="h-4 w-4 shrink-0 mt-0.5 text-emerald-400" />
          <div>
            <strong>Image indexing is off by default.</strong> Images (.png, .jpg, .jpeg) are only indexed and OCR'd if they are inside an image folder listed below.
          </div>
        </div>

        {/* Add Image Folder Form */}
        <form onSubmit={handleAddImageFolder} className="space-y-2">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                value={newImagePath}
                onChange={(e) => setNewImagePath(e.target.value)}
                placeholder="Absolute image folder path (e.g. D:\Receipts, C:\Users\vikas\Desktop\ID_Cards)"
                className="w-full rounded-xl border border-white/10 bg-zinc-900/60 px-3.5 py-2.5 text-xs text-zinc-200 placeholder-zinc-500 outline-none transition-colors focus:border-emerald-500/50 focus:bg-zinc-900"
              />
            </div>
            <button
              type="submit"
              disabled={addingImageFolder || !newImagePath.trim()}
              className="flex items-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-xs font-medium text-emerald-300 transition-all hover:border-emerald-500/60 hover:bg-emerald-500/20 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {addingImageFolder ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FolderPlus className="h-3.5 w-3.5" />
              )}
              <span>Add</span>
            </button>
          </div>

          {imageFolderError && (
            <div className="flex items-center gap-1.5 text-xs text-red-400 pt-1">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              <span>{imageFolderError}</span>
            </div>
          )}
        </form>

        {/* Image Folders List */}
        <div className="space-y-2 pt-1">
          {loadingImageFolders ? (
            <div className="flex items-center justify-center py-4 text-xs text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              <span>Loading image folders...</span>
            </div>
          ) : imageFolders.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 p-4 text-center">
              <p className="text-xs text-zinc-400">No image folders configured (image indexing is completely disabled).</p>
              <p className="text-[11px] text-zinc-500 mt-1">
                Add a folder above if you want specific receipts or ID scans to be indexed with OCR.
              </p>
            </div>
          ) : (
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {imageFolders.map((imf) => (
                <div
                  key={imf}
                  className="group flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-zinc-900/40 p-2.5 transition-colors hover:border-white/10 hover:bg-zinc-900/70"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Image className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                    <span className="font-mono text-xs text-zinc-300 truncate" title={imf}>
                      {imf}
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRemoveImageFolder(imf)}
                    disabled={removingImageFolder === imf}
                    className="flex shrink-0 items-center gap-1 rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-[11px] font-medium text-red-400 transition-all hover:border-red-500/40 hover:bg-red-500/20 active:scale-95 disabled:opacity-50"
                    title="Remove image folder"
                  >
                    {removingImageFolder === imf ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                    <span>Remove</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Confirmation Dialog Modal for "Delete all my data" */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="relative w-full max-w-md rounded-2xl border border-red-500/30 bg-zinc-950 p-6 shadow-2xl shadow-red-950/40">
            {/* Modal Header */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-red-500/40 bg-red-500/10 text-red-400">
                  <AlertTriangle className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">
                    Delete All My Data
                  </h3>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    Irreversible action on local database
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  if (!deleting) setShowDeleteModal(false);
                }}
                disabled={deleting}
                className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-800 hover:text-white transition-colors disabled:opacity-50"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Content */}
            {!deleteResult ? (
              <form onSubmit={handleDeleteAllSubmit} className="mt-5 space-y-4">
                {/* Clear explanation of what will be deleted and what will not */}
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3.5 text-xs text-zinc-300 space-y-2">
                  <p>
                    This will delete all local data in the database:
                  </p>
                  <ul className="list-disc list-inside space-y-0.5 text-zinc-400 pl-1">
                    <li>The search index and semantic embeddings</li>
                    <li>All extracted facts, dates, and document categories</li>
                    <li>Pinned emergency vault documents and settings</li>
                    <li>Search caches and query sessions</li>
                  </ul>
                  <div className="pt-1 font-semibold text-emerald-400 border-t border-amber-500/20">
                    ✓ Your original files and folders on disk will NOT be touched or deleted.
                  </div>
                </div>

                {/* Vault PIN input if PIN is set */}
                {privacy?.vault_pin_set && (
                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-zinc-300">
                      Vault PIN <span className="text-red-400">*</span>
                    </label>
                    <input
                      type="password"
                      maxLength={8}
                      value={deletePinInput}
                      onChange={(e) => setDeletePinInput(e.target.value.replace(/\D/g, ""))}
                      placeholder="Enter 4-8 digit Vault PIN..."
                      className="w-full rounded-xl border border-white/10 bg-zinc-900 px-3.5 py-2.5 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-red-500/50 focus:outline-none focus:ring-1 focus:ring-red-500/50"
                      disabled={deleting}
                    />
                    <p className="text-[11px] text-zinc-500">
                      Your PIN is required to authorize clearing the protected vault.
                    </p>
                  </div>
                )}

                {/* Confirmation input: user must type DELETE */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-medium text-zinc-300">
                    Type <span className="font-mono font-bold text-red-400">DELETE</span> to confirm:
                  </label>
                  <input
                    type="text"
                    value={deleteConfirmInput}
                    onChange={(e) => {
                      setDeleteConfirmInput(e.target.value);
                      if (deleteError) setDeleteError(null);
                    }}
                    placeholder="DELETE"
                    className="w-full rounded-xl border border-white/10 bg-zinc-900 px-3.5 py-2.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-red-500/50 focus:outline-none focus:ring-1 focus:ring-red-500/50"
                    disabled={deleting}
                  />
                </div>

                {deleteError && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-xs text-red-400">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    <span>{deleteError}</span>
                  </div>
                )}

                {/* Modal Actions */}
                <div className="flex items-center justify-end gap-2.5 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowDeleteModal(false)}
                    disabled={deleting}
                    className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs font-medium text-zinc-300 hover:bg-white/10 hover:text-white transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={deleting || deleteConfirmInput.trim() !== "DELETE" || (privacy?.vault_pin_set && !deletePinInput.trim())}
                    className="flex items-center gap-1.5 rounded-xl border border-red-500/40 bg-red-600 px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-red-900/40 transition-all hover:bg-red-500 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {deleting ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        <span>Deleting...</span>
                      </>
                    ) : (
                      <>
                        <Trash2 className="h-3.5 w-3.5" />
                        <span>Delete all my data</span>
                      </>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              /* Success Result View */
              <div className="mt-5 space-y-4">
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-center space-y-2">
                  <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-400" />
                  <h4 className="text-sm font-semibold text-emerald-300">
                    All Data Successfully Deleted
                  </h4>
                  <p className="text-xs text-zinc-300">
                    The local index and vault have been reset and SQLite database vacuumed.
                  </p>
                </div>

                {/* Detailed deletion summary */}
                <div className="rounded-xl border border-white/5 bg-zinc-900/70 p-3 space-y-2 text-xs">
                  <div className="font-medium text-zinc-400">Deletion Summary:</div>
                  <div className="grid grid-cols-2 gap-2 text-zinc-300">
                    <div>Files removed: <span className="font-semibold text-zinc-100">{deleteResult.deleted.files ?? 0}</span></div>
                    <div>Chunks removed: <span className="font-semibold text-zinc-100">{deleteResult.deleted.chunks ?? 0}</span></div>
                    <div>Facts removed: <span className="font-semibold text-zinc-100">{deleteResult.deleted.facts ?? 0}</span></div>
                    <div>Vault pins removed: <span className="font-semibold text-zinc-100">{deleteResult.deleted.vault ?? 0}</span></div>
                  </div>
                </div>

                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setShowDeleteModal(false);
                      setDeleteResult(null);
                    }}
                    className="rounded-xl border border-white/10 bg-white/10 px-4 py-2.5 text-xs font-medium text-white hover:bg-white/20 transition-colors"
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

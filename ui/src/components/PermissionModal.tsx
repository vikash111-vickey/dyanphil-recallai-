import React, { useState } from "react";
import {
  ShieldCheck,
  FolderOpen,
  Lock,
  EyeOff,
  AlertTriangle,
  X,
  Loader2,
  CheckCircle2,
  Sparkles,
} from "lucide-react";
import { requestFolderPermissionAndScan } from "@/lib/localFileScanner";

interface PermissionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPermissionGranted: (folderName: string, fileCount: number) => void;
}

export function PermissionModal({
  isOpen,
  onClose,
  onPermissionGranted,
}: PermissionModalProps) {
  const [scanning, setScanning] = useState(false);
  const [currentFile, setCurrentFile] = useState("");
  const [scanCount, setScanCount] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleGrantPermission = async () => {
    setErrorMsg(null);
    setScanning(true);
    setScanCount(0);
    setCurrentFile("");

    try {
      const result = await requestFolderPermissionAndScan((name, count) => {
        setCurrentFile(name);
        setScanCount(count);
      });

      if (result.ok) {
        onPermissionGranted(result.folderName, result.count);
        onClose();
      } else {
        setErrorMsg(result.message);
      }
    } catch (err: any) {
      console.error("Folder permission error:", err);
      setErrorMsg(
        err.message || "Failed to select folder. Please check your browser permissions."
      );
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg rounded-2xl border border-zinc-800 bg-[#09090d] p-6 shadow-2xl text-zinc-100 selection:bg-emerald-500/30">
        {/* Close Button */}
        <button
          onClick={onClose}
          disabled={scanning}
          className="absolute top-4 right-4 text-zinc-400 hover:text-zinc-100 disabled:opacity-40 transition-colors p-1"
          aria-label="Close"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-white flex items-center gap-2">
              Laptop File Access & Privacy
              <span className="text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase">
                Permission Once
              </span>
            </h2>
            <p className="text-xs text-zinc-400">
              100% On-Device Search & Security Verification
            </p>
          </div>
        </div>

        {/* Safety Guarantees */}
        <div className="space-y-2.5 my-4 bg-zinc-950/60 rounded-xl p-3.5 border border-zinc-850 text-xs">
          <div className="flex items-start gap-2.5">
            <Lock className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-zinc-200">0% Cloud Upload:</span>{" "}
              <span className="text-zinc-400">
                All scanning and searches run directly on your laptop inside your device. Your documents never leave your computer.
              </span>
            </div>
          </div>

          <div className="flex items-start gap-2.5">
            <EyeOff className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-zinc-200">Automatic Masking:</span>{" "}
              <span className="text-zinc-400">
                Sensitive info (Aadhaar, PAN, card numbers, passwords) is automatically masked for safety.
              </span>
            </div>
          </div>

          <div className="flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-zinc-200">System Folder Protection:</span>{" "}
              <span className="text-zinc-400">
                Operating system folders (like C:\Windows and Program Files) are strictly blocked from being scanned.
              </span>
            </div>
          </div>
        </div>

        {/* Error message */}
        {errorMsg && (
          <div className="mb-4 rounded-lg bg-red-950/40 border border-red-800/40 p-3 text-xs text-red-300 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Scanning Progress */}
        {scanning && (
          <div className="mb-4 rounded-xl bg-emerald-950/20 border border-emerald-500/20 p-3.5 text-xs text-emerald-200">
            <div className="flex items-center justify-between mb-2">
              <span className="flex items-center gap-2 font-medium">
                <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
                Scanning your authorized folder...
              </span>
              <span className="text-[11px] font-mono text-emerald-400 font-semibold">
                {scanCount} files found
              </span>
            </div>
            {currentFile && (
              <p className="text-[11px] text-zinc-400 truncate font-mono">
                Indexing: {currentFile}
              </p>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-col gap-2.5 mt-5">
          <button
            type="button"
            onClick={handleGrantPermission}
            disabled={scanning}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white px-4 py-2.5 text-sm font-medium transition-all shadow-lg shadow-emerald-950/50 active:scale-[0.99] disabled:opacity-50"
          >
            {scanning ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Reading & Indexing Laptop Folder...</span>
              </>
            ) : (
              <>
                <FolderOpen className="w-4 h-4" />
                <span>Select Folder on This Laptop</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={onClose}
            disabled={scanning}
            className="w-full rounded-xl border border-zinc-800 bg-zinc-900/60 hover:bg-zinc-800/60 text-zinc-300 hover:text-white px-4 py-2 text-xs font-medium transition-all"
          >
            Explore with Sample Documents First
          </button>
        </div>

        <p className="mt-3 text-center text-[10px] text-zinc-500">
          You can revoke or change authorized folders anytime in Settings.
        </p>
      </div>
    </div>
  );
}

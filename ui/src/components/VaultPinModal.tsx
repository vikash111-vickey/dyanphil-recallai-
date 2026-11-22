import React, { useState, useEffect, useRef } from "react";
import { Shield, Lock, AlertCircle, X, KeyRound, Sparkles } from "lucide-react";

interface VaultPinModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (token: string) => void;
  initialMode?: "unlock" | "setup";
  customMessage?: string;
}

export function VaultPinModal({
  isOpen,
  onClose,
  onSuccess,
  initialMode = "unlock",
  customMessage,
}: VaultPinModalProps) {
  const [mode, setMode] = useState<"unlock" | "setup">(initialMode);
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setPin("");
      setConfirmPin("");
      setError(null);
      setMode(initialMode);
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    }
  }, [isOpen, initialMode]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validate digits & length
    if (!pin || !/^\d{4,8}$/.test(pin)) {
      setError("PIN must be between 4 and 8 digits.");
      return;
    }

    if (mode === "setup") {
      if (pin !== confirmPin) {
        setError("PINs do not match. Please verify.");
        return;
      }
    }

    setLoading(true);

    try {
      if (mode === "setup") {
        // 1. Setup new PIN
        const setupRes = await fetch("/vault/setup", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin }),
        });

        const setupData = await setupRes.json().catch(() => ({}));
        if (!setupRes.ok) {
          throw new Error(setupData.detail || setupData.message || `Setup failed (${setupRes.status})`);
        }

        // 2. Immediately unlock to obtain 10-minute token
        const unlockRes = await fetch("/vault/unlock", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin }),
        });

        const unlockData = await unlockRes.json().catch(() => ({}));
        if (!unlockRes.ok) {
          throw new Error(unlockData.detail || `Unlock failed (${unlockRes.status})`);
        }

        onSuccess(unlockData.token);
      } else {
        // Unlock existing PIN
        const unlockRes = await fetch("/vault/unlock", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin }),
        });

        const unlockData = await unlockRes.json().catch(() => ({}));

        if (!unlockRes.ok) {
          const detail = unlockData.detail || unlockData.message || `Unlock failed (${unlockRes.status})`;
          // If not setup yet, offer setup automatically
          if (unlockRes.status === 400 && detail.toLowerCase().includes("not been set up")) {
            setMode("setup");
            setError("No PIN is configured yet. Enter a 4–8 digit PIN to set up your Vault.");
            return;
          }
          throw new Error(detail);
        }

        onSuccess(unlockData.token);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200"
    >
      <div className="relative w-full max-w-sm rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-2xl backdrop-blur-xl">
        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 rounded-lg p-1 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
          aria-label="Close dialog"
        >
          <X className="h-4 w-4" />
        </button>

        {/* Header */}
        <div className="flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-purple-500/30 bg-purple-500/10 text-purple-400 shadow-[0_0_20px_rgba(168,85,247,0.15)]">
            {mode === "setup" ? (
              <Sparkles className="h-6 w-6" />
            ) : (
              <Shield className="h-6 w-6" />
            )}
          </div>

          <h2 className="mt-3.5 text-base font-semibold text-zinc-100">
            {mode === "setup" ? "Set up Emergency Vault PIN" : "Unlock Emergency Vault"}
          </h2>

          <p className="mt-1 text-xs text-zinc-400">
            {customMessage ||
              (mode === "setup"
                ? "Create a 4–8 digit numeric PIN to secure your emergency documents."
                : "Enter your 4–8 digit PIN to access pinned vault files.")}
          </p>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 shrink-0 text-rose-400 mt-0.5" />
            <span className="flex-1">{error}</span>
          </div>
        )}

        {/* PIN Form */}
        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div>
            <label className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400">
              {mode === "setup" ? "New PIN (4–8 digits)" : "Vault PIN"}
            </label>
            <input
              ref={inputRef}
              type="password"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={8}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
              placeholder="••••"
              disabled={loading}
              className="mt-1.5 w-full rounded-xl border border-white/10 bg-zinc-900 px-4 py-3 text-center font-mono text-xl tracking-[0.4em] text-zinc-100 outline-none transition-all placeholder:tracking-normal placeholder:text-zinc-600 focus:border-purple-500/60 focus:ring-2 focus:ring-purple-500/20 disabled:opacity-50"
            />
          </div>

          {mode === "setup" && (
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                Confirm PIN
              </label>
              <input
                type="password"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={8}
                value={confirmPin}
                onChange={(e) => setConfirmPin(e.target.value.replace(/\D/g, ""))}
                placeholder="••••"
                disabled={loading}
                className="mt-1.5 w-full rounded-xl border border-white/10 bg-zinc-900 px-4 py-3 text-center font-mono text-xl tracking-[0.4em] text-zinc-100 outline-none transition-all placeholder:tracking-normal placeholder:text-zinc-600 focus:border-purple-500/60 focus:ring-2 focus:ring-purple-500/20 disabled:opacity-50"
              />
            </div>
          )}

          <button
            type="submit"
            disabled={loading || pin.length < 4 || (mode === "setup" && confirmPin.length < 4)}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-purple-500/30 bg-purple-600 px-4 py-2.5 text-xs font-semibold text-white shadow-[0_0_20px_rgba(168,85,247,0.3)] transition-all hover:bg-purple-500 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
          >
            {loading ? (
              <span>Authenticating...</span>
            ) : mode === "setup" ? (
              <>
                <KeyRound className="h-4 w-4" />
                <span>Save PIN & Unlock</span>
              </>
            ) : (
              <>
                <Lock className="h-4 w-4" />
                <span>Unlock Vault</span>
              </>
            )}
          </button>
        </form>

        {/* Toggle between unlock and setup */}
        <div className="mt-4 border-t border-white/5 pt-3 text-center">
          {mode === "unlock" ? (
            <button
              type="button"
              onClick={() => {
                setMode("setup");
                setError(null);
                setPin("");
                setConfirmPin("");
              }}
              className="text-xs text-zinc-400 hover:text-purple-300 transition-colors"
            >
              First time? Set up a new PIN
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                setMode("unlock");
                setError(null);
                setPin("");
                setConfirmPin("");
              }}
              className="text-xs text-zinc-400 hover:text-purple-300 transition-colors"
            >
              Already set up? Enter PIN
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

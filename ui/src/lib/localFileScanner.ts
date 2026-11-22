// Local File Scanner & Privacy-Safe Folder Access via File System Access API
import { SearchResultItem } from "@/components/ResultsPanel";
import { maskSensitiveData } from "@/lib/masking";

const STORAGE_KEY_PERMISSION = "dyanphil_local_permission_granted";
const STORAGE_KEY_FOLDER_NAME = "dyanphil_local_folder_name";
const STORAGE_KEY_FILES = "dyanphil_local_indexed_files";

// Block dangerous OS roots and system directories
const BLOCKED_SYSTEM_NAMES = new Set([
  "windows",
  "system32",
  "program files",
  "program files (x86)",
  "programdata",
  "appdata",
  "$recycle.bin",
  "system volume information",
  "boot",
  "recovery",
  "etc",
  "bin",
  "sbin",
  "usr",
  "var",
]);

export interface LocalFolderState {
  granted: boolean;
  folderName: string | null;
  fileCount: number;
}

export function getLocalFolderState(): LocalFolderState {
  const granted = localStorage.getItem(STORAGE_KEY_PERMISSION) === "true";
  const folderName = localStorage.getItem(STORAGE_KEY_FOLDER_NAME);
  const storedFiles = localStorage.getItem(STORAGE_KEY_FILES);
  let fileCount = 0;
  if (storedFiles) {
    try {
      fileCount = JSON.parse(storedFiles).length;
    } catch {
      fileCount = 0;
    }
  }
  return { granted, folderName, fileCount };
}

export function revokeLocalPermission(): void {
  localStorage.removeItem(STORAGE_KEY_PERMISSION);
  localStorage.removeItem(STORAGE_KEY_FOLDER_NAME);
  localStorage.removeItem(STORAGE_KEY_FILES);
}

export function getStoredLocalFiles(): SearchResultItem[] {
  const stored = localStorage.getItem(STORAGE_KEY_FILES);
  if (!stored) return [];
  try {
    return JSON.parse(stored) as SearchResultItem[];
  } catch {
    return [];
  }
}

function classifyDocType(filename: string, content: string): string {
  const low = (filename + " " + content).toLowerCase();
  if (low.includes("passport") || low.includes("aadhaar") || low.includes("pan card") || low.includes("license") || low.includes("voter")) {
    return "id_document";
  }
  if (low.includes("insurance") || low.includes("policy") || low.includes("mediclaim")) {
    return "insurance";
  }
  if (low.includes("ticket") || low.includes("boarding") || low.includes("flight") || low.includes("pnr") || low.includes("train")) {
    return "ticket";
  }
  if (low.includes("invoice") || low.includes("bill") || low.includes("receipt") || low.includes("tax invoice")) {
    return "invoice";
  }
  if (low.includes("warranty") || low.includes("guarantee") || low.includes("service card")) {
    return "warranty";
  }
  if (low.includes("medical") || low.includes("prescription") || low.includes("diagnosis") || low.includes("lab report")) {
    return "medical";
  }
  if (low.includes("resume") || low.includes("cv") || low.includes("offer letter") || low.includes("experience")) {
    return "career";
  }
  return "notes";
}

function extractBasicFacts(text: string): { kind: string; label: string; value: string; value_date?: string }[] {
  const facts: { kind: string; label: string; value: string; value_date?: string }[] = [];

  // Match dates (YYYY-MM-DD or DD/MM/YYYY or DD-Mon-YYYY)
  const dateRegex = /\b(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})\b/g;
  let dateMatch;
  let dateCount = 0;
  while ((dateMatch = dateRegex.exec(text)) !== null && dateCount < 2) {
    facts.push({
      kind: "date",
      label: "Date",
      value: dateMatch[1],
      value_date: dateMatch[1],
    });
    dateCount++;
  }

  // Match amounts (₹ 1,234 or $ 100 or Rs. 500)
  const amountRegex = /(?:₹|Rs\.?|\$)\s*[\d,]+(?:\.\d{2})?/gi;
  const amountMatch = amountRegex.exec(text);
  if (amountMatch) {
    facts.push({
      kind: "amount",
      label: "Amount",
      value: amountMatch[0],
    });
  }

  return facts;
}

/**
 * Prompt the user to select a folder on their laptop and grant permission.
 * Validates folder name to prevent selecting system roots.
 */
export async function requestFolderPermissionAndScan(
  onProgress?: (filename: string, count: number) => void
): Promise<{ ok: boolean; message: string; count: number; folderName: string }> {
  // Check if File System Access API is supported
  if (!("showDirectoryPicker" in window)) {
    throw new Error(
      "Your browser does not support the File System Access API. Please use Google Chrome, Microsoft Edge, or the desktop app on your laptop."
    );
  }

  let dirHandle: FileSystemDirectoryHandle;
  try {
    dirHandle = await (window as any).showDirectoryPicker({
      mode: "read",
    });
  } catch (err: any) {
    if (err.name === "AbortError") {
      return { ok: false, message: "Folder selection cancelled by user.", count: 0, folderName: "" };
    }
    throw err;
  }

  const folderName = dirHandle.name;
  const folderNameLower = folderName.toLowerCase();

  // Safety check: block system folders
  if (BLOCKED_SYSTEM_NAMES.has(folderNameLower)) {
    return {
      ok: false,
      message: `Security Safety Restriction: Selecting system folder "${folderName}" is blocked to protect your operating system.`,
      count: 0,
      folderName,
    };
  }

  const indexed: SearchResultItem[] = [];
  const supportedExts = new Set([".txt", ".md", ".json", ".csv", ".log", ".pdf", ".html", ".xml", ".docx", ".xlsx"]);

  async function traverse(handle: FileSystemDirectoryHandle, pathParts: string[]) {
    // Max 100 files in browser memory for fast laptop responsiveness
    if (indexed.length >= 100) return;

    for await (const [name, entry] of (handle as any).entries()) {
      if (indexed.length >= 100) break;
      if (name.startsWith(".") || name === "node_modules" || name === "$RECYCLE.BIN") continue;

      if (entry.kind === "directory") {
        await traverse(entry, [...pathParts, name]);
      } else if (entry.kind === "file") {
        const dotIdx = name.lastIndexOf(".");
        const ext = dotIdx !== -1 ? name.slice(dotIdx).toLowerCase() : "";

        if (supportedExts.has(ext)) {
          try {
            const file = await entry.getFile();
            // Skip files > 15 MB in browser
            if (file.size > 15 * 1024 * 1024) continue;

            let textContent = "";
            if (ext === ".txt" || ext === ".md" || ext === ".json" || ext === ".csv" || ext === ".log" || ext === ".html") {
              textContent = await file.text();
            } else {
              textContent = `File: ${name} (${(file.size / 1024).toFixed(1)} KB) in ${pathParts.join("/")}`;
            }

            const docType = classifyDocType(name, textContent);
            const rawSnippet = textContent.slice(0, 300).replace(/\s+/g, " ");
            const safeSnippet = maskSensitiveData(rawSnippet);
            const safeFacts = extractBasicFacts(textContent).map((f) => ({
              ...f,
              value: maskSensitiveData(f.value),
            }));

            const relPath = [...pathParts, name].join("\\");
            const modifiedStr = new Date(file.lastModified).toISOString().slice(0, 10);

            indexed.push({
              filename: name,
              path: relPath,
              breadcrumb: [...pathParts, name],
              source: "laptop local",
              modified: modifiedStr,
              snippet: safeSnippet || `Document: ${name}`,
              match_type: "exact",
              exists: true,
              doc_type: docType,
              facts: safeFacts,
            });

            if (onProgress) {
              onProgress(name, indexed.length);
            }
          } catch (fileErr) {
            console.warn(`Could not read ${name}:`, fileErr);
          }
        }
      }
    }
  }

  await traverse(dirHandle, [folderName]);

  // Persist permission and indexed summary
  localStorage.setItem(STORAGE_KEY_PERMISSION, "true");
  localStorage.setItem(STORAGE_KEY_FOLDER_NAME, folderName);
  localStorage.setItem(STORAGE_KEY_FILES, JSON.stringify(indexed));

  return {
    ok: true,
    message: `Successfully granted permission! Indexed ${indexed.length} local files from "${folderName}".`,
    count: indexed.length,
    folderName,
  };
}

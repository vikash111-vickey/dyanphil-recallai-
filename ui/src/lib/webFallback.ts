import { AskResponse, SearchResultItem } from "@/components/ResultsPanel";
import { getStoredLocalFiles, getLocalFolderState } from "@/lib/localFileScanner";
import { maskSensitiveData } from "@/lib/masking";

export const SAMPLE_DOCUMENTS: SearchResultItem[] = [
  {
    filename: "Passport_Republic_of_India.pdf",
    path: "D:\\Personal\\Identity\\Passport_Republic_of_India.pdf",
    breadcrumb: ["Personal", "Identity", "Passport_Republic_of_India.pdf"],
    source: "local file",
    modified: "2019-08-15",
    snippet: "Republic of India Passport. Document No: T87654321. Name: Bearer. Place of Issue: Delhi. Valid until 14 Aug 2029.",
    match_type: "exact",
    exists: true,
    doc_type: "id_document",
    facts: [
      { kind: "date", label: "Expiry Date", value: "2029-08-14", value_date: "2029-08-14" },
      { kind: "id", label: "Passport Number", value: "T87654321" },
      { kind: "name", label: "Nationality", value: "Indian" },
    ],
  },
  {
    filename: "Aadhaar_Card_UIDAI_Identity.pdf",
    path: "D:\\Personal\\Identity\\Aadhaar_Card_UIDAI_Identity.pdf",
    breadcrumb: ["Personal", "Identity", "Aadhaar_Card_UIDAI_Identity.pdf"],
    source: "local file",
    modified: "2021-03-10",
    snippet: "Unique Identification Authority of India (UIDAI). Government of India Aadhaar Card. Aadhaar No: XXXX-XXXX-4921. Issue Date: 10 Mar 2021.",
    match_type: "exact",
    exists: true,
    doc_type: "id_document",
    facts: [
      { kind: "id", label: "Aadhaar Number", value: "XXXX-XXXX-4921" },
      { kind: "date", label: "Issue Date", value: "2021-03-10", value_date: "2021-03-10" },
      { kind: "name", label: "Authority", value: "UIDAI" },
    ],
  },
  {
    filename: "Star_Health_Insurance_Policy.pdf",
    path: "D:\\Finances\\Insurance\\Star_Health_Insurance_Policy.pdf",
    breadcrumb: ["Finances", "Insurance", "Star_Health_Insurance_Policy.pdf"],
    source: "local file",
    modified: "2024-04-01",
    snippet: "Star Comprehensive Family Health Insurance Policy. Policy No: SH-9912048. Sum Insured: INR 10,00,000. Coverage renewal due: 31 Mar 2027.",
    match_type: "semantic",
    exists: true,
    doc_type: "insurance",
    facts: [
      { kind: "date", label: "Valid Until", value: "2027-03-31", value_date: "2027-03-31" },
      { kind: "id", label: "Policy No", value: "SH-9912048" },
      { kind: "amount", label: "Sum Insured", value: "₹ 10,00,000" },
    ],
  },
  {
    filename: "IndiGo_Flight_Ticket_DEL_BOM.pdf",
    path: "D:\\Travel\\Bookings\\IndiGo_Flight_Ticket_DEL_BOM.pdf",
    breadcrumb: ["Travel", "Bookings", "IndiGo_Flight_Ticket_DEL_BOM.pdf"],
    source: "local file",
    modified: "2026-11-20",
    snippet: "IndiGo E-Ticket. Booking Reference PNR: K9L2MZ. Flight 6E-2041 DEL to BOM. Departure Date: 15 Dec 2026 at 08:30 AM.",
    match_type: "keyword",
    exists: true,
    doc_type: "ticket",
    facts: [
      { kind: "date", label: "Travel Date", value: "2026-12-15", value_date: "2026-12-15" },
      { kind: "id", label: "PNR Code", value: "K9L2MZ" },
      { kind: "name", label: "Flight", value: "6E-2041" },
    ],
  },
  {
    filename: "BSES_Yamuna_Electricity_Bill_Nov2026.pdf",
    path: "D:\\Utilities\\Bills\\BSES_Yamuna_Electricity_Bill_Nov2026.pdf",
    breadcrumb: ["Utilities", "Bills", "BSES_Yamuna_Electricity_Bill_Nov2026.pdf"],
    source: "local file",
    modified: "2026-11-15",
    snippet: "BSES Yamuna Power Limited Electricity Bill. Consumer Account: 102938475. Total Amount Payable: ₹ 3,420. Due Date: 30 Nov 2026.",
    match_type: "keyword",
    exists: true,
    doc_type: "invoice",
    facts: [
      { kind: "date", label: "Due Date", value: "2026-11-30", value_date: "2026-11-30" },
      { kind: "amount", label: "Amount Due", value: "₹ 3,420" },
      { kind: "id", label: "Consumer No", value: "102938475" },
    ],
  },
  {
    filename: "Dell_XPS_Laptop_Warranty_Card.pdf",
    path: "D:\\Appliances\\Electronics\\Dell_XPS_Laptop_Warranty_Card.pdf",
    breadcrumb: ["Appliances", "Electronics", "Dell_XPS_Laptop_Warranty_Card.pdf"],
    source: "local file",
    modified: "2024-06-18",
    snippet: "Dell Premium Support and Onsite Service Warranty. Service Tag: 8FG9K22. Coverage active through 18 Jun 2027.",
    match_type: "keyword",
    exists: true,
    doc_type: "warranty",
    facts: [
      { kind: "date", label: "Warranty Expiry", value: "2027-06-18", value_date: "2027-06-18" },
      { kind: "id", label: "Service Tag", value: "8FG9K22" },
      { kind: "name", label: "Model", value: "Dell XPS 15" },
    ],
  },
  {
    filename: "Income_Tax_Return_Acknowledgment_AY2026.pdf",
    path: "D:\\Finances\\Taxes\\Income_Tax_Return_Acknowledgment_AY2026.pdf",
    breadcrumb: ["Finances", "Taxes", "Income_Tax_Return_Acknowledgment_AY2026.pdf"],
    source: "local file",
    modified: "2026-07-28",
    snippet: "Income Tax Department Government of India. ITR-1 Sahaj Acknowledgment AY 2026-27. PAN: ABCDE1234F. e-Filing Ack No: 492019481029.",
    match_type: "keyword",
    exists: true,
    doc_type: "tax",
    facts: [
      { kind: "date", label: "Assessment Year", value: "2026-27" },
      { kind: "id", label: "Ack Number", value: "492019481029" },
      { kind: "id", label: "PAN", value: "ABCDE1234F" },
    ],
  },
  {
    filename: "Annual_Medical_Health_Checkup_Report.pdf",
    path: "D:\\Medical\\Reports\\Annual_Medical_Health_Checkup_Report.pdf",
    breadcrumb: ["Medical", "Reports", "Annual_Medical_Health_Checkup_Report.pdf"],
    source: "local file",
    modified: "2026-09-10",
    snippet: "Comprehensive Annual Health Checkup and Lipid Profile. Lab: Thyrocare Diagnostics. Overall health parameters normal.",
    match_type: "keyword",
    exists: true,
    doc_type: "medical",
    facts: [
      { kind: "date", label: "Report Date", value: "2026-09-10", value_date: "2026-09-10" },
      { kind: "name", label: "Facility", value: "Thyrocare Diagnostics" },
      { kind: "id", label: "Report ID", value: "THY-2026-881" },
    ],
  },
  {
    filename: "Resume_Software_Developer_Profile.pdf",
    path: "D:\\Career\\Documents\\Resume_Software_Developer_Profile.pdf",
    breadcrumb: ["Career", "Documents", "Resume_Software_Developer_Profile.pdf"],
    source: "local file",
    modified: "2026-10-05",
    snippet: "Curriculum Vitae / Resume. Senior Full-Stack Software Developer. Skills: Python, React, TypeScript, SQLite, Machine Learning.",
    match_type: "keyword",
    exists: true,
    doc_type: "career",
    facts: [
      { kind: "name", label: "Role", value: "Software Developer" },
      { kind: "date", label: "Updated", value: "2026-10-05", value_date: "2026-10-05" },
    ],
  },
];

// Common stop words to ignore during word scoring to prevent false positive matches
const STOP_WORDS = new Set([
  "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
  "in", "on", "at", "to", "for", "of", "with", "by", "from", "about",
  "and", "or", "so", "if", "as", "what", "when", "where", "who", "which",
  "why", "how", "can", "could", "should", "would", "my", "me", "mine",
  "our", "ours", "your", "yours", "his", "her", "their", "its", "this",
  "that", "these", "those", "please", "kindly", "show", "find", "get",
  "search", "open", "check", "look", "tell", "give", "want", "need",
  "document", "documents", "file", "files", "record", "records", "pdf",
  "it", "do", "does", "did", "have", "has", "had", "all", "any", "some",
  // Hindi / Hinglish stopwords
  "mera", "meri", "mere", "mujhe", "mujhko", "hum", "humara", "humari",
  "kahan", "kidhar", "kab", "kaise", "kyun", "kya", "konsa", "konsi",
  "hai", "hain", "tha", "thi", "the", "ka", "ki", "ke", "ko", "se",
  "par", "pe", "me", "mein", "aur", "ya", "toh", "bhi", "batao", "bata",
  "dekho", "dekh", "dhundo", "dhoondho", "nikalo", "kholo",
]);

// Semantic keyword mappings for domain expansion
const SYNONYM_MAP: Record<string, string[]> = {
  passport: ["passport", "pass", "identity", "id_document"],
  aadhaar: ["aadhaar", "aadhar", "adhar", "uidai", "uid", "identity", "id_document"],
  pan: ["pan", "pancard", "tax", "identity"],
  identity: ["identity", "id", "passport", "aadhaar", "pan", "license", "voter"],
  insurance: ["insurance", "policy", "mediclaim", "star", "health", "bima"],
  health: ["health", "medical", "checkup", "doctor", "hospital", "report", "insurance", "thyrocare"],
  medical: ["medical", "doctor", "hospital", "report", "checkup", "clinic", "prescription", "lipid"],
  ticket: ["ticket", "flight", "plane", "travel", "boarding", "indigo", "pnr", "del", "bom"],
  flight: ["flight", "ticket", "indigo", "travel", "plane", "pnr", "delhi", "mumbai"],
  travel: ["travel", "flight", "ticket", "boarding", "indigo", "booking"],
  bill: ["bill", "electricity", "electric", "power", "bses", "yamuna", "due", "utility", "invoice"],
  electricity: ["electricity", "electric", "bill", "bses", "yamuna", "power", "bijli", "light"],
  bijli: ["electricity", "bill", "bses", "power"],
  invoice: ["invoice", "bill", "payment", "amount", "bses", "tax"],
  warranty: ["warranty", "guarantee", "dell", "xps", "laptop", "support", "service", "hardware"],
  laptop: ["laptop", "dell", "xps", "computer", "warranty"],
  tax: ["tax", "itr", "taxes", "income", "acknowledgment", "pan", "assessment"],
  itr: ["itr", "tax", "income", "acknowledgment", "sahaj"],
  resume: ["resume", "cv", "curriculum", "career", "job", "developer", "profile"],
  cv: ["cv", "resume", "career", "profile"],
};

export function performClientSearch(query: string, sessionId: string): AskResponse {
  const rawQ = (query || "").trim();
  const q = rawQ.toLowerCase();

  // Extract clean words (strip punctuation, keep alphanumeric)
  const allTokens = q.match(/[a-z0-9]+/g) || [];
  // Filter out stop words for meaningful scoring
  const keywords = allTokens.filter((token) => !STOP_WORDS.has(token) && token.length >= 2);

  const isUrgent =
    q.includes("urgent") ||
    q.includes("emergency") ||
    q.includes("jaldi") ||
    q.includes("kho gaya") ||
    q.includes("lost") ||
    q.includes("turant") ||
    q.includes("fast");

  // Merge laptop local indexed files (if permission was granted) with built-in documents
  const userLocalFiles = getStoredLocalFiles();
  const folderState = getLocalFolderState();
  const allDocs = [...userLocalFiles, ...SAMPLE_DOCUMENTS];

  // If query is empty or only whitespace/punctuation
  if (keywords.length === 0 && allTokens.length === 0) {
    return {
      tone: "neutral",
      urgency: "normal",
      message: "Please type a document name, keyword, or question (e.g., passport, health insurance, electricity bill, flight ticket, warranty).",
      session_id: sessionId,
      results: [],
    };
  }

  // Handle conversational greetings & FAQs naturally like a human
  if (/^(hi|hello|hey|hola|namaste|greetings|good morning|good evening)\b[!.? ]*$/i.test(q)) {
    return {
      tone: "friendly",
      urgency: "normal",
      message: "Hello! How can I help you? Ask me to find any document on your laptop, like your passport, electricity bill, or health insurance.",
      session_id: sessionId,
      results: [],
    };
  }

  if (/^(who are you|what can you do|what is this|help|how does this work)\b[!.? ]*$/i.test(q)) {
    return {
      tone: "friendly",
      urgency: "normal",
      message: "I'm Dyanphil, your offline private document assistant. I can help you find and open personal documents stored on your laptop with 100% on-device privacy.",
      session_id: sessionId,
      results: [],
    };
  }

  if (/^(thanks|thank you|thx|dhanyawad|shukriya)\b[!.? ]*$/i.test(q)) {
    return {
      tone: "friendly",
      urgency: "normal",
      message: "You're very welcome! Let me know if you need any other documents or files.",
      session_id: sessionId,
      results: [],
    };
  }

  // Expand keywords with synonyms
  const searchTerms = new Set<string>();
  for (const token of keywords) {
    searchTerms.add(token);
    // Add singular version if ends with 's'
    if (token.length > 3 && token.endsWith("s")) {
      searchTerms.add(token.slice(0, -1));
    }
    // Add known synonyms
    if (SYNONYM_MAP[token]) {
      for (const syn of SYNONYM_MAP[token]) {
        searchTerms.add(syn);
      }
    }
  }

  // Score each document based on exact word boundaries & term frequency
  const scored = allDocs.map((doc) => {
    let score = 0;
    const filenameLow = doc.filename.toLowerCase();
    const snippetLow = doc.snippet.toLowerCase();
    const docTypeLow = (doc.doc_type || "").toLowerCase();
    const docText = `${filenameLow} ${docTypeLow} ${snippetLow}`;

    // 1. Whole exact phrase match
    if (rawQ.length >= 3 && docText.includes(q)) {
      score += 40;
    }

    // 2. Term scoring
    for (const term of searchTerms) {
      // Regex word-boundary test to prevent partial word false-positives
      const wordRegex = new RegExp(`\\b${term}\\b`, "i");

      // Filename matches (highest weight)
      if (wordRegex.test(filenameLow)) {
        score += 25;
      } else if (filenameLow.includes(term) && term.length >= 4) {
        score += 15;
      }

      // Document type match
      if (wordRegex.test(docTypeLow)) {
        score += 18;
      }

      // Facts match (label or value)
      for (const f of doc.facts || []) {
        const fText = `${f.label} ${f.value}`.toLowerCase();
        if (wordRegex.test(fText)) {
          score += 20;
        } else if (fText.includes(term) && term.length >= 4) {
          score += 10;
        }
      }

      // Snippet / content match
      if (wordRegex.test(snippetLow)) {
        score += 12;
      } else if (snippetLow.includes(term) && term.length >= 4) {
        score += 6;
      }
    }

    // Boost real files from the user's laptop
    if (doc.source === "laptop local" && score > 0) {
      score += 15;
    }

    return { doc, score };
  });

  const matches = scored
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((s) => ({
      ...s.doc,
      snippet: maskSensitiveData(s.doc.snippet),
      facts: s.doc.facts?.map((f) => ({
        ...f,
        value: maskSensitiveData(f.value),
      })),
    }));

  // Enforce image policy: return images only when query contains image keywords or fewer than 3 docs
  const IMAGE_WORDS = new Set(["photo", "picture", "image", "screenshot", "png", "jpg", "jpeg", "pic", "tasveer"]);
  const hasImageWord = allTokens.some((t) => IMAGE_WORDS.has(t) || IMAGE_WORDS.has(t.replace(/s$/, "")));

  const isImageDoc = (item: SearchResultItem) => {
    const ext = (item.filename.split(".").pop() || "").toLowerCase();
    return ["png", "jpg", "jpeg"].includes(ext) || item.doc_type === "image" || item.doc_type === "photo";
  };

  let filteredMatches = matches;
  if (!hasImageWord) {
    const docs = matches.filter((m) => !isImageDoc(m));
    const images = matches.filter((m) => isImageDoc(m));
    if (docs.length >= 3) {
      filteredMatches = docs;
    } else {
      filteredMatches = [...docs, ...images];
    }
  }

  // IF NO MATCHES: Return empty list and clean truthful message (never return unrelated default documents)
  if (filteredMatches.length === 0) {
    return {
      tone: isUrgent ? "urgent" : "neutral",
      urgency: isUrgent ? "high" : "normal",
      message: `I couldn't find any documents matching "${rawQ}" on your machine. Try searching for specific document names (like passport, insurance, electricity bill, flight ticket, warranty) or grant folder permission above to index your laptop files.`,
      session_id: sessionId,
      results: [],
    };
  }

  const results = filteredMatches.slice(0, 5);
  const top = results[0];
  const cleanName = top.filename.replace(/_/g, " ").replace(/\.(pdf|docx|txt|xlsx)$/i, "");
  const foundUserLaptopFiles = results.some((m) => m.source === "laptop local");

  // Detect specific fact questions (expiry, number/id, amount)
  const isAskingExpiry = q.includes("expire") || q.includes("expiry") || q.includes("valid") || q.includes("due date") || q.includes("renewal") || q.includes("kab tak");
  const isAskingNumber = q.includes("number") || q.includes("no") || q.includes("id") || q.includes("pnr") || q.includes("code") || q.includes("tag");
  const isAskingAmount = q.includes("how much") || q.includes("amount") || q.includes("cost") || q.includes("bill") || q.includes("price") || q.includes("kitna");

  let message = "";

  if (isAskingExpiry) {
    const dateFact = top.facts?.find((f) => f.kind === "date" || f.label.toLowerCase().includes("expir") || f.label.toLowerCase().includes("valid") || f.label.toLowerCase().includes("due"));
    if (dateFact) {
      message = `For your ${cleanName}, the ${dateFact.label.toLowerCase()} is ${dateFact.value}. I've attached your document below.`;
    }
  } else if (isAskingNumber) {
    const idFact = top.facts?.find((f) => f.kind === "id" || f.label.toLowerCase().includes("no") || f.label.toLowerCase().includes("number") || f.label.toLowerCase().includes("pnr") || f.label.toLowerCase().includes("tag"));
    if (idFact) {
      message = `Here is your ${cleanName}. The ${idFact.label.toLowerCase()} is ${idFact.value}.`;
    }
  } else if (isAskingAmount) {
    const amtFact = top.facts?.find((f) => f.kind === "amount" || f.label.toLowerCase().includes("amount") || f.label.toLowerCase().includes("sum"));
    if (amtFact) {
      message = `For your ${cleanName}, the total ${amtFact.label.toLowerCase()} is ${amtFact.value}.`;
    }
  }

  if (!message) {
    if (foundUserLaptopFiles) {
      message = `Here are ${results.length} document(s) from your laptop folder (${folderState.folderName || "Local"}). Top match: ${cleanName}.`;
    } else if (results.length === 1) {
      message = `Here is your ${cleanName}. Document details and actions are ready below.`;
    } else {
      message = `Here are the top documents matching "${rawQ}". Leading file: ${cleanName}.`;
    }
  }

  return {
    tone: isUrgent ? "urgent" : "neutral",
    urgency: isUrgent ? "high" : "normal",
    message,
    session_id: sessionId,
    results,
  };
}

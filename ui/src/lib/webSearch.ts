// Internet & Research Paper Search Engine (arXiv + Wikipedia + Optional Gemini AI)
import { AskResponse, SearchResultItem } from "@/components/ResultsPanel";
import { maskSensitiveData } from "@/lib/masking";

const STORAGE_KEY_GEMINI_KEY = "dyanphil_gemini_api_key";

export function getStoredApiKey(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(STORAGE_KEY_GEMINI_KEY) || "";
}

export function saveApiKey(key: string): void {
  if (typeof localStorage === "undefined") return;
  if (!key.trim()) {
    localStorage.removeItem(STORAGE_KEY_GEMINI_KEY);
  } else {
    localStorage.setItem(STORAGE_KEY_GEMINI_KEY, key.trim());
  }
}

/**
 * Search scientific research papers from arXiv via their public OpenSearch API
 */
async function searchArxiv(query: string, maxResults = 5): Promise<SearchResultItem[]> {
  const cleanQ = encodeURIComponent(query.trim());
  const url = `https://export.arxiv.org/api/query?search_query=all:${cleanQ}&start=0&max_results=${maxResults}&sortBy=relevance`;

  try {
    const res = await fetch(url);
    if (!res.ok) return [];
    const xmlText = await res.text();
    const parser = new DOMParser();
    const xml = parser.parseFromString(xmlText, "application/xml");
    const entries = Array.from(xml.querySelectorAll("entry"));

    const items: SearchResultItem[] = [];

    for (const entry of entries) {
      const title = entry.querySelector("title")?.textContent?.replace(/\s+/g, " ").trim() || "Untitled Research Paper";
      const summary = entry.querySelector("summary")?.textContent?.replace(/\s+/g, " ").trim() || "";
      const published = entry.querySelector("published")?.textContent?.slice(0, 10) || "";
      const idUrl = entry.querySelector("id")?.textContent?.trim() || "";

      // Extract direct links
      let paperUrl = idUrl;
      let pdfUrl = "";
      const links = Array.from(entry.querySelectorAll("link"));
      for (const link of links) {
        const href = link.getAttribute("href") || "";
        const titleAttr = link.getAttribute("title");
        if (titleAttr === "pdf" || href.includes("/pdf/")) {
          pdfUrl = href.endsWith(".pdf") ? href : `${href}.pdf`;
        } else if (link.getAttribute("rel") === "alternate") {
          paperUrl = href;
        }
      }
      if (!pdfUrl && idUrl.includes("/abs/")) {
        pdfUrl = idUrl.replace("/abs/", "/pdf/") + ".pdf";
      }

      // Authors
      const authors = Array.from(entry.querySelectorAll("author > name"))
        .map((n) => n.textContent?.trim() || "")
        .filter(Boolean);
      const authorsStr = authors.slice(0, 3).join(", ") + (authors.length > 3 ? " et al." : "");

      // Primary Category
      const cat = entry.querySelector("primary_category")?.getAttribute("term") || "Research";

      items.push({
        filename: `${title}.pdf`,
        path: paperUrl || idUrl,
        breadcrumb: ["Internet", "Research Papers", `arXiv:${cat}`, `${title.slice(0, 30)}...`],
        source: "arXiv Research",
        modified: published,
        snippet: summary.slice(0, 320) + (summary.length > 320 ? "..." : ""),
        match_type: "research",
        exists: true,
        doc_type: "research_paper",
        url: paperUrl || idUrl,
        pdf_url: pdfUrl,
        facts: [
          { kind: "authors", label: "Authors", value: authorsStr || "Researchers" },
          { kind: "date", label: "Published", value: published, value_date: published },
          { kind: "category", label: "Category", value: `arXiv:${cat}` },
        ],
      });
    }

    return items;
  } catch (err) {
    console.warn("arXiv search failed:", err);
    return [];
  }
}

/**
 * Search Wikipedia for encyclopedic background and topic information
 */
async function searchWikipedia(query: string, maxResults = 3): Promise<SearchResultItem[]> {
  const cleanQ = encodeURIComponent(query.trim());
  const url = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${cleanQ}&format=json&origin=*&srlimit=${maxResults}`;

  try {
    const res = await fetch(url);
    if (!res.ok) return [];
    const data = await res.json();
    const hits = data?.query?.search || [];

    return hits.map((hit: any) => {
      const title = hit.title || "Wikipedia Article";
      const cleanSnippet = (hit.snippet || "").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
      const pageUrl = `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/\s+/g, "_"))}`;
      const pubDate = (hit.timestamp || "").slice(0, 10);

      return {
        filename: `${title}.html`,
        path: pageUrl,
        breadcrumb: ["Internet", "Knowledge", "Wikipedia", title],
        source: "Wikipedia Knowledge",
        modified: pubDate,
        snippet: cleanSnippet || `Encyclopedic information regarding ${title}.`,
        match_type: "knowledge",
        exists: true,
        doc_type: "article",
        url: pageUrl,
        facts: [
          { kind: "source", label: "Source", value: "Wikipedia" },
          { kind: "words", label: "Word Count", value: String(hit.wordcount || "1000+") },
          { kind: "date", label: "Last Updated", value: pubDate, value_date: pubDate },
        ],
      };
    });
  } catch (err) {
    console.warn("Wikipedia search failed:", err);
    return [];
  }
}

/**
 * Synthesize answer using Google Gemini API if user configured an API key
 */
async function askGemini(apiKey: string, question: string, contextItems: SearchResultItem[]): Promise<string> {
  if (!apiKey.trim()) return "";

  const contextText = contextItems
    .slice(0, 5)
    .map(
      (item, i) =>
        `[Source ${i + 1}]: "${item.filename}" (${item.source}, ${item.modified})\nAbstract/Summary: ${item.snippet}\nLink: ${item.url || item.path}`
    )
    .join("\n\n");

  const prompt = `You are Dyanphil Research AI. A user asked: "${question}".

Here are the top scientific papers and web sources retrieved for this query:
${contextText}

Provide a direct, thorough, and well-structured answer explaining the requested concepts, citing specific papers or sources by name, and highlighting key findings. Keep it factual, informative, and easy to read.`;

  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey.trim()}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: {
            temperature: 0.3,
            maxOutputTokens: 1000,
          },
        }),
      }
    );

    if (!res.ok) {
      console.warn("Gemini API returned error:", res.status);
      return "";
    }

    const data = await res.json();
    const candidateText = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    return candidateText || "";
  } catch (err) {
    console.warn("Gemini API call failed:", err);
    return "";
  }
}

/**
 * Execute Internet & Research Paper search across arXiv, Wikipedia, and optional Gemini synthesis
 */
export async function performInternetSearch(query: string, sessionId: string): Promise<AskResponse> {
  const rawQ = (query || "").trim();
  if (!rawQ) {
    return {
      tone: "neutral",
      urgency: "normal",
      message: "Please enter a research topic, academic subject, or question to search the internet and research papers.",
      session_id: sessionId,
      results: [],
    };
  }

  // 1. Fetch from arXiv and Wikipedia in parallel
  const [arxivResults, wikiResults] = await Promise.all([
    searchArxiv(rawQ, 4),
    searchWikipedia(rawQ, 3),
  ]);

  const combinedResults: SearchResultItem[] = [...arxivResults, ...wikiResults];

  if (combinedResults.length === 0) {
    return {
      tone: "neutral",
      urgency: "normal",
      message: `No online research papers or encyclopedia entries were found for "${rawQ}". Try searching with alternate academic terms or check your internet connection.`,
      session_id: sessionId,
      results: [],
    };
  }

  // 2. Optional Gemini AI Synthesis
  const apiKey = getStoredApiKey();
  let aiSummary = "";
  if (apiKey) {
    aiSummary = await askGemini(apiKey, rawQ, combinedResults);
  }

  let finalMessage = "";
  if (aiSummary) {
    finalMessage = aiSummary;
  } else {
    const paperCount = arxivResults.length;
    const wikiCount = wikiResults.length;
    finalMessage = `Found ${combinedResults.length} online research source(s) for "${rawQ}" (${paperCount} arXiv research paper${paperCount === 1 ? "" : "s"}, ${wikiCount} encyclopedia article${wikiCount === 1 ? "" : "s"}). Click any card to read online or download the full PDF.`;
  }

  return {
    tone: "neutral",
    urgency: "normal",
    message: finalMessage,
    session_id: sessionId,
    results: combinedResults,
  };
}

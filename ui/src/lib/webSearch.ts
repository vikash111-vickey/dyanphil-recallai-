// Internet & Scholarly Research Engine (IEEE Xplore + OpenAlex + arXiv + Wikipedia + Optional Gemini AI)
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

function cleanHtmlTags(str: string): string {
  if (!str) return "";
  return str.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}

/**
 * Search IEEE Xplore publications via official CrossRef DOI prefix 10.1109
 * (covers IEEE Transactions, Journals, Magazines, and Conferences)
 */
async function searchIeeeXplore(query: string, maxResults = 4): Promise<SearchResultItem[]> {
  const cleanQ = encodeURIComponent(query.trim());
  const url = `https://api.crossref.org/works?query=${cleanQ}&filter=prefix:10.1109&rows=${maxResults * 2}`;

  try {
    const res = await fetch(url, { signal: AbortSignal.timeout?.(6000) });
    if (!res.ok) return [];
    const data = await res.json();
    const items = data?.message?.items || [];

    const results: SearchResultItem[] = [];

    for (const it of items) {
      if (results.length >= maxResults) break;
      const title = it.title?.[0] || "IEEE Publication";
      // Skip generic committee / index / title pages
      if (/organizing committee|program committee|table of contents|author index|preface/i.test(title)) {
        continue;
      }

      // Authors
      const authors = (it.author || [])
        .map((a: any) => `${a.given || ""} ${a.family || ""}`.trim())
        .filter(Boolean);
      const authorsStr = authors.slice(0, 3).join(", ") + (authors.length > 3 ? " et al." : "");

      const container = it["container-title"]?.[0] || "IEEE Xplore";
      const doi = it.DOI || "";
      const year = it.issued?.["date-parts"]?.[0]?.[0] || it.created?.["date-parts"]?.[0]?.[0] || "";

      // Construct accurate IEEE Xplore document link
      let ieeeUrl = it.resource?.primary?.URL;
      if (!ieeeUrl || !ieeeUrl.includes("ieeexplore.ieee.org")) {
        ieeeUrl = doi ? `https://doi.org/${doi}` : `https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText=${cleanQ}`;
      }

      let pdfUrl = "";
      if (it.link && Array.isArray(it.link)) {
        for (const l of it.link) {
          if (l.URL && l.URL.includes(".pdf")) {
            pdfUrl = l.URL;
            break;
          }
        }
      }

      const rawAbstract = cleanHtmlTags(it.abstract || "");
      const snippet = rawAbstract
        ? rawAbstract.slice(0, 320) + (rawAbstract.length > 320 ? "..." : "")
        : `Published in ${container}${year ? ` (${year})` : ""}. IEEE DOI: ${doi || "10.1109"}. Access full text and citations on IEEE Xplore.`;

      results.push({
        filename: `${title}.pdf`,
        path: ieeeUrl,
        breadcrumb: ["Internet", "IEEE Xplore", container.slice(0, 35), `${title.slice(0, 30)}...`],
        source: "IEEE Xplore",
        modified: year ? String(year) : "Recent",
        snippet,
        match_type: "ieee",
        exists: true,
        doc_type: "ieee_paper",
        url: ieeeUrl,
        pdf_url: pdfUrl,
        facts: [
          { kind: "journal", label: "IEEE Venue", value: container.slice(0, 50) },
          { kind: "authors", label: "Authors", value: authorsStr || "IEEE Authors" },
          { kind: "doi", label: "DOI", value: doi || "10.1109" },
        ],
      });
    }

    return results;
  } catch (err) {
    console.warn("IEEE Xplore search failed:", err);
    return [];
  }
}

/**
 * Search OpenAlex global scholarly database (covers Nature, Science, ACM, Springer, Elsevier, Oxford)
 */
async function searchOpenAlex(query: string, maxResults = 3): Promise<SearchResultItem[]> {
  const cleanQ = encodeURIComponent(query.trim());
  const url = `https://api.openalex.org/works?search=${cleanQ}&per-page=${maxResults}`;

  try {
    const res = await fetch(url, { signal: AbortSignal.timeout?.(6000) });
    if (!res.ok) return [];
    const data = await res.json();
    const works = data?.results || [];

    const items: SearchResultItem[] = [];

    for (const w of works) {
      const title = w.display_name || w.title || "Academic Research Paper";
      const pubYear = w.publication_year ? String(w.publication_year) : "";
      const publisher = w.primary_location?.source?.display_name || "Peer-Reviewed Academic Publisher";

      // Landing page & open-access PDF
      const landingUrl = w.primary_location?.landing_page_url || (w.doi ? `https://doi.org/${w.doi.replace(/^https?:\/\/doi.org\//, "")}` : w.id);
      const pdfUrl = w.open_access?.oa_url || w.primary_location?.pdf_url || "";

      // Authors
      const authors = (w.authorships || [])
        .map((a: any) => a.author?.display_name)
        .filter(Boolean)
        .slice(0, 3)
        .join(", ");

      const topic = w.primary_topic?.display_name || "";
      const field = w.primary_topic?.field?.display_name || "";
      const citedCount = w.cited_by_count ? `Cited by ${w.cited_by_count} papers` : "";

      const snippet = [
        topic ? `Research Area: ${topic}.` : "",
        field ? `Field: ${field}.` : "",
        citedCount ? `${citedCount}.` : "",
        `Published in ${publisher}.`,
      ].filter(Boolean).join(" ");

      items.push({
        filename: `${title}.pdf`,
        path: landingUrl || w.id,
        breadcrumb: ["Internet", "Scholarly Index", publisher.slice(0, 30), `${title.slice(0, 30)}...`],
        source: publisher.slice(0, 30) || "Academic Research",
        modified: pubYear || "Recent",
        snippet: snippet || `Published in ${publisher}. Access full peer-reviewed text online.`,
        match_type: "research",
        exists: true,
        doc_type: "research_paper",
        url: landingUrl || w.id,
        pdf_url: pdfUrl,
        facts: [
          { kind: "authors", label: "Authors", value: authors || "Researchers" },
          { kind: "publisher", label: "Publisher", value: publisher.slice(0, 40) },
          { kind: "date", label: "Year", value: pubYear, value_date: pubYear },
        ],
      });
    }

    return items;
  } catch (err) {
    console.warn("OpenAlex search failed:", err);
    return [];
  }
}

/**
 * Search scientific research papers from arXiv via CORS-enabled OpenAlex repository index
 * Eliminates browser CORS errors from export.arxiv.org
 */
async function searchArxiv(query: string, maxResults = 3): Promise<SearchResultItem[]> {
  const cleanQ = encodeURIComponent(query.trim());
  // OpenAlex source ID s4306400194 is arXiv.org - supports CORS with access-control-allow-origin: *
  const url = `https://api.openalex.org/works?search=${cleanQ}&filter=locations.source.id:s4306400194&per-page=${maxResults}`;

  try {
    const res = await fetch(url, { signal: AbortSignal.timeout?.(6000) });
    if (!res.ok) return [];
    const data = await res.json();
    const works = data?.results || [];

    const items: SearchResultItem[] = [];

    for (const w of works) {
      const title = w.display_name || w.title || "arXiv Preprint";
      const pubYear = w.publication_year ? String(w.publication_year) : "";
      const landingUrl = w.primary_location?.landing_page_url || (w.doi ? `https://doi.org/${w.doi.replace(/^https?:\/\/doi.org\//, "")}` : w.id);
      const pdfUrl = w.open_access?.oa_url || w.primary_location?.pdf_url || "";

      const authors = (w.authorships || [])
        .map((a: any) => a.author?.display_name)
        .filter(Boolean)
        .slice(0, 3)
        .join(", ");
      const authorsStr = authors ? (w.authorships?.length > 3 ? `${authors} et al.` : authors) : "arXiv Researchers";

      const topic = w.primary_topic?.display_name || "";
      const field = w.primary_topic?.field?.display_name || "";
      const citedCount = w.cited_by_count ? `Cited by ${w.cited_by_count} papers` : "";

      const snippet = [
        topic ? `Topic: ${topic}.` : "",
        field ? `Field: ${field}.` : "",
        citedCount ? `${citedCount}.` : "",
        "Preprint indexed from arXiv.org. Access full paper online or download open-access PDF.",
      ].filter(Boolean).join(" ");

      items.push({
        filename: `${title}.pdf`,
        path: landingUrl || w.id,
        breadcrumb: ["Internet", "Research Papers", "arXiv.org", `${title.slice(0, 30)}...`],
        source: "arXiv.org",
        modified: pubYear || "Recent",
        snippet,
        match_type: "research",
        exists: true,
        doc_type: "research_paper",
        url: landingUrl || w.id,
        pdf_url: pdfUrl,
        facts: [
          { kind: "authors", label: "Authors", value: authorsStr },
          { kind: "source", label: "Repository", value: "arXiv.org" },
          { kind: "date", label: "Year", value: pubYear, value_date: pubYear },
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
 * Search Wikipedia for encyclopedic background and definitions
 */
async function searchWikipedia(query: string, maxResults = 2): Promise<SearchResultItem[]> {
  const cleanQ = encodeURIComponent(query.trim());
  const url = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${cleanQ}&format=json&origin=*&srlimit=${maxResults}`;

  try {
    const res = await fetch(url, { signal: AbortSignal.timeout?.(5000) });
    if (!res.ok) return [];
    const data = await res.json();
    const hits = data?.query?.search || [];

    return hits.map((hit: any) => {
      const title = hit.title || "Wikipedia Article";
      const cleanSnippet = cleanHtmlTags(hit.snippet || "");
      const pageUrl = `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/\s+/g, "_"))}`;
      const pubDate = (hit.timestamp || "").slice(0, 10);

      return {
        filename: `${title}.html`,
        path: pageUrl,
        breadcrumb: ["Internet", "Knowledge", "Wikipedia", title],
        source: "Wikipedia",
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
    .slice(0, 6)
    .map(
      (item, i) =>
        `[Source ${i + 1}]: "${item.filename}" (${item.source}, ${item.modified})\nAbstract/Summary: ${item.snippet}\nLink: ${item.url || item.path}`
    )
    .join("\n\n");

  const prompt = `You are Dyanphil Scientific Research Assistant. A user asked: "${question}".

Here are peer-reviewed research papers and scholarly sources retrieved from IEEE Xplore, OpenAlex, arXiv, and encyclopedic literature:
${contextText}

Provide an authoritative, clear, and comprehensive answer explaining the concepts, citing the relevant papers (especially IEEE Xplore or journal publications) by name with their key findings. Include technical details requested by the user.`;

  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey.trim()}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: AbortSignal.timeout?.(12000),
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: {
            temperature: 0.3,
            maxOutputTokens: 1200,
          },
        }),
      }
    );

    if (!res.ok) {
      console.warn("Gemini API error status:", res.status);
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
 * Execute deep Internet & Scholarly Research across IEEE Xplore, OpenAlex, arXiv, Wikipedia & Gemini AI
 */
export async function performInternetSearch(query: string, sessionId: string): Promise<AskResponse> {
  const rawQ = (query || "").trim();
  if (!rawQ) {
    return {
      tone: "neutral",
      urgency: "normal",
      message: "Please enter any research question or topic (e.g. quantum computing, deep learning, wireless networks, biomedical algorithms) to search IEEE Xplore, arXiv, and the internet.",
      session_id: sessionId,
      results: [],
    };
  }

  // 1. Fetch from IEEE Xplore, OpenAlex, arXiv, and Wikipedia simultaneously
  const [ieeeRes, openAlexRes, arxivRes, wikiRes] = await Promise.allSettled([
    searchIeeeXplore(rawQ, 4),
    searchOpenAlex(rawQ, 3),
    searchArxiv(rawQ, 3),
    searchWikipedia(rawQ, 2),
  ]);

  const ieeeItems = ieeeRes.status === "fulfilled" ? ieeeRes.value : [];
  const openAlexItems = openAlexRes.status === "fulfilled" ? openAlexRes.value : [];
  const arxivItems = arxivRes.status === "fulfilled" ? arxivRes.value : [];
  const wikiItems = wikiRes.status === "fulfilled" ? wikiRes.value : [];

  // IEEE papers prioritized first, then open research, then arXiv, then Wikipedia
  const combinedResults: SearchResultItem[] = [
    ...ieeeItems,
    ...openAlexItems,
    ...arxivItems,
    ...wikiItems,
  ];

  if (combinedResults.length === 0) {
    const ieeePortalLink = `https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText=${encodeURIComponent(rawQ)}`;
    return {
      tone: "neutral",
      urgency: "normal",
      message: `No direct scientific papers were found for "${rawQ}". You can search IEEE Xplore directly at: ${ieeePortalLink}`,
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
    const ieeeCount = ieeeItems.length;
    const scholarCount = openAlexItems.length + arxivItems.length;
    const ieeeNote = ieeeCount > 0 ? `${ieeeCount} IEEE Xplore publication${ieeeCount === 1 ? "" : "s"}` : "";
    const scholarNote = scholarCount > 0 ? `${scholarCount} scientific research paper${scholarCount === 1 ? "" : "s"}` : "";
    const breakdown = [ieeeNote, scholarNote].filter(Boolean).join(", ");

    finalMessage = `Found ${combinedResults.length} internet research papers and sources for "${rawQ}" (${breakdown || "Scholarly publications"}). Click any card to read directly on IEEE Xplore, view publisher full text, or download PDF.`;
  }

  return {
    tone: "neutral",
    urgency: "normal",
    message: finalMessage,
    session_id: sessionId,
    results: combinedResults,
  };
}

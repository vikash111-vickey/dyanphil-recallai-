import http from "node:http"
import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

let cachedSessionToken: string | null = null

function fetchSessionToken(): Promise<string> {
  return new Promise((resolve) => {
    if (cachedSessionToken) {
      return resolve(cachedSessionToken)
    }
    const req = http.get("http://127.0.0.1:8000/", (res) => {
      const setCookies = res.headers["set-cookie"]
      if (setCookies) {
        for (const cookieStr of setCookies) {
          const match = cookieStr.match(/session_token=([^;]+)/)
          if (match) {
            cachedSessionToken = match[1]
            return resolve(cachedSessionToken)
          }
        }
      }
      resolve("")
    })
    req.on("error", () => resolve(""))
  })
}

function sessionCookieDevPlugin(): Plugin {
  return {
    name: "session-cookie-dev",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.url === "/" || req.url === "/index.html") {
          const token = await fetchSessionToken()
          if (token) {
            res.setHeader(
              "Set-Cookie",
              `session_token=${token}; Path=/; SameSite=Strict`,
            )
          }
        }
        next()
      })
    },
  }
}

const proxyEntry = {
  target: "http://127.0.0.1:8000",
  changeOrigin: true,
  configure: (proxy: any) => {
    proxy.on("proxyReq", async (proxyReq: any, req: any) => {
      const existingCookie = req.headers.cookie || ""
      if (!existingCookie.includes("session_token=")) {
        const token = await fetchSessionToken()
        if (token) {
          const newCookie = existingCookie
            ? `${existingCookie}; session_token=${token}`
            : `session_token=${token}`
          proxyReq.setHeader("cookie", newCookie)
        }
      }
    })
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), sessionCookieDevPlugin()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": proxyEntry,
      "/ask": proxyEntry,
      "/open": proxyEntry,
      "/expiring": proxyEntry,
      "/vault": proxyEntry,
      "/settings": proxyEntry,
      "/index": proxyEntry,
      "/ocr": proxyEntry,
      "/data": proxyEntry,
      "/privacy": proxyEntry,
      "/health": proxyEntry,
      "/gmail": proxyEntry,
    },
  },
})

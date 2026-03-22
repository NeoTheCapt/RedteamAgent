/**
 * Engagement Hooks Plugin for RedteamOpencode
 *
 * Provides session-aware engagement tracking, scope enforcement,
 * and automatic logging for red team operations.
 *
 * Event handlers:
 * - session.created: Detect and offer to resume active engagements
 * - chat.message: Track current agent for log attribution
 * - tool.execute.before: Heuristic scope enforcement for bash commands
 * - tool.execute.after: Auto-log bash commands to engagement log.md
 * - file.edited: Warn when log.md is modified directly
 */

import type { PluginInput } from "@opencode-ai/plugin"
import { appendFile, readFile, readdir } from "node:fs/promises"
import path from "node:path"

interface ScopeJson {
  target: string
  hostname: string
  port: number
  scope: string[]
  mode: string
  status: string
  start_time: string
  phases_completed: string[]
  current_phase: string
}

export const EngagementHooksPlugin = async ({
  client,
  $,
  directory,
  worktree,
}: PluginInput) => {
  const root = worktree || directory

  const log = (level: "debug" | "info" | "warn" | "error", message: string) =>
    client.app.log({ body: { service: "engagement", level, message } })

  // Track current agent for log attribution.
  // Updated by chat.message hook, consumed by tool.execute.after.
  let currentAgent = "operator"

  // Deduplication: track last logged command to prevent double-logging.
  // OpenCode may fire tool.execute.after multiple times for the same command.
  let lastLoggedCommand = ""
  let lastLoggedTimestamp = 0

  /** Localhost / loopback addresses — always allowed regardless of scope. */
  const LOCALHOST = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"])

  /**
   * Find the most recent engagement directory with the given status.
   * Returns the directory path or null.
   */
  const findActiveEngagement = async (): Promise<string | null> => {
    try {
      const engagementsDir = path.join(root, "engagements")
      const entries = await readdir(engagementsDir, { withFileTypes: true })
      const engagementDirs = entries
        .filter((entry) => entry.isDirectory())
        .map((entry) => path.join(engagementsDir, entry.name))
        .sort()
        .reverse()

      for (const engagementDir of engagementDirs) {
        try {
          const scopeFile = path.join(engagementDir, "scope.json")
          const content = await readFile(scopeFile, "utf8")
          const scope: ScopeJson = JSON.parse(content)
          if (scope.status === "in_progress") {
            return engagementDir
          }
        } catch {
          // Malformed scope.json, skip
        }
      }
    } catch {
      // No engagement directories found
    }
    return null
  }

  /**
   * Read and parse scope.json from an engagement directory.
   */
  const readScope = async (engagementDir: string): Promise<ScopeJson | null> => {
    try {
      const content = await readFile(path.join(engagementDir, "scope.json"), "utf8")
      return JSON.parse(content)
    } catch {
      return null
    }
  }

  /**
   * Extract URLs, hostnames, and IP addresses from a command string.
   * This is best-effort heuristic, not a security boundary.
   */
  const extractHostnames = (command: string): string[] => {
    const hosts: string[] = []

    // Match URLs like http://example.com or https://sub.example.com:8080/path
    const urlPattern = /https?:\/\/([a-zA-Z0-9._-]+(?::\d+)?)/g
    let match: RegExpExecArray | null
    while ((match = urlPattern.exec(command)) !== null) {
      hosts.push(match[1].replace(/:\d+$/, ""))
    }

    // Match bare hostnames after common tool names
    const toolTargetPattern = /(?:curl|wget|nmap|nikto|gobuster|ffuf|sqlmap|nuclei|httpx|dig|host|whois|nc|netcat)\s+(?:-[^\s]+\s+)*([a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,})/g
    while ((match = toolTargetPattern.exec(command)) !== null) {
      hosts.push(match[1])
    }

    // Match bare IP addresses (e.g., nmap 10.0.0.1, curl 192.168.1.1)
    const ipPattern = /\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/g
    while ((match = ipPattern.exec(command)) !== null) {
      hosts.push(match[1])
    }

    return [...new Set(hosts)]
  }

  /**
   * Check if a hostname matches any scope entry (supports wildcard prefixes).
   */
  const isInScope = (hostname: string, scopeList: string[]): boolean => {
    // Always allow localhost / loopback
    if (LOCALHOST.has(hostname)) return true

    return scopeList.some((entry) => {
      if (entry.startsWith("*.")) {
        const domain = entry.slice(2)
        return hostname === domain || hostname.endsWith(`.${domain}`)
      }
      return hostname === entry
    })
  }

  /**
   * Truncate a string to a maximum length, appending "..." if truncated.
   */
  const truncate = (str: string, maxLen: number): string => {
    if (str.length <= maxLen) return str
    return str.slice(0, maxLen) + "..."
  }

  return {
    /**
     * session.created
     *
     * On session start, check for an active engagement (most recent scope.json
     * with status "in_progress"). If found, read context files and notify.
     */
    "session.created": async () => {
      log("info", "[Engagement] Plugin loaded")

      const engagementDir = await findActiveEngagement()
      if (!engagementDir) {
        log("info", "[Engagement] No active engagement found")
        return
      }

      const scope = await readScope(engagementDir)
      if (!scope) return

      let logContent = ""
      let findingsContent = ""
      try {
        logContent = await readFile(path.join(engagementDir, "log.md"), "utf8")
      } catch {
        // log.md may not exist yet
      }
      try {
        findingsContent = await readFile(path.join(engagementDir, "findings.md"), "utf8")
      } catch {
        // findings.md may not exist yet
      }

      const logLines = logContent.trim().split("\n").length
      const findingCount = (findingsContent.match(/^## \[FINDING-/gm) || []).length

      let queueInfo = ""
      try {
        const statsOutput = await $`./scripts/dispatcher.sh ${path.join(engagementDir, "cases.db")} stats`.text()
        queueInfo = statsOutput.trim()
      } catch {
        queueInfo = "no queue"
      }

      log(
        "warn",
        `[Engagement] Active engagement found: ${scope.target}\n` +
          `  Phase: ${scope.current_phase} | Completed: ${(scope.phases_completed || []).join(", ") || "none"}\n` +
          `  Findings: ${findingCount} | Log: ${logLines} lines\n` +
          `  Queue: ${queueInfo}\n` +
          `  Use /resume to continue or /engage <url> to start fresh.`
      )
    },

    /**
     * chat.message
     *
     * Track which agent is currently active for log attribution.
     * The `agent` field in the input identifies the current agent.
     */
    "chat.message": async (
      input: {
        sessionID: string
        agent?: string
        model?: { providerID: string; modelID: string }
        messageID?: string
        variant?: string
      },
    ) => {
      if (input.agent) {
        currentAgent = input.agent
      }
    },

    /**
     * tool.execute.before
     *
     * For bash tool calls, extract hostnames/URLs from the command and
     * compare against the active engagement's scope list. Warn on
     * out-of-scope targets. This is heuristic/best-effort.
     * NOTE: OpenCode plugin API cannot block execution, only warn.
     */
    "tool.execute.before": async (
      input: { tool: string; args?: Record<string, unknown> }
    ) => {
      if (input.tool !== "bash") return

      const command = String(input.args?.command || input.args || "")
      if (!command) return

      const hostnames = extractHostnames(command)
      if (hostnames.length === 0) return

      const engagementDir = await findActiveEngagement()
      if (!engagementDir) return

      const scope = await readScope(engagementDir)
      if (!scope || !scope.scope || scope.scope.length === 0) return

      for (const hostname of hostnames) {
        if (!isInScope(hostname, scope.scope)) {
          log(
            "warn",
            `[Engagement] OUT OF SCOPE: "${hostname}" does not match any scope entry ` +
              `[${scope.scope.join(", ")}]. Agent: ${currentAgent}. Verify this is intentional.`
          )
        }
      }
    },

    /**
     * tool.execute.after
     *
     * For bash tool calls, append a timestamped entry to the active
     * engagement's log.md with the command, agent name, and truncated output.
     */
    "tool.execute.after": async (
      input: { tool: string; sessionID: string; callID: string; args: any },
      output: { title: string; output: string; metadata: any }
    ) => {
      if (input.tool !== "bash") return

      const command = String(input.args?.command || input.args || "")
      if (!command) return

      // Skip noise: pure file reads, git ops, test commands
      if (/^(cat |ls |git |echo |test |\[|pwd)/.test(command)) return

      // Deduplication: skip if same command was logged within the last 3 seconds.
      const now = Date.now()
      const commandKey = command.slice(0, 200)
      if (commandKey === lastLoggedCommand && now - lastLoggedTimestamp < 3000) {
        log("debug", "[Engagement] Skipping duplicate log entry")
        return
      }
      lastLoggedCommand = commandKey
      lastLoggedTimestamp = now

      // Try to extract engagement dir from the command itself
      let engagementDir: string | null = null
      const engMatch = command.match(/engagements\/[^\s"'\/]+/)
      if (engMatch) {
        const candidateDir = `${root}/${engMatch[0]}`
        try {
          await readFile(path.join(candidateDir, "log.md"), "utf8")
          engagementDir = candidateDir
        } catch {
          // Not a valid engagement dir, fall back
        }
      }
      if (!engagementDir) {
        engagementDir = await findActiveEngagement()
      }
      if (!engagementDir) return

      const outputStr = typeof output === "string"
        ? output
        : typeof output === "object" && output !== null
          ? (output.output || JSON.stringify(output))
          : String(output || "")

      const timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, "Z")
      const summary = truncate(outputStr.trim(), 500)
      const shortCmd = truncate(command, 200)

      const entry = [
        "",
        `## [${timestamp}] ${currentAgent} — Bash`,
        `**Command**: \`${shortCmd}\``,
        summary ? `**Output**: ${summary}` : "*No output*",
        "",
      ].join("\n")

      try {
        await appendFile(path.join(engagementDir, "log.md"), entry)
        log("debug", `[Engagement] Logged command to ${engagementDir}/log.md`)
      } catch (err) {
        log("warn", `[Engagement] Failed to append to log.md: ${err}`)
      }
    },

    /**
     * file.edited
     *
     * If the edited file path contains "log.md", warn the user that
     * the engagement log was modified directly.
     */
    "file.edited": async (event: { path: string }) => {
      if (event.path.includes("log.md")) {
        log(
          "warn",
          `[Engagement] Engagement log was modified directly: ${event.path}. ` +
            `The plugin auto-logs commands -- manual edits may cause inconsistencies.`
        )
      }
    },
  }
}

export default EngagementHooksPlugin

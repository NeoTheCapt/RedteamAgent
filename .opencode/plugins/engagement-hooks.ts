/**
 * Engagement Hooks Plugin for RedteamOpencode
 *
 * Provides session-aware engagement tracking, scope enforcement,
 * and automatic logging for red team operations.
 *
 * Event handlers:
 * - session.created: Detect and offer to resume active engagements
 * - tool.execute.before: Heuristic scope enforcement for bash commands
 * - tool.execute.after: Auto-log bash commands to engagement log.md
 * - file.edited: Warn when log.md is modified directly
 */

import type { PluginInput } from "@opencode-ai/plugin"

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

  // Deduplication: track last logged command to prevent double-logging.
  // OpenCode may fire tool.execute.after multiple times for the same command.
  let lastLoggedCommand = ""
  let lastLoggedTimestamp = 0

  /**
   * Find the most recent engagement directory with the given status.
   * Returns the directory path or null.
   */
  const findActiveEngagement = async (): Promise<string | null> => {
    try {
      // List engagement dirs sorted by modification time (newest first)
      const result = await $`ls -1dt ${root}/engagements/*/scope.json 2>/dev/null`.text()
      const scopeFiles = result.trim().split("\n").filter(Boolean)

      for (const scopeFile of scopeFiles) {
        try {
          const content = await $`cat ${scopeFile}`.text()
          const scope: ScopeJson = JSON.parse(content)
          if (scope.status === "in_progress") {
            // Return the directory (strip /scope.json)
            return scopeFile.replace(/\/scope\.json$/, "")
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
      const content = await $`cat ${engagementDir}/scope.json`.text()
      return JSON.parse(content)
    } catch {
      return null
    }
  }

  /**
   * Extract URLs and hostnames from a command string using heuristic regex.
   * This is best-effort, not a security boundary.
   */
  const extractHostnames = (command: string): string[] => {
    const hosts: string[] = []

    // Match URLs like http://example.com or https://sub.example.com:8080/path
    const urlPattern = /https?:\/\/([a-zA-Z0-9._-]+(?::\d+)?)/g
    let match: RegExpExecArray | null
    while ((match = urlPattern.exec(command)) !== null) {
      // Strip port from hostname
      hosts.push(match[1].replace(/:\d+$/, ""))
    }

    // Match bare hostnames/IPs that look like targets (e.g., in curl, nmap, etc.)
    // Only after common tool names to reduce false positives
    const toolTargetPattern = /(?:curl|wget|nmap|nikto|gobuster|ffuf|sqlmap|nuclei|httpx|dig|host|whois|nc|netcat)\s+(?:-[^\s]+\s+)*([a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,})/g
    while ((match = toolTargetPattern.exec(command)) !== null) {
      hosts.push(match[1])
    }

    return [...new Set(hosts)]
  }

  /**
   * Check if a hostname matches any scope entry (supports wildcard prefixes).
   */
  const isInScope = (hostname: string, scopeList: string[]): boolean => {
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

      // Read supporting files for context
      let logContent = ""
      let findingsContent = ""
      try {
        logContent = await $`cat ${engagementDir}/log.md`.text()
      } catch {
        // log.md may not exist yet
      }
      try {
        findingsContent = await $`cat ${engagementDir}/findings.md`.text()
      } catch {
        // findings.md may not exist yet
      }

      const logLines = logContent.trim().split("\n").length

      // Count findings
      const findingCount = (findingsContent.match(/^## \[FINDING-/gm) || []).length

      // Check queue stats if cases.db exists
      let queueInfo = ""
      try {
        const statsOutput = await $`./scripts/dispatcher.sh ${engagementDir}/cases.db stats 2>/dev/null`.text()
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
     * tool.execute.before
     *
     * For bash tool calls, extract hostnames/URLs from the command and
     * compare against the active engagement's scope list. Warn on
     * out-of-scope targets. This is heuristic/best-effort.
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
              `[${scope.scope.join(", ")}]. Verify this is intentional.`
          )
        }
      }
    },

    /**
     * tool.execute.after
     *
     * For bash tool calls, append a timestamped entry to the active
     * engagement's log.md with the command and truncated output summary.
     */
    "tool.execute.after": async (
      input: { tool: string; args?: Record<string, unknown> },
      output: unknown
    ) => {
      if (input.tool !== "bash") return

      const command = String(input.args?.command || input.args || "")
      if (!command) return

      // Deduplication: skip if same command was logged within the last 2 seconds
      const now = Date.now()
      if (command === lastLoggedCommand && now - lastLoggedTimestamp < 2000) {
        log("debug", "[Engagement] Skipping duplicate log entry")
        return
      }
      lastLoggedCommand = command
      lastLoggedTimestamp = now

      const engagementDir = await findActiveEngagement()
      if (!engagementDir) return

      const outputStr = typeof output === "string"
        ? output
        : typeof output === "object" && output !== null
          ? JSON.stringify(output)
          : String(output || "")

      const timestamp = new Date().toISOString()
      const summary = truncate(outputStr.trim(), 500)

      const entry = [
        "",
        `## [${timestamp}]`,
        "",
        "```bash",
        command,
        "```",
        "",
        summary ? `**Output summary:** ${summary}` : "*No output*",
        "",
      ].join("\n")

      try {
        await $`printf '%s' ${entry} >> ${engagementDir}/log.md`
        log("debug", `[Engagement] Logged command to ${engagementDir}/log.md`)
      } catch (err) {
        log("warn", `[Engagement] Failed to append to log.md: ${err}`)
      }
    },

    /**
     * file.edited
     *
     * If the edited file path contains "log.md", warn the user that
     * the engagement log was modified directly. This is a post-hoc
     * warning -- the edit cannot be prevented.
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

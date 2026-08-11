import type { Plugin } from "@opencode-ai/plugin"

export const ValidatePlugin: Plugin = async ({ $, directory, client }) => {
  const isArticleJson = (filePath: string): boolean => {
    const normalized = filePath.replace(/\\/g, "/")
    return (
      normalized.includes("knowledge/articles/") &&
      normalized.endsWith(".json")
    )
  }

  const validateFile = async (filePath: string) => {
    try {
      const result =
        await $`python3 hooks/validate_json.py ${filePath}`.cwd(directory).nothrow()
      if (result.exitCode !== 0) {
        const stderr = result.stderr.toString().trim()
        const stdout = result.stdout.toString().trim()
        if (stderr) {
          await client.app.log({
            body: {
              service: "validate",
              level: "warn",
              message: `校验失败: ${filePath}\n${stderr}`,
            },
          })
        }
        if (stdout) {
          await client.app.log({
            body: {
              service: "validate",
              level: "warn",
              message: `校验结果:\n${stdout}`,
            },
          })
        }
      } else {
        await client.app.log({
          body: {
            service: "validate",
            level: "info",
            message: `通过: ${filePath}`,
          },
        })
      }
    } catch (err) {
      await client.app.log({
        body: {
          service: "validate",
          level: "error",
          message: `执行异常: ${filePath} — ${String(err)}`,
        },
      })
    }
  }

  return {
    "tool.execute.after": async (input, _output) => {
      const tool = (input as { tool?: string }).tool
      if (tool !== "write" && tool !== "edit" && tool !== "Write" && tool !== "Edit") return

      const args = (input as { args?: Record<string, unknown> }).args
      if (!args) return

      const singlePath =
        (args as Record<string, unknown>)?.filePath ??
        (args as Record<string, unknown>)?.file_path
      if (!singlePath || typeof singlePath !== "string") return

      if (!isArticleJson(singlePath)) return

      await validateFile(singlePath)
    },
  }
}

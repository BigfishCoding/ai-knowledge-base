import type { Plugin, Hooks, PluginInput } from "@opencode-ai/plugin"

const server: Plugin = async (input: PluginInput): Promise<Hooks> => {
  const { $ } = input

  return {
    "tool.execute.after": async (
      evt: { tool: string; sessionID: string; callID: string; args: any },
      _output: { title: string; output: string; metadata: any },
    ) => {
      const tool = evt.tool
      if (tool !== "write" && tool !== "edit") return

      const filePath =
        (evt.args?.file_path as string | undefined) ??
        (evt.args?.filePath as string | undefined)

      if (!filePath) return
      if (!filePath.includes("knowledge/articles/")) return
      if (!filePath.endsWith(".json")) return

      console.log(`[validate] 检测到 JSON 写入: ${filePath}`)

      try {
        const result = await $`python3 hooks/validate_json.py ${filePath}`.nothrow()

        if (result.exitCode !== 0) {
          console.warn(`[validate] 校验未通过 (exit ${result.exitCode}):`)
          console.warn(result.stdout?.toString() ?? "")
          console.warn(result.stderr?.toString() ?? "")
        } else {
          console.log(`[validate] 校验通过: ${filePath}`)
        }
      } catch (err) {
        console.error(`[validate] 执行校验脚本异常: ${err}`)
      }
    },
  }
}

export default { server } satisfies { server: Plugin }

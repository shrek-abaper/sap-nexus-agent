import type { AgentRunSnapshot } from "@/runtime/run-event-schema";

/**
 * 一轮对话 = 一次独立的 Agent run。
 * 前端累积多轮消息时，每轮各自持有一份 snapshot，由 SSE 增量更新。
 * 后端每次仍独立 POST，不携带历史上下文。
 */
export type ChatTurn = {
  runId: string;
  query: string;
  snapshot: AgentRunSnapshot | null;
  isRunning: boolean;
  /**
   * 传输层错误（POST 失败 / SSE 中断），区别于 snapshot.error 的 Agent run 内部失败。
   * 存在时气泡以 failure tone 展示该信息，而非卡在「正在推理」或回退到空态占位。
   */
  error?: string;
};

/**
 * 当前查看轮索引。null 表示尚未发起任何 run（空态）。
 * 切换 Run History 时只读展示对应轮，底部 composer 仍发起新轮（追加到末尾）。
 */
export type ActiveTurnIndex = number | null;

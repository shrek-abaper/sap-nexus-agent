"use client";

import { Icon } from "@/shared/ui/Icon";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isRunning: boolean;
}

/**
 * 底部固定输入框（Notion 式 composer）。
 * 对话态唯一输入入口；提交后由父组件追加新 turn。
 */
export function ChatComposer({ value, onChange, onSubmit, isRunning }: ChatComposerProps) {
  return (
    <form
      className="chat-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (!isRunning && value.trim()) {
          onSubmit();
        }
      }}
    >
      <div className="chat-composer__input">
        <textarea
          aria-label="向 SAP Nexus Agent 提问"
          placeholder="输入 SAP 业务问题，回车发送，Shift+回车换行"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            const el = event.currentTarget;
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (!isRunning && value.trim()) {
                onSubmit();
              }
            }
          }}
        />
        <button disabled={isRunning || !value.trim()} type="submit" aria-label="发送">
          <Icon name="send" size={16} />
        </button>
      </div>
      <p className="chat-composer__hint">Agent 记住本轮对话上下文，可连续追问补参数。</p>
    </form>
  );
}

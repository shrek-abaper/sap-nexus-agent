import type { HumanInTheLoopState } from "@/runtime/run-event-schema";
import type { RedactedArtifact } from "@/shared/types/artifacts";

type ApprovalDecision = "approve" | "reject";

type HumanApprovalPanelProps = {
  state: HumanInTheLoopState;
  artifact?: RedactedArtifact;
  onDecision?: (decision: ApprovalDecision) => void;
  disabled?: boolean;
};

export function canDecideApproval(state: HumanInTheLoopState) {
  return state === "awaiting_human_approval";
}

export function HumanApprovalPanel({
  state,
  artifact,
  onDecision,
  disabled = false
}: HumanApprovalPanelProps) {
  const approval = objectPayload(artifact?.payload);
  const parameters = objectPayload(approval?.parameters);
  const actionable = canDecideApproval(state) && Boolean(onDecision);

  return (
    <section className={`panel approval-panel approval-panel--${state}`}>
      <div className="approval-panel__head">
        <div>
          <small>Human Approval</small>
          <h2>采购申请创建审批</h2>
        </div>
        <span>{stateLabel(state)}</span>
      </div>
      {state === "approval_not_required" ? <small>Read-only Function，不需要人工审批。</small> : null}
      {approval ? (
        <dl className="approval-panel__facts">
          <div><dt>物料</dt><dd>{text(parameters?.material)}</dd></div>
          <div><dt>工厂</dt><dd>{text(parameters?.plant)}</dd></div>
          <div><dt>数量</dt><dd>{text(parameters?.quantity)} {text(parameters?.unit)}</dd></div>
          <div><dt>采购组</dt><dd>{text(parameters?.purchasing_group)}</dd></div>
          <div><dt>交货日期</dt><dd>{text(parameters?.delivery_date)}</dd></div>
          <div><dt>Approval ID</dt><dd className="approval-panel__mono">{text(approval.approvalId)}</dd></div>
          <div><dt>有效期至</dt><dd className="approval-panel__mono">{text(approval.expiresAt)}</dd></div>
          <div><dt>Snapshot Hash</dt><dd className="approval-panel__mono">{text(approval.parameterSnapshotHash)}</dd></div>
        </dl>
      ) : null}
      {actionable ? (
        <div className="approval-panel__actions">
          <button disabled={disabled} onClick={() => onDecision?.("reject")} type="button">
            拒绝
          </button>
          <button
            className="approval-panel__approve"
            disabled={disabled}
            onClick={() => onDecision?.("approve")}
            type="button"
          >
            批准并执行
          </button>
        </div>
      ) : null}
    </section>
  );
}

function objectPayload(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function text(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : "-";
}

function stateLabel(state: HumanInTheLoopState) {
  const labels: Record<HumanInTheLoopState, string> = {
    approval_not_required: "无需审批",
    approval_required: "需要审批",
    awaiting_human_approval: "等待审批",
    approved: "已批准",
    rejected: "已拒绝",
    expired: "已过期"
  };
  return labels[state];
}

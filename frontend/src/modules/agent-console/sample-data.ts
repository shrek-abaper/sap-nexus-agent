/**
 * Workbench 首屏示例常量。
 *
 * 物料号 / 工厂号 / PO 号均为示例标识符，集中维护，避免在组件中散落硬编码。
 * 不代表真实 SAP 业务数据。示例卡对应 registry/capabilities.yaml 中已注册的三个能力：
 * MM.Inventory.GetAvailability (READ)、MM.PurchaseOrder.GetList (READ)、MM.PR.CreateDraft (ACTION)。
 */

export const SAMPLE_IDENTIFIERS = {
  material: "DEMOA2",
  plant: "5100",
  po: "DEMOPO2"
} as const;

export type SamplePromptKind = "read" | "action";

export type SamplePromptSegment = {
  text: string;
  /** 标识符片段，渲染时使用等宽字体（物料号 / 工厂号 / PO 号）。 */
  mono?: boolean;
};

export type SamplePrompt = {
  kind: SamplePromptKind;
  /** 顶部标签，独占一行，如 "READ · 库存"。 */
  label: string;
  /** 渲染片段，标识符片段标记为 mono。 */
  segments: SamplePromptSegment[];
  /** 提交给 Agent 的纯文本 query（点击示例卡后填入输入框）。 */
  query: string;
};

export const samplePrompts: SamplePrompt[] = [
  {
    kind: "read",
    label: "READ · 库存",
    segments: [
      { text: SAMPLE_IDENTIFIERS.material, mono: true },
      { text: " 在工厂 " },
      { text: SAMPLE_IDENTIFIERS.plant, mono: true },
      { text: " 还有多少可用库存" }
    ],
    query: `${SAMPLE_IDENTIFIERS.material} 在工厂 ${SAMPLE_IDENTIFIERS.plant} 还有多少可用库存`
  },
  {
    kind: "read",
    label: "READ · 采购订单",
    segments: [{ text: "列出近 30 天未清采购订单" }],
    query: "列出近 30 天未清采购订单"
  },
  {
    kind: "action",
    label: "ACTION · 需审批",
    segments: [
      { text: "为 " },
      { text: SAMPLE_IDENTIFIERS.material, mono: true },
      { text: " 创建采购申请草稿" }
    ],
    query: `为 ${SAMPLE_IDENTIFIERS.material} 创建采购申请草稿`
  }
];

/** Hero 首屏输入框 placeholder。 */
export const heroInputPlaceholder = `描述你的 SAP 问题，例如：${SAMPLE_IDENTIFIERS.material} 在工厂 ${SAMPLE_IDENTIFIERS.plant} 的可用库存`;

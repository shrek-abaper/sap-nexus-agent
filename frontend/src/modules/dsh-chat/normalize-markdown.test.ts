import { describe, expect, it } from "vitest";
import { normalizeMarkdown } from "./normalize-markdown";

describe("normalizeMarkdown", () => {
  it("splits a heading glued to preceding text", () => {
    const out = normalizeMarkdown("需要物料### 📦标题\n内容");
    expect(out).toContain("需要物料\n\n### 📦标题");
  });

  it("splits a bullet glued after sentence punctuation", () => {
    expect(normalizeMarkdown("工厂编码：- 需要提供：物料")).toContain("工厂编码：\n- 需要提供：物料");
    expect(normalizeMarkdown("工厂编码：-需要提供：物料")).toContain("工厂编码：\n- 需要提供：物料");
  });

  it("does not split a hyphen inside a heading phrase", () => {
    expect(normalizeMarkdown("### 物料供应诊断-查询库存")).toBe("### 物料供应诊断-查询库存");
  });

  it("splits a glued -item after a CJK word on a non-heading line", () => {
    const out = normalizeMarkdown("工厂编码-需要提供：物料");
    expect(out).toContain("工厂编码\n- 需要提供：物料");
  });

  it("normalizes the full malformed capability answer", () => {
    const raw = "编码## 📋标题\n-需要物料## 👤二\n-需要客户";
    const out = normalizeMarkdown(raw);
    expect(out).toContain("编码\n\n## 📋标题");
    expect(out).toContain("\n- 需要物料\n\n## 👤二");
    expect(out).toContain("\n- 需要客户");
  });

  it("does not break ISO dates or inline hyphenated tokens", () => {
    const out = normalizeMarkdown("日期 2026-09-12，范围 A-B");
    expect(out).toContain("2026-09-12");
    expect(out).toContain("A-B");
  });

  it("leaves already well-formed markdown untouched", () => {
    const input = "### 标题\n\n- 第一项\n- 第二项\n\n> 引用";
    expect(normalizeMarkdown(input)).toBe(input);
  });

  it("splits a glued horizontal rule after CJK text", () => {
    const out = normalizeMarkdown("公司代码---");
    expect(out).toContain("公司代码\n\n---");
  });
});

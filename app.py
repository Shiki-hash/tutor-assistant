"""Local CLI MVP: one CrewAI Agent, structured drafts, grounded references."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parent


class UserFacingError(ValueError):
    """Only deliberately written, credential-free messages reach the console."""


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_id: str
    quote: str = Field(min_length=1)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_reply: str = Field(min_length=1, max_length=1000)
    evidence: list[Citation]
    assistant_checks: list[str] = Field(min_length=1)
    missing_info: list[str]
    suggested_status: Literal["待补充信息", "待老师核实", "待补充评价记录", "待状态排查", "待明确评价要求"]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_citations(draft: Draft, knowledge: list[dict]) -> None:
    sources = {card["id"]: card for card in knowledge}
    for citation in draft.evidence:
        if citation.knowledge_id not in sources:
            raise UserFacingError("模型引用了不存在的知识卡，草稿已拦截。")
        if not citation.quote.strip() or citation.quote not in sources[citation.knowledge_id]["text"]:
            raise UserFacingError("模型引用与原文不一致，草稿已拦截。")


def settings() -> dict:
    load_dotenv(ROOT / ".env", override=False)
    values = {key: os.getenv(key, "").strip() for key in
              ("TUTOR_MODEL", "TUTOR_API_KEY", "TUTOR_BASE_URL")}
    provider = os.getenv("TUTOR_PROVIDER", "openai").strip().lower()
    if provider == "deepseek":
        # Never fall back to the existing OpenAI credential.
        values["TUTOR_API_KEY"] = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not values["TUTOR_API_KEY"]:
            raise UserFacingError("请在本机 .env 填写 DEEPSEEK_API_KEY；原 OpenAI 密钥不会用于 DeepSeek。")
        if urlparse(values["TUTOR_BASE_URL"]).hostname != "api.deepseek.com":
            raise UserFacingError("DeepSeek 配置的接口必须是 https://api.deepseek.com。")
    values["TUTOR_PROVIDER"] = provider
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise UserFacingError("尚未配置 " + "、".join(missing) + "。请在本机 .env 填写；没有调用模型。")
    if not values["TUTOR_MODEL"].startswith("openai/"):
        raise UserFacingError("此版本使用兼容接口，TUTOR_MODEL 请填写 openai/模型名称。")
    if not values["TUTOR_BASE_URL"].startswith(("https://", "http://localhost:", "http://127.0.0.1:")):
        raise UserFacingError("接口地址需要 HTTPS，或本机 HTTP 地址。")
    return values


def build_crew(case: dict, knowledge: list[dict], config: dict):
    # Disable framework tracing before importing CrewAI. No extra telemetry needed.
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["CREWAI_TELEMETRY_ENABLED"] = "false"
    os.environ["CREWAI_TRACING_ENABLED"] = "false"
    from crewai import Agent, Crew, LLM, Process, Task

    llm = LLM(model=config["TUTOR_MODEL"], api_key=config["TUTOR_API_KEY"],
              base_url=config["TUTOR_BASE_URL"],
              timeout=60, max_retries=0)
    agent = Agent(role="助教答疑草稿助手", goal="基于已有信息生成可核查的简短回复",
                  backstory=(ROOT / "prompt.md").read_text(encoding="utf-8"),
                  llm=llm, allow_delegation=False, verbose=False,
                  max_iter=2, max_retry_limit=0, allow_code_execution=False)
    payload = json.dumps({"case": case, "knowledge": knowledge}, ensure_ascii=False)

    def guardrail(output):
        try:
            draft = output.pydantic or Draft.model_validate_json(output.raw)
            validate_citations(draft, knowledge)
            return True, output
        except (ValueError, ValidationError):
            return False, "请输出指定结构；只引用存在的知识卡及其原文连续片段。"

    use_native_schema = config.get("TUTOR_PROVIDER") != "deepseek"
    schema_instruction = "最终答案必须为纯 JSON 对象，不带代码围栏，遵循 JSON Schema：" + json.dumps(Draft.model_json_schema(), ensure_ascii=False)
    task = Task(description="分析以下 JSON 数据，按你的规则生成草稿：\n" + payload,
                expected_output=schema_instruction,
                agent=agent, output_pydantic=Draft if use_native_schema else None, guardrail=guardrail,
                guardrail_max_retries=1)
    return Crew(agents=[agent], tasks=[task], process=Process.sequential,
                memory=False, cache=False, verbose=False)


def generate(case: dict, knowledge: list[dict], config: dict) -> dict:
    started = time.perf_counter()
    prompt_hash = hashlib.sha256((ROOT / "prompt.md").read_bytes()).hexdigest()
    knowledge_hash = hashlib.sha256((ROOT / "knowledge.json").read_bytes()).hexdigest()
    crew = build_crew(case, knowledge, config)
    result = crew.kickoff()
    draft = result.pydantic or Draft.model_validate_json(result.raw)
    validate_citations(draft, knowledge)
    sources = {card["id"]: card for card in knowledge}
    return {
        "case_id": case["id"], "synthetic_input": case.get("synthetic", True),
        "mode": "live_model", "model": config["TUTOR_MODEL"],
        "prompt_sha256": prompt_hash,
        "knowledge_sha256": knowledge_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "human_review": "待审核", "input": case, "draft": draft.model_dump(),
        "source_cards": [sources[c.knowledge_id] for c in draft.evidence],
        "limitations": "引用检查只验证来源与原文，不能保证推理正确，仍需真人核对。"
    }


def render_markdown(record: dict) -> str:
    draft = record["draft"]
    sources = {card["id"]: card for card in record["source_cards"]}
    citations = [f'- {c["knowledge_id"]}：{c["quote"]}（{sources[c["knowledge_id"]]["verification"]}）'
                 for c in draft["evidence"]]
    return "\n".join([
        f'# {record["case_id"]} · AI 回复草稿 · 待人工审核',
        '', '## 给学生的回复（可编辑）', '', draft['student_reply'], '',
        '## 依据', '', *(citations or ['无引用；不能据此解释未知规则。']), '',
        '## 仅供助教：核查项', '', *('- ' + x for x in draft['assistant_checks']), '',
        '## 缺失信息', '', *('- ' + x for x in draft['missing_info']), '',
        '建议状态：' + draft['suggested_status'], '',
        f'模型生成耗时：{record["elapsed_seconds"]} 秒（不含人工审核时间）。', '',
        record['limitations'], '',
    ])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="助教答疑助手：先预览输入，再调用模型生成草稿。")
    parser.add_argument("--case", choices=["F009", "F010", "F004"], default="F010")
    parser.add_argument("--preview", action="store_true", help="只预览输入和验收标准，不生成回复、不联网")
    parser.add_argument("--check", action="store_true", help="检查本机配置是否齐全，不调用模型")
    parser.add_argument("--message", help="替换示例学生消息；仅填写已脱敏内容")
    parser.add_argument("--teacher-result", help="补充真人核查结果")
    args = parser.parse_args(argv)
    try:
        if args.check:
            settings()
            print("配置字段齐全；接口连通性、模型可用性尚未验证。")
            return 0
        cases = read_json(ROOT / "cases.json")
        case = next(dict(c) for c in cases if c["id"] == args.case)
        if args.message is not None:
            if not args.message.strip():
                raise UserFacingError("学生消息不能为空。")
            case["message"] = args.message.strip()
            case["synthetic"] = False
            case["context"] = "用户自定义消息，未提供额外背景。"
        if args.teacher_result:
            case["teacher_result"] = args.teacher_result
        knowledge = read_json(ROOT / "knowledge.json")
        if args.preview:
            print("输入预览：没有调用模型，没有生成 AI 草稿。")
            print(json.dumps({"case": case, "knowledge": knowledge}, ensure_ascii=False, indent=2))
            return 0
        config = settings()
        print("正在调用配置的模型生成草稿，请等待……")
        record = generate(case, knowledge, config)
        output = ROOT / "outputs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
        output.mkdir(parents=True)
        (output / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "reply.md").write_text(render_markdown(record), encoding="utf-8")
        print("生成完成，请审核并编辑：" + str(output / "reply.md"))
        return 0
    except UserFacingError as exc:
        # Settings/validation errors never include credentials.
        print("未完成：" + str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        # Do not echo provider errors: they may contain request data or credentials.
        print(f"生成失败（{type(exc).__name__}）。请检查接口、模型、额度或网络。没有生成替代话术。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())

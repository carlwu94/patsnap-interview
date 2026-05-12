from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any
from typing import Iterator

from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.agent.llm_client import build_llm_client
from app.config import Settings
from app.mcp.server import create_server


PATENT_ID_PATTERN = re.compile(r"\b[A-Z]{2}\d+[A-Z]?\b")
YEAR_PATTERN = re.compile(r"(20\d{2})")
TOP_N_PATTERN = re.compile(r"(?:top|前|热门的?)(\d+)")
MAX_TOOL_ROUNDS = 8
STOP_TOOL_LOOP_STATUS = "检测到重复工具调用，基于当前结果作答"
SYSTEM_PROMPT = "You are a patent search assistant. Decide when to call tools. Keep answers concise and factual. Reuse existing tool results whenever possible, and stop calling tools once you have enough evidence to answer. When a company name may be an alias, abbreviation, or fuzzy reference, call list_assignees once to resolve the canonical assignee name before using assignee-based filters or trend queries. For company-and-year patent listing requests, pass the resolved exact assignee into assignee, and leave keyword empty unless the user also asked for a real technical topic such as a material, battery part, IPC, or method."
SEARCH_NOISE_FRAGMENTS = (
    "帮我",
    "查询",
    "检索",
    "搜索",
    "查找",
    "列出",
    "看看",
    "一下",
    "相关",
    "专利",
    "申请",
    "期间",
    "年",
    "在",
    "的",
    "有哪些",
    "情况",
)


@dataclass(frozen=True)
class ToolCallRecord:
    tool: str
    arguments: dict[str, Any]
    result_preview: str


def _model_status(settings: Settings) -> str:
    if settings.llm_api_key and settings.llm_model:
        return f"已配置模型：{settings.llm_model}"
    return "未配置模型，当前走规则兜底"


def _response_payload(
    settings: Settings,
    *,
    answer: str,
    tool_calls: list[dict[str, Any]] | None = None,
    data: Any = None,
    reasoning: str | None = None,
    status_steps: list[str] | None = None,
    current_status: str | None = None,
) -> dict[str, Any]:
    normalized_status_steps = status_steps or []
    return {
        "answer": answer,
        "tool_calls": tool_calls or [],
        "data": data,
        "reasoning": reasoning,
        "model_status": _model_status(settings),
        "status_steps": normalized_status_steps,
        "current_status": current_status or (normalized_status_steps[-1] if normalized_status_steps else "空闲"),
    }


def _stream_event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, **payload}


def _normalize_history(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history or []:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _build_messages(message: str, history: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_normalize_history(history),
        {"role": "user", "content": message},
    ]


def _tool_signature(name: str, arguments: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"


def _clean_search_keyword(keyword: Any, aliases: list[str] | None = None) -> str | None:
    if not isinstance(keyword, str):
        return None

    cleaned = keyword.strip()
    if not cleaned:
        return None

    for alias in aliases or []:
        if alias:
            cleaned = cleaned.replace(alias, " ")
    cleaned = YEAR_PATTERN.sub(" ", cleaned)
    for fragment in SEARCH_NOISE_FRAGMENTS:
        cleaned = cleaned.replace(fragment, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。；;：:")
    return cleaned or None


def _resolved_assignee_from_aliases(alias_map: dict[str, str], arguments: dict[str, Any]) -> tuple[str | None, list[str]]:
    aliases: list[str] = []
    keyword = arguments.get("keyword")
    if isinstance(keyword, str):
        aliases.extend(alias for alias in alias_map if alias and alias in keyword)

    assignee = arguments.get("assignee")
    if isinstance(assignee, str):
        aliases.extend(alias for alias in alias_map if alias and alias in assignee)

    resolved_values = {alias_map[alias] for alias in aliases if alias in alias_map}
    if not resolved_values and len(set(alias_map.values())) == 1:
        resolved_values = set(alias_map.values())
        aliases.extend(alias_map.keys())

    resolved_assignee = next(iter(resolved_values)) if len(resolved_values) == 1 else None
    unique_aliases = list(dict.fromkeys([*aliases, resolved_assignee] if resolved_assignee else aliases))
    return resolved_assignee, unique_aliases


def _normalize_tool_arguments(name: str, arguments: dict[str, Any], alias_map: dict[str, str]) -> dict[str, Any]:
    normalized = dict(arguments)
    if name not in {"search_patents", "get_assignee_trend"}:
        return normalized

    resolved_assignee, aliases = _resolved_assignee_from_aliases(alias_map, normalized)
    assignee = normalized.get("assignee")
    if (not isinstance(assignee, str) or not assignee.strip()) and resolved_assignee:
        normalized["assignee"] = resolved_assignee
        assignee = resolved_assignee

    if name == "search_patents":
        alias_candidates = [*aliases]
        if isinstance(assignee, str) and assignee.strip():
            alias_candidates.append(assignee.strip())
        normalized["keyword"] = _clean_search_keyword(normalized.get("keyword"), alias_candidates)

    return normalized


def _complete_with_current_evidence(
    client: Any,
    settings: Settings,
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    data: Any,
    reasoning_parts: list[str],
    status_steps: list[str],
    stop_status: str | None = None,
    fallback_answer: str = "已基于当前可用结果生成回答。",
) -> tuple[dict[str, Any], str | None]:
    completion_messages = [
        *messages,
        {
            "role": "system",
            "content": "Do not call any more tools. Based only on the conversation and existing tool outputs, provide the best concise factual answer you can. If evidence is partial, state the limitation clearly.",
        },
    ]
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=completion_messages,
    )
    choice = response.choices[0].message
    new_reasoning = getattr(choice, "reasoning_content", None)
    all_reasoning_parts = [*reasoning_parts]
    if new_reasoning:
        all_reasoning_parts.append(new_reasoning)

    completion_steps = [*status_steps]
    if stop_status and (not completion_steps or completion_steps[-1] != stop_status):
        completion_steps.append(stop_status)
    if not completion_steps or completion_steps[-1] != "已完成":
        completion_steps.append("已完成")

    payload = _response_payload(
        settings,
        answer=choice.content or fallback_answer,
        tool_calls=tool_calls,
        data=data,
        reasoning="\n\n".join(all_reasoning_parts) if all_reasoning_parts else None,
        status_steps=completion_steps,
    )
    return payload, new_reasoning


def _tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_assignees",
                "description": "List distinct assignee/company names with patent counts. Use this once to resolve a canonical company name before assignee-based filters or trend queries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "Optional partial company name or alias to narrow the candidate list.",
                        },
                        "limit": {"type": "integer", "description": "Maximum number of assignees to return."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_patents",
                "description": "Search patents by keyword with optional assignee and filing year filters. If the company name is uncertain, resolve it with list_assignees first. For company-only or company-plus-year requests, pass assignee and leave keyword empty.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "Optional technical keyword to search in title and full text. Leave empty if the user only constrained company and/or year."},
                        "assignee": {"type": "string", "description": "Optional exact assignee filter. Prefer the canonical company name returned by list_assignees."},
                        "year_start": {"type": "integer", "description": "Optional filing year lower bound."},
                        "year_end": {"type": "integer", "description": "Optional filing year upper bound."},
                        "limit": {"type": "integer", "description": "Maximum number of patents to return."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_patent_details",
                "description": "Get a patent's full record by patent id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patent_id": {"type": "string", "description": "Patent publication number."}
                    },
                    "required": ["patent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_top_ipc",
                "description": "Get the most frequent IPC main classes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "top_n": {"type": "integer", "description": "Number of IPC classes to return."}
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_assignee_trend",
                "description": "Get annual patent counts for an assignee in a year range. Prefer an exact assignee name from list_assignees.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "assignee": {"type": "string", "description": "Assignee name."},
                        "start_year": {"type": "integer", "description": "Start year."},
                        "end_year": {"type": "integer", "description": "End year."},
                    },
                    "required": ["assignee", "start_year", "end_year"],
                },
            },
        },
    ]


def _preview_result(result: Any) -> str:
    if isinstance(result, list):
        return f"{len(result)} items"
    if isinstance(result, dict):
        keys = ", ".join(list(result.keys())[:4])
        return f"dict[{keys}]"
    return str(result)


async def _execute_tool_via_mcp(name: str, arguments: dict[str, Any]) -> Any:
    async with Client(create_server()) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error:
        raise RuntimeError(f"MCP tool call failed: {name}")
    return result.structured_content.get("result")


def _execute_tool(settings: Settings, name: str, arguments: dict[str, Any]) -> tuple[Any, ToolCallRecord]:
    result = asyncio.run(_execute_tool_via_mcp(name, arguments))
    return result, ToolCallRecord(tool=name, arguments=arguments, result_preview=_preview_result(result))


def _extract_keyword(message: str) -> str:
    quoted = re.findall(r'[\'"“”‘’](.*?)[\'"“”‘’]', message)
    if quoted:
        return quoted[0].strip()

    cleaned = message
    for fragment in ["帮我", "检索", "搜索", "查找", "列出", "相关的", "专利", "所有提到", "查看", "一下"]:
        cleaned = cleaned.replace(fragment, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or message.strip()


def _heuristic_reply(settings: Settings, message: str) -> dict[str, Any]:
    patent_match = PATENT_ID_PATTERN.search(message.upper())
    if patent_match:
        result, record = _execute_tool(settings, "get_patent_details", {"patent_id": patent_match.group(0)})
        status_steps = [f"正在调用 get_patent_details 工具", "已完成"]
        if not result:
            return _response_payload(
                settings,
                answer=f"未找到专利 {patent_match.group(0)}。",
                tool_calls=[record.__dict__],
                data=result,
                status_steps=status_steps,
            )
        answer = f"已找到 {result['patent_id']}，标题是《{result['title']}》。申请人为 {result.get('assignee') or '未知'}。"
        return _response_payload(settings, answer=answer, tool_calls=[record.__dict__], data=result, status_steps=status_steps)

    if any(token in message for token in ["公司", "企业", "申请人"]) and any(
        token in message for token in ["名称", "名单", "列表", "有哪些"]
    ):
        result, record = _execute_tool(settings, "list_assignees", {"limit": 100})
        status_steps = ["正在调用 list_assignees 工具", "已完成"]
        if not result:
            return _response_payload(
                settings,
                answer="当前库中没有可用的公司名称。",
                tool_calls=[record.__dict__],
                data=result,
                status_steps=status_steps,
            )
        answer = "当前库中的公司/申请人包括：" + "；".join(item["assignee"] for item in result[:20])
        if len(result) > 20:
            answer += " 等。"
        return _response_payload(settings, answer=answer, tool_calls=[record.__dict__], data=result, status_steps=status_steps)

    if "IPC" in message.upper() or "分类号" in message:
        top_n_match = TOP_N_PATTERN.search(message)
        top_n = int(top_n_match.group(1)) if top_n_match else 5
        result, record = _execute_tool(settings, "get_top_ipc", {"top_n": top_n})
        status_steps = [f"正在调用 get_top_ipc 工具", "已完成"]
        answer = "最热门的 IPC 主分类号如下：" + "；".join(
            f"{item['ipc_main']}({item['patent_count']})" for item in result
        )
        return _response_payload(settings, answer=answer, tool_calls=[record.__dict__], data=result, status_steps=status_steps)

    if "趋势" in message or "每年" in message:
        years = [int(match) for match in YEAR_PATTERN.findall(message)]
        assignee = _extract_keyword(message)
        if len(years) >= 2:
            start_year, end_year = min(years), max(years)
        elif len(years) == 1:
            start_year = end_year = years[0]
        else:
            start_year, end_year = 2020, 2025
        result, record = _execute_tool(
            settings,
            "get_assignee_trend",
            {"assignee": assignee, "start_year": start_year, "end_year": end_year},
        )
        status_steps = [f"正在调用 get_assignee_trend 工具", "已完成"]
        answer = f"{assignee} 在 {start_year}-{end_year} 年的申请趋势已生成。"
        return _response_payload(settings, answer=answer, tool_calls=[record.__dict__], data=result, status_steps=status_steps)

    years = [int(match) for match in YEAR_PATTERN.findall(message)]
    assignee = None
    keyword = _extract_keyword(message)
    assignee_match = re.search(r'[\'"“”‘’]([^\'"“”‘’]+)[\'"“”‘’]', message)
    if assignee_match and any(token in message for token in ["申请人", "宁德时代", "公司"]):
        assignee = assignee_match.group(1)
    year_start = min(years) if years else None
    year_end = max(years) if years else None
    result, record = _execute_tool(
        settings,
        "search_patents",
        {
            "keyword": keyword,
            "assignee": assignee,
            "year_start": year_start,
            "year_end": year_end,
            "limit": 10,
        },
    )
    status_steps = [f"正在调用 search_patents 工具", "已完成"]
    if not result:
        return _response_payload(
            settings,
            answer="没有检索到匹配专利。可以换一个关键词或放宽筛选条件。",
            tool_calls=[record.__dict__],
            data=result,
            status_steps=status_steps,
        )
    answer = "检索到以下专利：" + "；".join(
        f"{item['patent_id']}《{item['title']}》" for item in result[:5]
    )
    return _response_payload(settings, answer=answer, tool_calls=[record.__dict__], data=result, status_steps=status_steps)


def _stream_final_payload(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield _stream_event("status", text=payload.get("current_status") or "已完成")
    yield _stream_event("answer", text=payload["answer"])
    yield _stream_event("final", payload=payload)


def _heuristic_reply_stream(settings: Settings, message: str) -> Iterator[dict[str, Any]]:
    yield _stream_event("status", text="思考中")
    payload = _heuristic_reply(settings, message)
    for tool_call in payload.get("tool_calls", []):
        yield _stream_event("tool_call", call=tool_call)
    yield from _stream_final_payload(payload)


def chat_with_agent(settings: Settings, message: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    client = build_llm_client(settings)
    if client is None:
        return _heuristic_reply(settings, message)

    tools = _tool_schemas()
    messages: list[dict[str, Any]] = _build_messages(message, history)

    tool_calls: list[dict[str, Any]] = []
    data: Any = None
    reasoning_parts: list[str] = []
    status_steps: list[str] = []
    seen_tool_signatures: set[str] = set()
    assignee_alias_map: dict[str, str] = {}
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        choice = response.choices[0].message
        if getattr(choice, "reasoning_content", None):
            reasoning_parts.append(choice.reasoning_content)
            if not status_steps or status_steps[-1] != "思考中":
                status_steps.append("思考中")
        if not choice.tool_calls:
            completion_steps = [*status_steps, "已完成"] if status_steps else ["已完成"]
            return _response_payload(
                settings,
                answer=choice.content or "未返回文本答案。",
                tool_calls=tool_calls,
                data=data,
                reasoning="\n\n".join(reasoning_parts) if reasoning_parts else None,
                status_steps=completion_steps,
            )

        messages.append(choice.model_dump(exclude_none=True))
        for tool_call in choice.tool_calls:
            status_steps.append(f"正在调用 {tool_call.function.name} 工具")
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                arguments = _normalize_tool_arguments(tool_call.function.name, arguments, assignee_alias_map)
                signature = _tool_signature(tool_call.function.name, arguments)
                if signature in seen_tool_signatures:
                    payload, new_reasoning = _complete_with_current_evidence(
                        client=client,
                        settings=settings,
                        messages=messages,
                        tool_calls=tool_calls,
                        data=data,
                        reasoning_parts=reasoning_parts,
                        status_steps=status_steps,
                        stop_status=STOP_TOOL_LOOP_STATUS,
                        fallback_answer="检测到重复工具调用，已基于当前结果作答。",
                    )
                    if new_reasoning:
                        reasoning_parts.append(new_reasoning)
                    return payload
                seen_tool_signatures.add(signature)
                result, record = _execute_tool(settings, tool_call.function.name, arguments)
                if tool_call.function.name == "list_assignees" and isinstance(result, list) and len(result) == 1:
                    alias = str(arguments.get("keyword") or "").strip()
                    assignee_name = str(result[0].get("assignee") or "").strip()
                    if alias and assignee_name:
                        assignee_alias_map[alias] = assignee_name
            except (json.JSONDecodeError, ToolError, RuntimeError, TypeError, ValueError):
                return _heuristic_reply(settings, message)
            data = result
            tool_calls.append(record.__dict__)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    payload, _ = _complete_with_current_evidence(
        client=client,
        settings=settings,
        messages=messages,
        tool_calls=tool_calls,
        data=data,
        reasoning_parts=reasoning_parts,
        status_steps=status_steps,
        stop_status="已达到工具调用上限，基于当前结果作答",
        fallback_answer="已达到工具调用上限，已基于当前结果作答。",
    )
    return payload


def stream_chat_with_agent(
    settings: Settings,
    message: str,
    history: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    client = build_llm_client(settings)
    if client is None:
        yield from _heuristic_reply_stream(settings, message)
        return

    tools = _tool_schemas()
    messages: list[dict[str, Any]] = _build_messages(message, history)

    tool_calls: list[dict[str, Any]] = []
    data: Any = None
    reasoning_parts: list[str] = []
    status_steps: list[str] = ["思考中"]
    seen_tool_signatures: set[str] = set()
    assignee_alias_map: dict[str, str] = {}
    yield _stream_event("status", text="思考中")

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        choice = response.choices[0].message
        reasoning_text = getattr(choice, "reasoning_content", None)
        if reasoning_text:
            reasoning_parts.append(reasoning_text)
            yield _stream_event("reasoning", text=reasoning_text)

        if not choice.tool_calls:
            completion_steps = [*status_steps, "已完成"]
            payload = _response_payload(
                settings,
                answer=choice.content or "未返回文本答案。",
                tool_calls=tool_calls,
                data=data,
                reasoning="\n\n".join(reasoning_parts) if reasoning_parts else None,
                status_steps=completion_steps,
            )
            yield from _stream_final_payload(payload)
            return

        messages.append(choice.model_dump(exclude_none=True))
        for tool_call in choice.tool_calls:
            status_text = f"正在调用 {tool_call.function.name} 工具"
            status_steps.append(status_text)
            yield _stream_event("status", text=status_text)
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                arguments = _normalize_tool_arguments(tool_call.function.name, arguments, assignee_alias_map)
                signature = _tool_signature(tool_call.function.name, arguments)
                if signature in seen_tool_signatures:
                    payload, new_reasoning = _complete_with_current_evidence(
                        client=client,
                        settings=settings,
                        messages=messages,
                        tool_calls=tool_calls,
                        data=data,
                        reasoning_parts=reasoning_parts,
                        status_steps=status_steps,
                        stop_status=STOP_TOOL_LOOP_STATUS,
                        fallback_answer="检测到重复工具调用，已基于当前结果作答。",
                    )
                    yield _stream_event("status", text=STOP_TOOL_LOOP_STATUS)
                    if new_reasoning:
                        yield _stream_event("reasoning", text=new_reasoning)
                    yield from _stream_final_payload(payload)
                    return
                seen_tool_signatures.add(signature)
                result, record = _execute_tool(settings, tool_call.function.name, arguments)
                if tool_call.function.name == "list_assignees" and isinstance(result, list) and len(result) == 1:
                    alias = str(arguments.get("keyword") or "").strip()
                    assignee_name = str(result[0].get("assignee") or "").strip()
                    if alias and assignee_name:
                        assignee_alias_map[alias] = assignee_name
            except (json.JSONDecodeError, ToolError, RuntimeError, TypeError, ValueError):
                yield from _heuristic_reply_stream(settings, message)
                return

            data = result
            tool_calls.append(record.__dict__)
            yield _stream_event("tool_call", call=record.__dict__)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            status_steps.append("思考中")
            yield _stream_event("status", text="思考中")

    stop_status = "已达到工具调用上限，基于当前结果作答"
    payload, new_reasoning = _complete_with_current_evidence(
        client=client,
        settings=settings,
        messages=messages,
        tool_calls=tool_calls,
        data=data,
        reasoning_parts=reasoning_parts,
        status_steps=status_steps,
        stop_status=stop_status,
        fallback_answer="已达到工具调用上限，已基于当前结果作答。",
    )
    yield _stream_event("status", text=stop_status)
    if new_reasoning:
        yield _stream_event("reasoning", text=new_reasoning)
    yield from _stream_final_payload(payload)

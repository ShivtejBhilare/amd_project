import os
import json
from openai import AsyncOpenAI
from .mcp_server import list_tools as mcp_list_tools, call_tool as mcp_call_tool

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "llava-1.5-7b-hf") 

client = AsyncOpenAI(api_key="EMPTY", base_url=VLLM_BASE_URL)

async def _call_llm(system_prompt, chat_history, text, tools):
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
    
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME, messages=messages, tools=tools, tool_choice="auto"
        )
        return response.choices[0].message
    except Exception as e:
        print(f"LLM Error: {e}")
        return None

async def customer_agent_flow(complaint_id: int, text: str, project_name: str, chat_history: list):
    """Handles direct customer chat."""
    mcp_tools = await mcp_list_tools()
    tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}} for t in mcp_tools if t.name in ["search_knowledge_base", "check_ticket_status"]]
    
    system_prompt = f"You are a Customer Agent for {project_name}. Use search_knowledge_base. If they ask for an update, use check_ticket_status."
    
    msg = await _call_llm(system_prompt, chat_history, text, tools)
    
    # Mock Fallback logic
    if not msg or not msg.tool_calls:
        if "update" in text.lower() or "status" in text.lower():
            res = await mcp_call_tool("check_ticket_status", {"complaint_id": complaint_id})
            return {"status": "success", "reply": f"Checking on your ticket: {res[0].text}"}
        elif len(chat_history) > 0 and ("not work" in text.lower() or "didn't" in text.lower() or "still" in text.lower()):
            return {"status": "escalated", "reply": "I see the steps didn't work. I am escalating this to my Supervisor immediately."}
        else:
            res = await mcp_call_tool("search_knowledge_base", {"project_name": project_name})
            return {"status": "success", "reply": f"Based on our docs for {project_name}:\n{res[0].text[:300]}..."}
            
    # Handle real tool calls
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        if tc.function.name == "check_ticket_status":
            res = await mcp_call_tool("check_ticket_status", args)
            return {"status": "success", "reply": f"Ticket Update: {res[0].text}"}
        elif tc.function.name == "search_knowledge_base":
            res = await mcp_call_tool("search_knowledge_base", args)
            return {"status": "success", "reply": f"Here is what I found: {res[0].text[:300]}"}
            
    return {"status": "success", "reply": msg.content}

async def supervisor_agent_flow(complaint_id: int, text: str, project_name: str):
    """Assigns the ticket and sets priority/eta in the background."""
    # Mock intelligent routing logic based on text
    if "security" in text.lower() or "2fa" in text.lower() or "bypass" in text.lower():
        specialty = "Security Analyst"
        priority = "CRITICAL"
        eta = "1 hour"
    elif "db" in text.lower() or "query" in text.lower() or "database" in text.lower():
        specialty = "Database Admin"
        priority = "HIGH"
        eta = "4 hours"
    elif "timeout" in text.lower() or "backend" in text.lower() or "upload" in text.lower() or "s3" in text.lower():
        specialty = "Backend Developer"
        priority = "HIGH"
        eta = "24 hours"
    else:
        specialty = "Frontend Developer"
        priority = "MEDIUM"
        eta = "2 days"
        
    args = {
        "complaint_id": complaint_id,
        "specialty_required": specialty,
        "priority": priority,
        "eta": eta,
        "category": "Escalated to Engineering",
        "suggested_action": "Review chat history and implement fix."
    }
    
    await mcp_call_tool("route_complaint", args)
    return {"status": "routed", "details": args}

async def developer_agent_flow(query: str):
    """Copilot for developers."""
    res = await mcp_call_tool("search_developer_docs", {"query": query})
    return {"status": "success", "reply": f"**Dev Copilot found:**\n{res[0].text}"}

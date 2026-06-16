import os
import json
import asyncio
import torch

from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from langchain_huggingface import HuggingFacePipeline, ChatHuggingFace
from langchain.tools import tool

from .mcp_server import list_tools as mcp_list_tools, call_tool as mcp_call_tool

MODEL_ID = os.getenv("MODEL_ID", "Qwen/Qwen2.5-14B-Instruct")

# Lazy Loaded Native AMD ROCm Pipeline
_tokenizer = None
_model = None
_chat_model = None
_is_loading = False

async def get_chat_model():
    global _tokenizer, _model, _chat_model, _is_loading
    if _chat_model is not None:
        return _chat_model
    
    if _is_loading:
        while _chat_model is None:
            await asyncio.sleep(1)
        return _chat_model
        
    _is_loading = True
    print(f"Loading {MODEL_ID} onto AMD ROCm natively...")
    
    def load_model():
        try:
            tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                device_map="auto", 
                torch_dtype=torch.bfloat16
            )
            text_pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                max_new_tokens=512,
                max_length=None,
                temperature=0.1,
                return_full_text=False
            )
            llm = HuggingFacePipeline(pipeline=text_pipeline)
            return ChatHuggingFace(llm=llm, model_id=MODEL_ID)
        except Exception as e:
            print(f"Failed to load native model: {e}")
            return None
            
    # Load model in a separate thread to prevent blocking Uvicorn's event loop
    _chat_model = await asyncio.to_thread(load_model)
    _is_loading = False
    print("AMD ROCm LLM Ready!")
    return _chat_model

# ----------- Langchain Tool Wrappers for MCP Server -----------

@tool
async def lc_check_ticket_status(complaint_id: int) -> str:
    """Fetch the status, priority, and ETA for a given complaint ID."""
    res = await mcp_call_tool("check_ticket_status", {"complaint_id": complaint_id})
    return res[0].text

@tool
async def lc_route_complaint(complaint_id: int, specialty_required: str, priority: str, eta: str, category: str, suggested_action: str) -> str:
    """Supervisor tool: Route a complaint to an available engineer based on specialty, set priority and ETA."""
    args = {"complaint_id": complaint_id, "specialty_required": specialty_required, "priority": priority, "eta": eta, "category": category, "suggested_action": suggested_action}
    res = await mcp_call_tool("route_complaint", args)
    return res[0].text

@tool
async def lc_search_knowledge_base(project_name: str) -> str:
    """Search the software SRS files to find troubleshooting steps."""
    res = await mcp_call_tool("search_knowledge_base", {"project_name": project_name})
    return res[0].text

@tool
async def lc_search_developer_docs(query: str) -> str:
    """Mock web search / documentation search for developers."""
    res = await mcp_call_tool("search_developer_docs", {"query": query})
    return res[0].text

@tool
async def lc_update_ticket(complaint_id: int, new_eta: str, developer_message: str) -> str:
    """Developer Copilot tool: Update the ETA of a ticket and leave a message for the customer timeline."""
    args = {"complaint_id": complaint_id, "new_eta": new_eta, "developer_message": developer_message}
    res = await mcp_call_tool("update_ticket", args)
    return res[0].text

async def _run_langchain_agent(system_prompt, tools, chat_history, text):
    try:
        chat_model = await get_chat_model()
        if not chat_model:
            return None
            
        def run_agent():
            from langchain.schema import HumanMessage, SystemMessage, AIMessage
            lc_msgs = [SystemMessage(content=system_prompt)]
            for msg in chat_history:
                if msg["role"] == "user":
                    lc_msgs.append(HumanMessage(content=msg["content"]))
                else:
                    lc_msgs.append(AIMessage(content=msg["content"]))
            lc_msgs.append(HumanMessage(content=text))
            
            # Direct invocation without AgentExecutor
            res = chat_model.invoke(lc_msgs)
            return res.content
            
        result = await asyncio.to_thread(run_agent)
        return result
    except Exception as e:
        print(f"Langchain Invoke Error: {e}")
        return None

# -------------- The 3 Agents --------------

async def customer_agent_flow(complaint_id: int, text: str, project_name: str, chat_history: list):
    """Handles direct customer chat."""
    tools = [lc_check_ticket_status, lc_search_knowledge_base]
    system_prompt = f"""You are a Customer Agent for {project_name}. 
If the user asks for ticket updates, use lc_check_ticket_status with ID {complaint_id}. 
If they have an issue, use lc_search_knowledge_base to find solutions.
CRITICAL RULE: When responding to the customer, be polite and helpful. NEVER expose internal developer instructions, API logs, backend architectures, or technical jargon to the customer. You must rephrase internal knowledge base docs into friendly, customer-facing advice.
If the provided solutions do not work or the issue is severe, you must explicitly say "[ESCALATE]" in your message to notify the supervisor. Otherwise, do not say it."""
    
    # Try the real AMD model
    reply = await _run_langchain_agent(system_prompt, tools, chat_history, text)
    if reply:
        status = "escalated" if "[ESCALATE]" in reply else "success"
        reply = reply.replace("[ESCALATE]", "").strip()
        return {"status": status, "reply": reply}
        
    # Mock fallback if model fails to load
    if "update" in text.lower() or "status" in text.lower() or "eta" in text.lower():
        res = await mcp_call_tool("check_ticket_status", {"complaint_id": complaint_id})
        return {"status": "success", "reply": f"Checking your ticket... {res[0].text}"}
    elif len(chat_history) > 0 and ("not work" in text.lower() or "didn't" in text.lower()):
        return {"status": "escalated", "reply": "I see the steps didn't work. I am escalating this to my Supervisor immediately."}
    else:
        res = await mcp_call_tool("search_knowledge_base", {"project_name": project_name})
        return {"status": "success", "reply": f"Based on our docs for {project_name}:\n{res[0].text[:300]}..."}

async def supervisor_agent_flow(complaint_id: int, text: str, project_name: str):
    """Assigns the ticket and sets priority/eta in the background."""
    # Fast mock fallback for supervisor to avoid waiting on LLM for background routing
    if "security" in text.lower() or "2fa" in text.lower() or "bypass" in text.lower():
        specialty, priority, eta = "Security Analyst", "CRITICAL", "1 hour"
    elif "db" in text.lower() or "query" in text.lower() or "database" in text.lower():
        specialty, priority, eta = "Database Admin", "HIGH", "4 hours"
    elif "timeout" in text.lower() or "backend" in text.lower() or "upload" in text.lower() or "s3" in text.lower():
        specialty, priority, eta = "Backend Developer", "HIGH", "24 hours"
    else:
        specialty, priority, eta = "Frontend Developer", "MEDIUM", "2 days"
        
    args = {"complaint_id": complaint_id, "specialty_required": specialty, "priority": priority, "eta": eta, "category": "Escalated", "suggested_action": "Review chat and implement fix."}
    await mcp_call_tool("route_complaint", args)
    return {"status": "routed", "details": args}

async def developer_agent_flow(query: str, history_text: str = "", ticket_id: int = None):
    """Copilot for developers."""
    tools = [lc_search_developer_docs, lc_update_ticket]
    ctx = f"\nYou are currently viewing Ticket #{ticket_id}. Timeline:\n{history_text}\n" if ticket_id else ""
    system_prompt = f"You are a Developer AI Copilot. You can search developer docs. If the developer tells you to update a ticket ETA and notify the customer, you MUST extract the ticket ID and use the lc_update_ticket tool.{ctx}"
    
    # Try the real AMD Model
    reply = await _run_langchain_agent(system_prompt, tools, [], query)
    if reply:
        return {"status": "success", "reply": reply}
    
    # Mock fallback
    if "eta" in query.lower() or "update" in query.lower() or "ticket" in query.lower():
        # Fallback regex mock parsing
        import re
        match = re.search(r"ticket\s*(\d+)", query.lower())
        cid = int(match.group(1)) if match else 1
        res = await mcp_call_tool("update_ticket", {"complaint_id": cid, "new_eta": "Updated by Developer", "developer_message": query})
        return {"status": "success", "reply": f"Copilot Action Completed: {res[0].text}"}
            
    res = await mcp_call_tool("search_developer_docs", {"query": query})
    return {"status": "success", "reply": f"**Dev Copilot found:**\n{res[0].text}"}

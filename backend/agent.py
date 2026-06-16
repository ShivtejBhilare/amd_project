import os
import json
import asyncio
import torch

from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from langchain_huggingface import HuggingFacePipeline, ChatHuggingFace
from langchain.tools import tool

from .mcp_server import list_tools as mcp_list_tools, call_tool as mcp_call_tool

MODEL_ID = os.getenv("MODEL_ID", "Qwen/Qwen2.5-Coder-7B-Instruct")

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
                max_new_tokens=1024,
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

def get_model_status():
    if _chat_model is not None:
        return "READY"
    elif _is_loading:
        return "LOADING"
    else:
        return "UNINITIALIZED"

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

@tool
async def lc_save_memory(agent_type: str, memory_key: str, memory_value: str) -> str:
    """Save a persistent memory (e.g. successful troubleshooting steps, developer preferences). agent_type must be 'customer', 'supervisor', or 'copilot'"""
    args = {"agent_type": agent_type, "memory_key": memory_key, "memory_value": memory_value}
    res = await mcp_call_tool("save_memory", args)
    return res[0].text

@tool
async def lc_recall_memory(agent_type: str) -> str:
    """Retrieve all saved memories for your agent type to help with decision making."""
    res = await mcp_call_tool("recall_memory", {"agent_type": agent_type})
    return res[0].text

async def _run_langchain_agent(system_prompt, tools, chat_history, text):
    try:
        chat_model = await get_chat_model()
        if not chat_model:
            return None
            
        def run_agent():
            from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
            lc_msgs = [SystemMessage(content=system_prompt)]
            for msg in chat_history:
                role = msg.get("role", "")
                if role == "user":
                    lc_msgs.append(HumanMessage(content=msg["content"]))
                elif role == "assistant":
                    lc_msgs.append(AIMessage(content=msg["content"]))
            lc_msgs.append(HumanMessage(content=text))
            
            res = chat_model.invoke(lc_msgs)
            return res.content
            
        result = await asyncio.to_thread(run_agent)
        return result
    except Exception as e:
        error_msg = str(e)
        print(f"Langchain Invoke Error: {error_msg}")
        return f"LLM_ERROR: {error_msg}"

# -------------- The 3 Agents --------------

async def customer_agent_flow(complaint_id: int, text: str, project_name: str, chat_history: list):
    """Information Gathering & Status Agent for the Customer."""
    tools = [lc_check_ticket_status, lc_search_knowledge_base, lc_save_memory, lc_recall_memory]
    
    # Check if there is an active developer request
    try:
        from .database import SessionLocal, Complaint
        db = SessionLocal()
        comp = db.query(Complaint).filter(Complaint.id == complaint_id).first()
        dev_question = comp.developer_question if comp else None
        db.close()
    except:
        dev_question = None

    dev_context = f"\nCRITICAL: The developer has explicitly asked for this information: '{dev_question}'. You MUST ask the customer this exact question and wait for their reply." if dev_question else ""
    
    # Auto-recall memory for context
    memory_res = await mcp_call_tool("recall_memory", {"agent_type": "customer"})
    memory_context = f"\nYour Saved Memories:\n{memory_res[0].text}\n" if "No memories" not in memory_res[0].text else ""
    
system_prompt = f"""You are the Customer Support Agent for {project_name}. 
Your roles:
1. GATHER INFO: Ask clarifying questions about their issue.
2. TROUBLESHOOT: Use lc_search_knowledge_base to find solutions.
3. ESCALATE: If the provided solutions do not work or the issue is severe, explicitly say "[RAISE_TICKET]" in your message AND write a polite message telling the user you are assigning a developer to help them! Do not just output the tag.
4. STATUS UPDATE: If they ask for an update, ETA, or task assignment, use lc_check_ticket_status and explain the status nicely.
5. LEARN: If a user confirms a troubleshooting step solved their problem, use lc_save_memory to save it so you don't need to check the KB next time!
{memory_context}{dev_context}
CRITICAL RULES:
- Be polite and concise.
- NEVER expose internal logs, backend architectures, or API details.
- NEVER ask the customer technical questions like "check your code", "check the database", or "check the API logs". Assume the customer is non-technical!"""
    
    reply = await _run_langchain_agent(system_prompt, tools, chat_history, text)
    if reply and not reply.startswith("LLM_ERROR:"):
        status = "escalated" if "[RAISE_TICKET]" in reply else "success"
        reply = reply.replace("[RAISE_TICKET]", "").strip()
        return {"status": status, "reply": reply}
        
    err = reply.replace("LLM_ERROR:", "").strip() if reply else "Model failed to load."
    return {"status": "error", "reply": f"Cognitive routing engine outage. Details: {err}"}

async def supervisor_agent_flow(complaint_id: int, text: str, project_name: str):
    """Assigns the ticket and sets priority/eta."""
    tools = [lc_route_complaint, lc_save_memory, lc_recall_memory]
    
    memory_res = await mcp_call_tool("recall_memory", {"agent_type": "supervisor"})
    memory_context = f"\nYour Routing Memories:\n{memory_res[0].text}\n" if "No memories" not in memory_res[0].text else ""
    
    system_prompt = f"""You are the Supervisor Agent. A ticket has been raised for {project_name}.
Review the entire conversation timeline of the user's issue: '{text}'.
You MUST call the lc_route_complaint tool to assign this ticket to a developer IMMEDIATELY.
Arguments:
- complaint_id: {complaint_id}
- specialty_required: Pick one: 'Frontend Developer', 'Backend Developer', 'Database Admin', 'Security Analyst'
- priority: Assess the intensity of the issue and assign 'LOW', 'MEDIUM', 'HIGH', or 'CRITICAL'.
- eta: e.g., '2 hours', '1 day'
- category: A short 2-3 word category.
- suggested_action: Instructions for the developer based on the context.
{memory_context}
You can use lc_save_memory to save patterns or logic (e.g. "If project is Banking App, route to Security Analyst").
Reply with a summary of your routing decision."""
    
    reply = await _run_langchain_agent(system_prompt, tools, [], text)
    if reply and not reply.startswith("LLM_ERROR:"):
        return {"status": "routed", "details": reply}
        
    err = reply.replace("LLM_ERROR:", "").strip() if reply else "Model failed to load."
    return {"status": "error", "details": f"Supervisor cognitive engine failed: {err}"}

@tool
async def lc_request_client_info(complaint_id: int, developer_question: str) -> str:
    """Developer Copilot tool: Leave a question on the ticket for the customer agent to ask the client. Use this when the developer needs more info."""
    args = {"complaint_id": complaint_id, "developer_question": developer_question}
    res = await mcp_call_tool("request_client_info", args)
    return res[0].text

async def developer_agent_flow(query: str, chat_history: list = [], history_text: str = "", ticket_id: int = None):
    """Copilot for developers."""
    tools = [lc_search_developer_docs, lc_update_ticket, lc_request_client_info, lc_save_memory, lc_recall_memory]
    ctx = f"\nYou are currently viewing Ticket #{ticket_id}. Customer Timeline:\n{history_text}\n" if ticket_id else ""
    
    memory_res = await mcp_call_tool("recall_memory", {"agent_type": "copilot"})
    memory_context = f"\nYour Saved Dev Preferences & Notes:\n{memory_res[0].text}\n" if "No memories" not in memory_res[0].text else ""
    
    system_prompt = f"""You are a Developer AI Copilot.
Available Actions:
1. Search docs: use lc_search_developer_docs to help the developer.
2. Update ETA: use lc_update_ticket.
3. Request Info from Client: If the developer asks you to get more information from the client, you MUST use the lc_request_client_info tool. The Customer Agent will automatically relay your question to the client!
4. Learn: Use lc_save_memory to save developer preferences (e.g. what frameworks they use) so you can recall them later.
{memory_context}{ctx}"""
    
    reply = await _run_langchain_agent(system_prompt, tools, chat_history, query)
    if reply and not reply.startswith("LLM_ERROR:"):
        return {"status": "success", "reply": reply}
    
    err = reply.replace("LLM_ERROR:", "").strip() if reply else "Model failed to load."
    return {"status": "error", "reply": f"Copilot cognitive engine failed: {err}"}

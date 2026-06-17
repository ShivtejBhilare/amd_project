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
async def lc_route_complaint(complaint_id: int, employee_id: int, priority: str, eta: str, category: str, suggested_action: str) -> str:
    """Supervisor tool: Route a complaint to a specific engineer by ID, set priority and ETA."""
    args = {"complaint_id": complaint_id, "employee_id": employee_id, "priority": priority, "eta": eta, "category": category, "suggested_action": suggested_action}
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
async def lc_update_ticket_status(complaint_id: int, new_status: str, developer_message: str) -> str:
    """Developer Copilot tool: Update the status of a ticket."""
    args = {"complaint_id": complaint_id, "new_status": new_status, "developer_message": developer_message}
    res = await mcp_call_tool("update_ticket_status", args)
    return res[0].text

@tool
async def lc_update_ticket_eta(complaint_id: int, new_eta: str, developer_message: str) -> str:
    """Developer Copilot tool: Update the ETA of a ticket."""
    args = {"complaint_id": complaint_id, "new_eta": new_eta, "developer_message": developer_message}
    res = await mcp_call_tool("update_ticket_eta", args)
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

@tool
async def lc_get_dashboard_stats() -> str:
    """Developer Copilot tool: Fetch statistics about pending tickets, ticket priorities, and idle developers."""
    res = await mcp_call_tool("get_dashboard_stats", {})
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
- NEVER ask the customer technical questions like "check your code", "check the database", or "check the API logs". Assume the customer is non-technical!

If you need to use a tool, you MUST output ONLY a JSON object in this format:
```json
{{"tool": "tool_name", "args": {{"arg_name": "value"}}}}
```
If you do not need to use a tool, output your response directly as normal text."""
    
    reply = await _run_langchain_agent(system_prompt, tools, chat_history, text)
    
    if reply and not reply.startswith("LLM_ERROR:"):
        # Check if the LLM outputted a tool call
        try:
            import re
            import json
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', reply, re.DOTALL)
            clean_reply = json_match.group(1).strip() if json_match else reply.strip()
            data = json.loads(clean_reply)
            
            if "tool" in data and "args" in data:
                tool_name = data["tool"]
                args = data["args"]
                # Map lc_ prefixes if they exist
                mcp_tool_name = tool_name.replace("lc_", "")
                res = await mcp_call_tool(mcp_tool_name, args)
                tool_output = res[0].text
                
                # Re-run LLM with tool output
                tool_msg = f"Tool '{tool_name}' returned: {tool_output}. Now answer my original request based on this."
                chat_history.append({"role": "assistant", "content": reply})
                reply2 = await _run_langchain_agent(system_prompt, tools, chat_history, tool_msg)
                
                status = "escalated" if "[RAISE_TICKET]" in reply2 else "success"
                return {"status": status, "reply": reply2.replace("[RAISE_TICKET]", "").strip()}
        except:
            pass # Not a valid tool call JSON, just return the text
            
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
    
    try:
        from .database import SessionLocal, Employee
        db = SessionLocal()
        available_devs = db.query(Employee).filter(Employee.is_available == True).all()
        dev_list_str = "\n".join([f"ID: {d.id} | Name: {d.name} | Specialty: {d.specialty}" for d in available_devs])
        db.close()
    except:
        dev_list_str = "ID: 1 | Frontend Developer\nID: 2 | Backend Developer"
    
    system_prompt = f"""You are the Supervisor Agent. A ticket has been raised for {project_name}.
Review the entire conversation timeline of the user's issue: '{text}'.
You MUST assign this ticket to a specific available developer IMMEDIATELY.

Available Developers:
{dev_list_str}

To use the routing tool, you MUST use the following exact format:

Thought: I need to use a tool to route this complaint.
Action: lc_route_complaint
Action Input: {{"complaint_id": {complaint_id}, "employee_id": <int>, "priority": "<LOW|MEDIUM|HIGH|CRITICAL>", "eta": "<string>", "category": "<string>", "suggested_action": "<string>"}}

Example:
Thought: This issue involves SQL optimization. Charlie is the Database Admin.
Action: lc_route_complaint
Action Input: {{"complaint_id": {complaint_id}, "employee_id": 3, "priority": "HIGH", "eta": "2 hours", "category": "Database Issue", "suggested_action": "Check indexes on the table."}}

{memory_context}"""
    
    reply = await _run_langchain_agent(system_prompt, tools, [], text)
    if not reply or reply.startswith("LLM_ERROR:"):
        err = reply.replace("LLM_ERROR:", "").strip() if reply else "Model failed to load."
        return {"status": "error", "details": f"Supervisor cognitive engine failed: {err}"}
        
    try:
        import re
        import json
        tool_name = None
        args = None
        
        # Try ReAct format first
        action_match = re.search(r'Action:\s*(.*?)\n.*?Action Input:\s*(.*)', reply, re.IGNORECASE | re.DOTALL)
        if action_match:
            tool_name = action_match.group(1).strip()
            args_str = action_match.group(2).strip()
            args_str = args_str.replace("```json", "").replace("```", "").strip()
            json_block_match = re.search(r'(\{.*?\})', args_str, re.DOTALL)
            if json_block_match:
                args_str = json_block_match.group(1)
            args = json.loads(args_str)
        else:
            # Fallback to pure JSON block format
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', reply, re.DOTALL)
            if json_match:
                args = json.loads(json_match.group(1).strip())
                tool_name = args.get("tool", "lc_route_complaint")
                if "args" in args:
                    args = args["args"]

        if args is None:
            # Maybe the raw response was JSON?
            clean_reply = reply.replace("```json", "").replace("```", "").strip()
            args = json.loads(clean_reply)

        final_args = {
            "complaint_id": complaint_id,
            "employee_id": args.get("employee_id", 1),
            "priority": args.get("priority", "MEDIUM"),
            "eta": args.get("eta", "TBD"),
            "category": args.get("category", "General"),
            "suggested_action": args.get("suggested_action", "Investigate issue")
        }
        res = await mcp_call_tool("route_complaint", final_args)
        return {"status": "routed", "details": res[0].text}
    except Exception as e:
        return {"status": "error", "details": f"Supervisor failed to parse output. Raw output: {reply} | Exception: {e}"}

@tool
async def lc_request_client_info(complaint_id: int, developer_question: str) -> str:
    """Developer Copilot tool: Leave a question on the ticket for the customer agent to ask the client. Use this when the developer needs more info."""
    args = {"complaint_id": complaint_id, "developer_question": developer_question}
    res = await mcp_call_tool("request_client_info", args)
    return res[0].text

async def developer_agent_flow(query: str, chat_history: list = [], history_text: str = "", ticket_id: int = None):
    """Copilot for developers."""
    tools = [lc_search_developer_docs, lc_search_knowledge_base, lc_update_ticket_status, lc_update_ticket_eta, lc_request_client_info, lc_save_memory, lc_recall_memory, lc_get_dashboard_stats]
    ctx = f"\nYou are currently viewing Ticket #{ticket_id}. Customer Timeline:\n{history_text}\n" if ticket_id else ""
    
    if ticket_id:
        try:
            from .database import SessionLocal, Complaint
            db = SessionLocal()
            comp = db.query(Complaint).filter(Complaint.id == ticket_id).first()
            if comp:
                ctx += f"\nTicket Status: {comp.status}\nTicket ETA: {comp.eta}\nTicket Priority: {comp.priority}\nTicket Category: {comp.predicted_category}\n"
            db.close()
        except Exception as e:
            print("Failed to get ticket info", e)
    
    memory_res = await mcp_call_tool("recall_memory", {"agent_type": "copilot"})
    memory_context = f"\nYour Saved Dev Preferences & Notes:\n{memory_res[0].text}\n" if "No memories" not in memory_res[0].text else ""
    
    system_prompt = f"""You are a Developer AI Copilot.
Available Tools:
1. lc_search_developer_docs - Search developer documentation. Args: {{"query": "string"}}
2. lc_search_knowledge_base - Check project requirements. Args: {{"project_name": "string"}}
3. lc_update_ticket_status - Change ticket status. Args: {{"complaint_id": int, "new_status": "string", "developer_message": "string"}}
4. lc_update_ticket_eta - Change ticket ETA. Args: {{"complaint_id": int, "new_eta": "string", "developer_message": "string"}}
5. lc_request_client_info - Ask client for more info. Args: {{"complaint_id": int, "developer_question": "string"}}
6. lc_get_dashboard_stats - Fetch pending tickets/idle devs. Args: {{}}
7. lc_save_memory - Save preferences. Args: {{"agent_type": "copilot", "memory_key": "string", "memory_value": "string"}}

To use a tool, you MUST use the following format exactly:

Thought: I need to use a tool to fulfill this request.
Action: <tool_name>
Action Input: <json_arguments>

Example:
Thought: The developer wants to update the ETA to 2 hours.
Action: lc_update_ticket_eta
Action Input: {{"complaint_id": {ticket_id if ticket_id else 123}, "new_eta": "2 hours", "developer_message": "Need more time to debug"}}

If you do not need to use a tool, just answer normally without "Thought" or "Action".
{memory_context}{ctx}"""

    reply = await _run_langchain_agent(system_prompt, tools, chat_history, query)
    
    if reply and not reply.startswith("LLM_ERROR:"):
        # Check if the LLM outputted a tool call
        try:
            import re
            import json
            
            tool_name = None
            args = None
            
            # Try ReAct format first
            action_match = re.search(r'Action:\s*(.*?)\n.*?Action Input:\s*(.*)', reply, re.IGNORECASE | re.DOTALL)
            if action_match:
                tool_name = action_match.group(1).strip()
                args_str = action_match.group(2).strip()
                args_str = args_str.replace("```json", "").replace("```", "").strip()
                json_block_match = re.search(r'(\{.*?\})', args_str, re.DOTALL)
                if json_block_match:
                    args_str = json_block_match.group(1)
                args = json.loads(args_str)
            else:
                # Fallback to pure JSON block format
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', reply, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(1).strip())
                    if "tool" in data and "args" in data:
                        tool_name = data["tool"]
                        args = data["args"]
                        
            if tool_name and args is not None:
                mcp_tool_name = tool_name.replace("lc_", "")
                res = await mcp_call_tool(mcp_tool_name, args)
                tool_output = res[0].text
                
                # Re-run LLM with tool output
                tool_msg = f"Tool '{tool_name}' returned: {tool_output}. Now answer my original request based on this."
                chat_history.append({"role": "assistant", "content": reply})
                reply2 = await _run_langchain_agent(system_prompt, tools, chat_history, tool_msg)
                return {"status": "success", "reply": reply2}
        except Exception as e:
            print(f"Failed to parse copilot tool JSON: {e}")
            pass # Not a valid tool call JSON, just return the text
            
        return {"status": "success", "reply": reply}
    
    err = reply.replace("LLM_ERROR:", "").strip() if reply else "Model failed to load."
    return {"status": "error", "reply": f"Copilot cognitive engine failed: {err}"}

import os
import json
from openai import AsyncOpenAI
from .mcp_server import list_tools as mcp_list_tools, call_tool as mcp_call_tool

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "llava-1.5-7b-hf") 

client = AsyncOpenAI(api_key="EMPTY", base_url=VLLM_BASE_URL)

async def process_complaint_with_agent(complaint_id: int, text: str, image_url: str = None, customer_id: int = None, project_name: str = None, chat_history: list = None):
    if chat_history is None:
        chat_history = []
        
    mcp_tools = await mcp_list_tools()
    
    openai_tools = []
    for t in mcp_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.inputSchema
            }
        })
        
    system_prompt = f"""You are an intelligent Customer Experience (CX) Routing Engine.
Your job is to analyze customer complaints for the project: {project_name}.

You have a conversational memory. Review the chat history. 
1. Use the `search_knowledge_base` tool to look up the SRS for {project_name}.
2. Check if the issue can be solved by simple troubleshooting steps from the knowledge base.
3. If the customer is trying the steps for the first time, provide them and DO NOT route to an engineer.
4. If the customer indicates the steps did not work, or the issue is inherently hardware/complex, you MUST use the `route_complaint` tool to escalate it.
Valid priorities: LOW, MEDIUM, HIGH, CRITICAL.
Valid specialties: GPU Drivers, Thermal Management, Hardware Replacements, CPU Performance.
"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    content = [{"type": "text", "text": text}]
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_url}"}})
        
    messages.append({"role": "user", "content": content})
    
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        
        if message.tool_calls:
            for tool_call in message.tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                print(f"Executing MCP Tool: {function_name} with args: {arguments}")
                result = await mcp_call_tool(function_name, arguments)
                
                if function_name == "search_knowledge_base":
                    return {"status": "success", "routing_details": None, "agent_reply": f"Based on our knowledge base: {result[0].text[:300]}...", "action": "RESOLVED"}
                elif function_name == "route_complaint":
                    return {"status": "success", "routing_details": arguments, "agent_reply": message.content, "action": "ROUTED"}
        
        return {"status": "success", "agent_reply": message.content, "routing_details": None, "action": "RESOLVED"}
    except Exception as e:
        print(f"Error calling vLLM (using mock fallback): {e}")
        
        # MOCK RAG / CONVERSATION FALLBACK
        if len(chat_history) > 0:
            mock_args = {
                "complaint_id": complaint_id,
                "specialty_required": "Thermal Management" if "ryzen" in str(project_name).lower() else "GPU Drivers",
                "priority": "HIGH",
                "category": "Escalated Issue",
                "suggested_action": "Customer tried self-service. Escalate to engineer."
            }
            await mcp_call_tool("route_complaint", mock_args)
            return {"status": "success", "routing_details": mock_args, "agent_reply": "Since those steps didn't work, I have escalated this to an expert engineer who will review the complete history.", "action": "ROUTED"}
        else:
            srs_snippet = "Download the AMD Cleanup Utility and reinstall WHQL drivers" if "radeon" in str(project_name).lower() else "Check AIO pump or enable Memory Context Restore"
            reply = f"Based on the {project_name} documentation: {srs_snippet}. Please try this and let me know if it helps."
            return {"status": "success", "routing_details": None, "agent_reply": reply, "action": "RESOLVED"}

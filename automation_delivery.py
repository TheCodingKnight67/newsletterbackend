"""Delivery is controlled by application code, never by model tool calls."""
import asyncio
import json
import os
from email_design import render_email


def email_parts(job, unsubscribe_url=None, theme=None):
    return render_email(job, unsubscribe_url, theme)


def validate_delivery_settings():
    transport = os.getenv('EMAIL_TRANSPORT', 'mailjet')
    if transport == 'mailjet':
        required = ('MAILJET_API_KEY', 'MAILJET_API_SECRET', 'MAILJET_SENDER_EMAIL')
    elif transport == 'mcp':
        required = ('MCP_EMAIL_TOOL', 'MCP_SERVER_URL' if os.getenv('MCP_SERVER_URL') else 'MCP_SERVER_COMMAND')
    else:
        raise RuntimeError('EMAIL_TRANSPORT must be mailjet or mcp')
    missing = [key for key in required if not os.getenv(key, '').strip()]
    if missing:
        raise RuntimeError('Missing delivery settings: ' + ', '.join(missing) + '. Add them to newsbackend/.env and restart the worker.')


def deliver(job, unsubscribe_url=None, theme=None):
    validate_delivery_settings()
    payload = json.loads(job.payload)
    text, markup = email_parts(job, unsubscribe_url, theme)
    transport = os.getenv("EMAIL_TRANSPORT", "mailjet")
    if transport == "mcp":
        return asyncio.run(mcp_send(job, payload["email"], text, markup))
    if transport != "mailjet":
        raise ValueError("EMAIL_TRANSPORT must be mailjet or mcp")
    from email_service import mailjet, MAILJET_SENDER_EMAIL

    result = mailjet.send.create(data={"Messages": [{
        "From": {"Email": MAILJET_SENDER_EMAIL, "Name": payload["character_name"]},
        "To": [{"Email": payload["email"]}], "Subject": job.subject,
        "TextPart": text, "HTMLPart": markup, "CustomID": job.id,
    }]})
    response = result.json()
    if result.status_code != 200 or any(m.get("Status") != "success" for m in response.get("Messages", [])) or not response.get("Messages"):
        raise RuntimeError("Mailjet did not acknowledge delivery; inspect the provider before retrying")
    return json.dumps(response)


async def mcp_send(job, recipient, text, markup):
    from contextlib import AsyncExitStack
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client

    tool_name = os.environ["MCP_EMAIL_TOOL"]
    # Map logical fields to the existing tool's parameter names in server configuration.
    fields = json.loads(os.getenv("MCP_EMAIL_FIELDS", '{"recipient":"to","subject":"subject","text":"body"}'))
    values = {"recipient": recipient, "subject": job.subject, "text": text,
              "html": markup, "idempotency_key": job.id}
    if not {"recipient", "subject"}.issubset(fields) or not ({"text", "html"} & fields.keys()):
        raise ValueError("MCP_EMAIL_FIELDS must include recipient, subject, and text or html")
    arguments = {target: values[source] for source, target in fields.items()}
    async with AsyncExitStack() as stack:
        if os.getenv("MCP_SERVER_URL"):
            token = os.getenv("MCP_SERVER_TOKEN")
            headers = {"Authorization": f"Bearer {token}"} if token else None
            streams = await stack.enter_async_context(streamablehttp_client(os.environ["MCP_SERVER_URL"], headers=headers))
        else:
            params = StdioServerParameters(command=os.environ["MCP_SERVER_COMMAND"],
                args=json.loads(os.getenv("MCP_SERVER_ARGS", "[]")), env=dict(os.environ))
            streams = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
        await session.initialize()
        tools = await session.list_tools()
        if tool_name not in {tool.name for tool in tools.tools}:
            raise ValueError("Configured MCP email tool was not advertised by server")
        result = await session.call_tool(tool_name, arguments)
        if result.isError:
            raise RuntimeError("MCP reported a delivery error; inspect the provider before retrying")
        # This receipt means the tool returned success; actual semantics depend on that server.
        return result.model_dump_json()

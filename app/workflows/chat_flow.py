from __future__ import annotations

from datetime import datetime

from app.services.create_config import ALLOWED_VALIDATION_TARGETS


async def handle_chat_send(request, app, templates, *, message: str, validation_target: str, selected_vs_name: str, build_evs_reply):
    if not app.state.evs_state["connected"]:
        app.state.chat_history.append(
            {
                "role": "assistant",
                "content": "Step 3 is locked. Connect and authenticate in Step 1 first.",
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        app.state.chat_history = app.state.chat_history[-80:]
        return templates.TemplateResponse(
            request,
            "partials/chat_messages.html",
            {"messages": app.state.chat_history, "evs": app.state.evs_state},
        )

    clean = message.strip()
    selected_target = validation_target.strip().lower()
    if selected_target not in ALLOWED_VALIDATION_TARGETS:
        selected_target = "vectorstore.ask"
    posted_vs_name = selected_vs_name.strip()
    if posted_vs_name:
        app.state.evs_state["selected_vs_name"] = posted_vs_name
    if clean:
        app.state.chat_history.append(
            {
                "role": "user",
                "content": clean,
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        app.state.chat_history.append(
            {
                "role": "assistant",
                "content": build_evs_reply(clean, selected_target),
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        app.state.chat_history = app.state.chat_history[-80:]

    return templates.TemplateResponse(
        request,
        "partials/chat_messages.html",
        {"messages": app.state.chat_history, "evs": app.state.evs_state},
    )


async def handle_chat_reset(request, app, templates):
    app.state.chat_history = []
    return templates.TemplateResponse(
        request,
        "partials/chat_messages.html",
        {"messages": app.state.chat_history, "evs": app.state.evs_state},
    )

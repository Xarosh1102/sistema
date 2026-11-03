REGISTERED_TOOLS = []


def register_tool(func):
    """Регистрирует функцию в списке инструментов ИИ без создания дубликатов."""
    func_name = getattr(func, "__name__", str(func))
    for i, existing in enumerate(REGISTERED_TOOLS):
        if getattr(existing, "__name__", str(existing)) == func_name:
            REGISTERED_TOOLS[i] = func
            return func
    REGISTERED_TOOLS.append(func)
    return func